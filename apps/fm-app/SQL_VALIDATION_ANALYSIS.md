# SQL Syntax Validation with sqlglot - Analysis & Recommendation

## Question
Should we add sqlglot-based SQL syntax validation BEFORE running `explain_analyze` on the database?

## Current Flow
```
LLM generates SQL
    ↓
explain_analyze on database (50-500ms)
    ↓ Error?
Repair loop with DB error message
    ↓ Success
Execute query
```

## Proposed Flow
```
LLM generates SQL
    ↓
sqlglot syntax check (1-10ms) ← FAST PRE-CHECK
    ↓ Error?
Repair loop with parse error
    ↓ Success
explain_analyze on database (50-500ms) ← SOURCE OF TRUTH
    ↓ Error?
Repair loop with DB error message
    ↓ Success
Execute query
```

## PROS ✅

### 1. **Speed** (10-50x faster)
- sqlglot: ~1-10ms (local, in-memory)
- Database: ~50-500ms (network + execution)
- Faster feedback for syntax errors

### 2. **Reduced Database Load**
```python
# Without sqlglot:
Bad SQL → DB query → Error → Retry → DB query → Error → Retry

# With sqlglot:
Bad SQL → Local parse → Error → Retry → Local parse → Success → DB query ✓
```
- Saves 2-3 database queries per syntax error
- Reduces connection pool usage
- Lower warehouse costs

### 3. **Better Error Messages**
```python
# sqlglot error (precise):
"Syntax error at line 3: Expected closing parenthesis after 'wallet_address'"

# Database error (cryptic):
"DB::Exception: Syntax error: failed at position 127 (line 3, column 15)"
```

### 4. **Catch Common Mistakes**
- Missing commas: `SELECT wallet amount` → "Expected comma"
- Typos: `SELCT` → "Unknown keyword"
- Unmatched parentheses: `SUM(amount` → "Missing closing paren"
- Invalid keywords: `SELECTT` → "Unexpected token"

## CONS ❌

### 1. **False Positives** ⚠️ (BIGGEST RISK)

ClickHouse-specific features that sqlglot might reject:

```sql
-- ClickHouse SAMPLE clause
SELECT * FROM trades SAMPLE 0.1
-- sqlglot: "Unexpected token SAMPLE"

-- ClickHouse count() shorthand
SELECT count() FROM trades
-- sqlglot: "count() requires an argument"

-- ClickHouse-specific functions
SELECT cityHash64(wallet) FROM trades
SELECT JSONExtractString(data, 'key') FROM events
-- sqlglot: "Unknown function"

-- Array operations
SELECT wallet, item FROM wallets ARRAY JOIN items AS item
-- sqlglot: "Invalid JOIN syntax"

-- MergeTree engine syntax
CREATE TABLE test ENGINE = MergeTree() ORDER BY id
-- sqlglot: "Invalid CREATE syntax"
```

### 2. **False Negatives**

sqlglot will NOT catch:
```sql
-- Column doesn't exist
SELECT nonexistent_column FROM trades
-- sqlglot: ✓ (valid syntax)
-- database: ✗ (column not found)

-- Table doesn't exist
SELECT * FROM fake_table
-- sqlglot: ✓ (valid syntax)
-- database: ✗ (table not found)

-- Type mismatch
SELECT wallet_address + amount  -- string + number
-- sqlglot: ✓ (valid syntax)
-- database: ✗ (type error)
```

**Conclusion**: `explain_analyze` is ALWAYS needed as source of truth!

### 3. **Dialect Accuracy Gap**
- ClickHouse releases new features
- sqlglot needs to catch up
- Custom UDFs won't be recognized

## RECOMMENDATION 💡

### **Option A: Conservative (Recommended)**

**Use sqlglot as a FAST PRE-CHECK, not a blocker:**

```python
# 1. Try sqlglot validation (fast)
result = validate_sql_syntax(sql, strict=False)

if result.error:
    logger.info(f"sqlglot pre-check error: {result.error}")
    # Don't fail - just log

if result.warning:
    logger.info(f"sqlglot warning: {result.warning}")

# 2. ALWAYS run explain_analyze (source of truth)
analyzed = await db_meta_mcp_analyze_query(...)

if analyzed.get("error"):
    # This is the REAL error - use for repair loop
    repair_loop(analyzed["error"])
```

**Benefits**:
- Catch obvious syntax errors fast
- No false positive blocking
- Still validate everything with database
- Get metrics on sqlglot accuracy

### **Option B: Aggressive (Not Recommended)**

**Block on sqlglot errors:**

