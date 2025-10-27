# Data Handler Analysis - `/data/{query_id}` Endpoint

## Current Implementation Review

### What It Does
```python
# routes.py get_query_data() endpoint

1. Fetch SQL from query_id
2. Apply sort_by and pagination via build_sorted_paginated_sql()
3. Execute against warehouse (ClickHouse via wh_session)
4. Return paginated results with total count
```

### Current Approach
```sql
-- Wraps user SQL in subquery
SELECT t.*, COUNT(*) OVER () AS total_count
FROM (
    {user_sql}
) AS t
ORDER BY t.{sort_column} ASC/DESC
LIMIT :limit
OFFSET :offset
```

---

## Issues & Concerns

### 🔴 CRITICAL: Column Validation Gap

**Problem**: `sort_by` isn't validated against QueryMetadata columns!

```python
# Current code:
col = _sanitize_sort_by(sort_by)  # Only checks if valid identifier
if col:
    base += f"\nORDER BY t.{col} {direction}"

# What if sort_by = "nonexistent_column"?
# → Database error: "Unknown column 'nonexistent_column'"
```

**We just fixed QueryMetadata.column_name, but we're not using it here!**

```python
# Should be:
query_metadata = await get_query_by_id(query_id, db)
valid_columns = [col.column_name for col in query_metadata.columns]

if sort_by not in valid_columns:
    raise HTTPException(400, f"Invalid sort column: {sort_by}")
```

---

### 🟡 MEDIUM: No Database Dialect Detection

**Problem**: Code assumes generic SQL but uses ClickHouse-specific features

```python
# Current: Hardcoded to ClickHouse
with wh_session() as session:
    # Uses COUNT(*) OVER () - SQL standard but not universal
    # Uses LIMIT/OFFSET - not all databases support this
```

**Available but unused**:
- `QueryMetadata.db_dialect` field (set to "clickhouse")
- Engine dialect from SQLAlchemy: `wh_engine.dialect.name`

**Dialect differences**:

| Feature | ClickHouse | PostgreSQL | MySQL | SQL Server |
|---------|-----------|------------|-------|------------|
| `LIMIT/OFFSET` | ✅ | ✅ | ✅ | ❌ (uses `FETCH FIRST`) |
| `COUNT(*) OVER()` | ✅ | ✅ | ✅ (8.0+) | ✅ |
| NULL handling | `NULLS FIRST` default | `NULLS LAST` default | No control | No control |

---

### 🟡 MEDIUM: Performance - COUNT(*) OVER()

**Problem**: `COUNT(*) OVER()` can be slow on large result sets

```sql
-- Current approach:
SELECT t.*, COUNT(*) OVER () AS total_count
FROM (...) AS t
LIMIT 100 OFFSET 0

-- For 1M row result:
-- ClickHouse must process entire 1M rows to get count
-- Even though we only return 100 rows!
```

**Alternatives**:

1. **Separate COUNT query** (more queries, but can be cached)
2. **Approximate count** (ClickHouse has `count() SETTINGS max_rows_to_read = ...`)
3. **Client-side cursor** (database keeps state, complex)
4. **No total count** (infinite scroll, best performance)

---

### 🟢 LOW: SQL Injection Protection

**Status**: ✅ **Good!**

```python
# Good: Column name validation
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")

# Good: Parameterized limit/offset
session.execute(text(combined_sql), {"limit": limit, "offset": offset})

# Good: Sanitization
col = _sanitize_sort_by(sort_by)
```

**However**: Still vulnerable if `sort_by` contains valid identifier for non-existent column.

---

### 🟢 LOW: Subquery Approach

**Status**: ✅ **Good and safe!**

```sql
-- Wrapping in subquery is correct:
SELECT t.* FROM (user_sql) AS t
```

**Why this is good**:
- Isolates user SQL from our modifications
- Prevents ORDER BY/LIMIT conflicts
- Works with CTEs, complex queries, etc.
- Generic across databases

---

### 🟡 MEDIUM: Error Handling

**Problem**: Generic errors don't help users

