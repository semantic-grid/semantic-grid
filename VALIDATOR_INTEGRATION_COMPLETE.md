# Validator Integration Complete ✓

The QueryMetadata validator has been successfully integrated into the interactive flow worker!

## What Was Done

### 1. **Prompt Updated** ✓
- File: `packages/resources/fm_app/system-pack/v1.0.0/slots/interactive_query/prompt.md`
- Made `column_name` required with explicit instructions
- Added examples of correct vs incorrect usage

### 2. **Validator Library Created** ✓
- Files:
  - `fm_app/validators/metadata_validator.py` - Main validator using sqlglot
  - `fm_app/validators/__init__.py` - Package exports
  - `examples/validate_metadata_example.py` - Usage examples
  - `METADATA_VALIDATION.md` - Integration guide

### 3. **Integrated into Interactive Flow** ✓
- File: `fm_app/workers/interactive_flow.py`
- Added validation at two key points:

#### A. Interactive Query Flow (Line ~730)
- Validates metadata immediately after LLM generates it
- If validation fails:
  - Logs detailed warning with errors
  - Adds validation errors to the repair loop
  - LLM gets another chance to fix the metadata (up to 3 attempts)
  - Continues to SQL validation

```python
# Validate QueryMetadata consistency
validation_result = MetadataValidator.validate_metadata(
    llm_response, dialect="clickhouse"
)
if not validation_result["valid"]:
    logger.warning("QueryMetadata validation failed", ...)
    # Add to repair loop
    if attempt < 3:
        validation_error_msg = (
            "QueryMetadata validation errors detected:\n"
            f"{errors_list}\n\n"
            f"SQL result columns: {validation_result['sql_columns']}\n"
            # ... detailed error message
        )
        messages.append({"role": "system", "content": validation_error_msg})
        attempt += 1
        continue
```

#### B. Manual Query Flow (Line ~217)
- Validates metadata after LLM generates it
- Logs warnings if validation fails
- No repair loop (manual query doesn't support retries)

## How It Works

### Flow Diagram

```
User Request
    ↓
LLM Generates QueryMetadata
    ↓
[NEW] Validate Metadata ← Parse SQL, extract columns, compare
    ↓
Valid? ──No──> Log warning + Add to repair loop → Retry (up to 3x)
    ↓ Yes
SQL Analysis (explain_analyze)
    ↓
Valid? ──No──> Add SQL error to repair loop → Retry (up to 3x)
    ↓ Yes
Execute Query
    ↓
Return Results
```

### What Gets Validated

The validator checks:
1. **Column name consistency**: All columns in metadata match SQL result columns
2. **No expressions in column_name**: No `"DATE(block_time)"` - must be `"trade_date"`
3. **No table prefixes**: No `"t.wallet"` - must be `"wallet"`
4. **Valid identifiers**: Must be simple SQL identifiers (letters, numbers, underscores)

### Example Validation Error (in logs)

```json
{
  "flow_stage": "metadata_validation",
  "errors": [
    "column_name 'DATE(block_time)' contains function/expression - should be the alias instead",
    "column_name 'DATE(block_time)' is not a valid SQL identifier",
    "Columns in SQL but missing from metadata: ['trade_date']"
  ],
  "sql_columns": ["wallet", "trade_date", "total_amount"],
  "metadata_columns": ["wallet", "DATE(block_time)", "total_amount"]
}
```

### Example Repair Loop Message (to LLM)

```
QueryMetadata validation errors detected:
  - column_name 'DATE(block_time)' contains function/expression - should be the alias instead
  - column_name 'DATE(block_time)' is not a valid SQL identifier
  - Columns in SQL but missing from metadata: ['trade_date']

SQL result columns: ['wallet', 'trade_date', 'total_amount']
Metadata column_name values: ['wallet', 'DATE(block_time)', 'total_amount']

Please fix the column_name values in the Column objects.
Remember: column_name must be the alias (the name after AS), not the expression.
For example: 'DATE(block_time) AS trade_date' -> column_name should be 'trade_date'
```

## Benefits

1. **Early Detection**: Catches column_name errors before SQL execution
2. **Automatic Repair**: LLM gets clear feedback and fixes the issue
3. **Better Logging**: Detailed logs help debug LLM accuracy
4. **No Breaking Changes**: Fully backward compatible
5. **Deterministic**: Uses sqlglot to parse SQL and extract actual column names

## Testing

### Manual Test
```bash
cd apps/fm-app
uv run python examples/validate_metadata_example.py
```

### Real Flow Test
When the interactive flow runs:
1. Check logs for `metadata_validation` stage
2. Look for warnings if validation fails
3. Check if repair loop is triggered
4. Verify LLM fixes the metadata on retry

### Log Queries
```python
# In your logging system, search for:
logger.warning("QueryMetadata validation failed", ...)
logger.info("Added validation errors to repair loop", ...)
logger.info("QueryMetadata validation passed", ...)
```

## Monitoring

Track these metrics:
- **Validation failure rate**: How often does LLM generate invalid metadata?
- **Repair success rate**: How often does LLM fix it on retry?
- **Common errors**: Which errors are most frequent?
- **Improvement over time**: Is prompt update helping?

## Files Modified

```
✓ packages/resources/fm_app/system-pack/v1.0.0/slots/interactive_query/prompt.md
✓ apps/fm-app/fm_app/workers/interactive_flow.py (integrated validator)
✓ apps/fm-app/fm_app/validators/metadata_validator.py (new)
✓ apps/fm-app/fm_app/validators/__init__.py (new)
✓ apps/fm-app/examples/validate_metadata_example.py (new)
✓ apps/fm-app/METADATA_VALIDATION.md (new)
```

## Next Steps

1. **Deploy and Monitor**: Watch validation logs in production
2. **Track Metrics**: Measure validation failure/success rates
3. **Tune Prompts**: If specific errors recur, enhance prompt further
4. **Consider Auto-fix**: For simple cases, auto-correct instead of retrying
5. **Extend Coverage**: Add validation for other metadata fields if needed

## Rollback Plan

If needed, the integration can be disabled by commenting out the validation calls in `interactive_flow.py` (lines ~217 and ~730). The validator is passive - it only logs and adds to repair loop, doesn't block execution.

---

**Status**: ✅ Complete and Ready for Production
**Impact**: Medium - Improves data quality, fully backward compatible
**Risk**: Low - Only adds logging and repair loop messages