```python
# 1. sqlglot validation
result = validate_sql_syntax(sql, strict=True)

if not result.valid:
    # FAIL immediately - don't hit database
    return repair_loop(result.error)

# 2. Only run explain_analyze if sqlglot passed
analyzed = await db_meta_mcp_analyze_query(...)
```

**Problems**:
- **False positives block valid SQL**
- User frustration with ClickHouse-specific features
- Not recommended unless you're 100% confident in sqlglot accuracy

### **Option C: Smart Hybrid**

**Skip sqlglot for ClickHouse-specific SQL:**

```python
# 1. Check if SQL has ClickHouse-specific features
if should_skip_sqlglot_validation(sql):
    logger.info("Skipping sqlglot - ClickHouse-specific syntax detected")
else:
    # 2. Run sqlglot validation
    result = validate_sql_syntax(sql, strict=False)
    if result.error:
        # Log but don't block
        logger.warning(f"sqlglot pre-check: {result.error}")

# 3. ALWAYS run explain_analyze
analyzed = await db_meta_mcp_analyze_query(...)
```

## Integration Example

### Minimal Integration (Option A)

```python
# In interactive_flow.py, before explain_analyze

from fm_app.validators.sql_validator import validate_sql_syntax

# ... after LLM generates SQL

extracted_sql = new_metadata.get("sql")

# Fast pre-check with sqlglot (optional, non-blocking)
print(">>> PRE SQLGLOT CHECK", stopwatch.lap())
sql_check = validate_sql_syntax(extracted_sql, strict=False)

if not sql_check.valid:
    logger.info(
        "SQL syntax pre-check failed",
        flow_stage="sqlglot_precheck",
        error=sql_check.error,
    )
    # Could add to metrics/monitoring

if sql_check.warning:
    logger.info(
        "SQL syntax pre-check warning",
        flow_stage="sqlglot_precheck",
        warning=sql_check.warning,
    )

print(">>> POST SQLGLOT CHECK", stopwatch.lap())

# ALWAYS run explain_analyze (source of truth)
print(">>> PRE ANALYZE", stopwatch.lap())
analyzed = await db_meta_mcp_analyze_query(
    req, extracted_sql, 5, settings, logger
)
print(">>> POST ANALYZE", stopwatch.lap())

if analyzed.get("error"):
    # This is the REAL error - use for repair loop
    # ...
```

### Metrics to Track

```python
# Track sqlglot accuracy
metrics = {
    "sqlglot_rejected_db_accepted": 0,  # False positive
    "sqlglot_accepted_db_rejected": 0,  # False negative
    "sqlglot_rejected_db_rejected": 0,  # True positive
    "sqlglot_accepted_db_accepted": 0,  # True negative
}

# After both validations:
if not sql_check.valid and not analyzed.get("error"):
    metrics["sqlglot_rejected_db_accepted"] += 1
    logger.warning("sqlglot false positive", sql=sql[:100])
```

## Final Recommendation

### **YES, add it as a fast pre-check:**

✅ **DO**:
- Use `strict=False` (don't block on warnings)
- Log errors/warnings for monitoring
- **ALWAYS** run explain_analyze after
- Track false positive/negative rates
- Use it as a development/debugging aid

❌ **DON'T**:
- Block on sqlglot errors (false positives!)
- Skip explain_analyze if sqlglot passes
- Use it as the only validation
- Expect 100% accuracy with ClickHouse-specific SQL

### **Expected Impact**:

**Optimistic scenario** (70% of errors are basic syntax):
```
Before: 100 bad SQL → 100 DB queries → 100 errors → 100 retries
After:  100 bad SQL → 70 caught by sqlglot (no DB hit) → 30 DB queries
Result: ~70% reduction in wasted DB queries
```

**Realistic scenario** (30% of errors are basic syntax):
```
Before: 100 bad SQL → 100 DB queries
After:  100 bad SQL → 30 caught by sqlglot → 70 DB queries
Result: ~30% reduction in wasted DB queries
```

**Cost**:
- ~5-10ms added latency per query (negligible)
- Small code complexity increase
- Need to monitor false positive rate

### **When to Reconsider**:

If after implementation you see:
- High false positive rate (>10%) - blocking valid ClickHouse SQL
- Low true positive rate (<20%) - not catching enough errors
- Maintenance burden from sqlglot updates

Then: Keep logging but don't use for flow control.

---

## TL;DR

**Add sqlglot as a fast pre-check, but always run explain_analyze as the source of truth. Don't block on sqlglot errors - just log and monitor.**