```python
except Exception as e:
    raise HTTPException(
        status_code=500,
        detail=f"Error executing query: {str(e)}"
    )

# User sees:
# "Error executing query: DB::Exception: Unknown column 'foo'"
#
# Should see:
# "Invalid sort column 'foo'. Available columns: wallet, amount, date"
```

---

### 🟢 LOW: ORDER BY Stripping

**Status**: ✅ **Good approach!**

```python
def _strip_final_order_by_and_trailing(sql: str) -> str:
    # Removes ORDER BY, LIMIT, OFFSET from user SQL
    # So we can add our own
```

**Why this is correct**:
- User SQL might have ORDER BY from LLM
- We want to override with user's sort preference
- Regex approach is reasonable

**Minor concern**: Complex regex could fail on edge cases
- Nested subqueries with ORDER BY
- Comments with "ORDER BY" in them
- String literals containing "ORDER BY"

---

## Recommendations

### 1. **Add Column Validation** (CRITICAL - Do This First)

```python
@api_router.get("/data/{query_id}")
async def get_query_data(
    query_id: UUID,
    sort_by: Optional[str] = None,
    sort_order: str = Query("asc", regex="^(asc|desc)$"),
    # ...
):
    # Fetch SQL and metadata
    query_response = await get_query_by_id(query_id=query_id, db=db)

    # Validate sort_by against QueryMetadata columns
    if sort_by:
        if not query_response or not query_response.columns:
            raise HTTPException(
                status_code=400,
                detail="Cannot sort: query metadata not available"
            )

        valid_columns = {col.column_name.lower() for col in query_response.columns if col.column_name}

        if sort_by.lower() not in valid_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort column '{sort_by}'. Available: {sorted(valid_columns)}"
            )

    # Continue with existing logic...
```

**Benefits**:
- Uses the QueryMetadata we just fixed!
- Clear error messages
- Prevents database errors
- Validates before expensive query

---

### 2. **Add Dialect Detection** (NICE TO HAVE)

```python
def get_warehouse_dialect() -> str:
    """Detect warehouse database dialect."""
    # Option 1: From engine
    return wh_engine.dialect.name  # 'clickhouse', 'postgresql', etc.

    # Option 2: From settings (if you have it)
    # return settings.database_wh_driver  # 'clickhouse', 'postgresql+psycopg2'

def build_sorted_paginated_sql(
    user_sql: str,
    sort_by: Optional[str],
    sort_order: str,
    include_total_count: bool = False,
    dialect: Optional[str] = None,  # NEW
) -> str:
    dialect = dialect or "generic"
    body = _strip_final_order_by_and_trailing(user_sql)

    # ... existing logic ...

    # Dialect-specific pagination
    if dialect == "sqlserver":
        # SQL Server doesn't support LIMIT/OFFSET
        # Must use OFFSET ... FETCH FIRST
        base += "\nOFFSET :offset ROWS"
        base += "\nFETCH FIRST :limit ROWS ONLY"
    else:
        # Generic: ClickHouse, PostgreSQL, MySQL
        base += "\nLIMIT :limit"
        base += "\nOFFSET :offset"

    return base
```

**Benefits**:
- Future-proof for multiple warehouses
- Correct syntax per database
- Easy to test

**When you need this**:
- If you plan to support multiple warehouse types
- If you want to use database-specific optimizations

**When you don't**:
- If you're only using ClickHouse (current state)

---

### 3. **Optimize COUNT Performance** (OPTIONAL)

**Option A: Separate COUNT query (recommended for ClickHouse)**

```python
# Instead of COUNT(*) OVER()
# Run two queries:

# 1. Get total count (can be cached)
count_sql = f"SELECT count(*) as total FROM ({sql}) AS t"
total_count = session.execute(text(count_sql)).scalar()

# 2. Get page data
data_sql = build_sorted_paginated_sql(sql, sort_by, sort_order, include_total_count=False)
rows = session.execute(text(data_sql), {"limit": limit, "offset": offset}).fetchall()
```

**Benefits**:
- Faster for large result sets
- Can cache total count
- ClickHouse optimizes count() queries

**Tradeoffs**:
- Two queries instead of one
- Slight risk of count changing between queries (rare)

**Option B: Approximate count for ClickHouse**

```sql
-- ClickHouse-specific optimization
SELECT t.*, count() OVER () AS total_count
FROM (user_sql) AS t
SETTINGS max_rows_to_read = 10000
LIMIT :limit
OFFSET :offset
```

**Option C: No total count**

```python
# Don't include COUNT(*) OVER() at all
# Use infinite scroll / "load more" pattern
# Frontend doesn't need exact total for UX
```

---

### 4. **Better Error Messages** (EASY WIN)

```python
try:
    result = session.execute(text(combined_sql), {"limit": limit, "offset": offset})
    # ...
except Exception as e:
    error_msg = str(e)

    # Parse common errors
    if "Unknown column" in error_msg or "column" in error_msg.lower():
        raise HTTPException(
            status_code=400,
            detail=f"Sort failed - column may not exist in result set: {error_msg}"
        )
    elif "syntax error" in error_msg.lower():
        raise HTTPException(
            status_code=500,
            detail=f"SQL syntax error (likely internal): {error_msg}"
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Error executing query: {error_msg}"
        )
```

---

### 5. **Add NULL Handling** (NICE TO HAVE)

```python
# For ClickHouse, control NULL sorting
if col:
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"
    null_handling = "NULLS LAST" if direction == "ASC" else "NULLS FIRST"
    base += f"\nORDER BY t.{col} {direction} {null_handling}"
```

**When you need this**:
- If your data has NULLs
- If you want consistent NULL behavior across databases
- If users complain about NULL ordering

---

## Summary & Priorities

### ✅ What's Good
1. SQL injection protection (parameterized queries, identifier validation)
2. Subquery wrapping approach
3. ORDER BY stripping logic

### 🔴 Critical Issues (Fix Now)
1. **Column validation missing** - sort_by not checked against QueryMetadata.columns
2. **No connection to metadata** - we validated column_name but don't use it here!

### 🟡 Medium Issues (Consider)
1. No dialect detection (but okay if only ClickHouse)
2. COUNT(*) OVER() performance (optimize if slow)
3. Generic error messages (improve UX)

### 🟢 Nice to Have
1. Dialect-specific optimizations
2. NULL handling control
3. Separate count query for caching

---

## Recommended Changes (Priority Order)

### Phase 1: Critical (Do Now)
```python
# Add column validation against QueryMetadata
# See recommendation #1 above
```

### Phase 2: Quick Wins (If Time Permits)
```python
# Better error messages
# See recommendation #4 above
```

### Phase 3: Future (When Needed)
```python
# Dialect detection (if adding new warehouses)
# COUNT optimization (if performance issues)
# NULL handling (if user complaints)
```

---

## Decision: Generic vs Adaptive SQL?

**Current**: Generic SQL (works for most databases)

**Recommendation**: **Adaptive with dialect detection**

```python
def build_sorted_paginated_sql(
    user_sql: str,
    sort_by: Optional[str],
    sort_order: str,
    include_total_count: bool = False,
    dialect: str = "clickhouse",  # Default to current
) -> str:
    # Use generic approach by default
    # Add dialect-specific optimizations when needed

    # Example:
    if dialect == "clickhouse" and include_total_count:
        # Could use approximate count for performance
        pass
    elif dialect == "sqlserver":
        # Use FETCH FIRST instead of LIMIT
        pass
    # etc.
```

**Why adaptive is better**:
- Future-proof
- Easy to optimize per database
- No downside (defaults to generic)
- Can detect dialect from engine

---

## Code Quality Score

| Aspect | Score | Notes |
|--------|-------|-------|
| Security | 8/10 | Good SQL injection protection, but column validation missing |
| Correctness | 6/10 | Works but allows invalid sort columns |
| Performance | 7/10 | COUNT(*) OVER() could be optimized |
| Maintainability | 7/10 | Clean code, could use dialect abstraction |
| Error Handling | 5/10 | Generic errors, not user-friendly |
| **Overall** | **6.6/10** | Solid foundation, needs column validation |

---

## Next Steps

**Immediate action**: Add column validation (see recommendation #1)

**Then**: Review if COUNT(*) OVER() causes performance issues in production

**Future**: Consider dialect detection when/if you add more warehouse types
