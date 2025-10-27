# QueryMetadata Validation Guide

## Problem

When LLMs generate QueryMetadata, the `column_name` field sometimes contains:
- Raw column names instead of aliases (e.g., `"wallet_address"` instead of `"wallet"`)
- SQL expressions instead of aliases (e.g., `"DATE(block_time)"` instead of `"trade_date"`)
- Table prefixes (e.g., `"t.wallet"` instead of `"wallet"`)

This breaks pagination/sorting because the backend constructs:
```sql
ORDER BY t.{column_name}
```

If `column_name = "DATE(block_time)"`, this becomes:
```sql
ORDER BY t.DATE(block_time)  -- FAILS! Invalid syntax
```

## Solution

### 1. Updated Prompt (Already Done ✓)

The `interactive_query/prompt.md` now has explicit instructions:
- Always use the alias if `AS` is present
- Never use expressions or table prefixes
- Includes examples of correct vs incorrect values

### 2. Validation Library

Use `MetadataValidator` to check QueryMetadata consistency:

```python
from fm_app.validators import MetadataValidator, MetadataValidationError

# Option 1: Get detailed validation results
result = MetadataValidator.validate_metadata(metadata, dialect="clickhouse")
if not result["valid"]:
    print("Errors:", result["errors"])
    print("Warnings:", result["warnings"])

# Option 2: Raise exception if invalid
try:
    MetadataValidator.validate_and_raise(metadata, dialect="clickhouse")
except MetadataValidationError as e:
    # Handle validation failure
    pass
```

### 3. Integration Points

#### A. Post-LLM Generation (Recommended)

After the LLM generates QueryMetadata in the interactive flow:

```python
# In fm_app/workers/interactive_flow.py or similar

# After LLM generates metadata
metadata = response.metadata  # QueryMetadata from LLM

# Validate
validation_result = MetadataValidator.validate_metadata(metadata)

if not validation_result["valid"]:
    # Log the error
    logger.warning(
        f"QueryMetadata validation failed: {validation_result['errors']}"
    )

    # Option 1: Add to repair loop (let critic fix it)
    # Add validation errors to the critic prompt

    # Option 2: Auto-fix simple cases
    # If SQL columns are known, automatically correct column_name values

    # Option 3: Return error to user
    # Ask user to rephrase or report the issue
```

#### B. Pre-Execution Check

Before executing sort/filter operations:

```python
# In fm_app/api/routes.py - get_query_data endpoint

@api_router.get("/data/{query_id}")
async def get_query_data(
    query_id: UUID,
    sort_by: Optional[str] = None,
    # ... other params
):
    # Fetch metadata
    metadata = # ... get from DB

    # Validate before using sort_by
    if sort_by and metadata.columns:
        validation = MetadataValidator.validate_metadata(metadata)
        if not validation["valid"]:
            raise HTTPException(
                status_code=500,
                detail=f"Invalid metadata: {validation['errors']}"
            )

        # Check if sort_by column exists
        if sort_by not in validation["sql_columns"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort column: {sort_by}"
            )
```

#### C. Debug/Admin Endpoint

Create an endpoint to check existing queries:

```python
@api_router.post("/admin/validate-metadata/{query_id}")
async def validate_query_metadata(query_id: UUID, db: AsyncSession = Depends(get_db)):
    """Debug endpoint to validate QueryMetadata."""
    query = await get_query_by_id(query_id, db)

    if not query or not query.metadata:
        raise HTTPException(404, "Query or metadata not found")

    result = MetadataValidator.validate_metadata(query.metadata)
    return result
```

#### D. Repair Loop Integration

In the SQL repair/validation flow:

```python
# In the critic/repair loop
def validate_and_repair_metadata(metadata: QueryMetadata, max_attempts: int = 3):
    """Validate metadata and attempt repairs."""

    for attempt in range(max_attempts):
        result = MetadataValidator.validate_metadata(metadata)

        if result["valid"]:
            return metadata

        # Add validation errors to critic prompt
        critic_prompt = f"""
        The QueryMetadata has validation errors:
        {chr(10).join(result['errors'])}

        SQL columns in result: {result['sql_columns']}
        Metadata columns: {result['metadata_columns']}

        Please fix the column_name values to match the SQL result columns.
        Remember: Use aliases when AS is present, not expressions.
        """

        # Call LLM to fix
        metadata = call_llm_to_fix(metadata, critic_prompt)

    raise MetadataValidationError("Failed to repair metadata after retries")
```

## Testing

Run the example to see validation in action:

```bash
cd apps/fm-app
uv run python examples/validate_metadata_example.py
```

## Common Validation Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `contains function/expression` | `column_name = "DATE(block_time)"` | Use alias: `"trade_date"` |
| `contains table prefix` | `column_name = "t.wallet"` | Remove prefix: `"wallet"` |
| `not a valid SQL identifier` | Special characters in name | Use simple identifier or alias |
| `missing from metadata` | Column in SQL not in metadata | Add missing Column objects |
| `not in SQL results` | Column in metadata not in SQL | Remove or fix column_name |

## Benefits

1. **Deterministic validation** - No guessing if metadata is correct
2. **Early error detection** - Catch issues before they cause runtime errors
3. **Better debugging** - Clear error messages about what's wrong
4. **Automated repair** - Can be integrated into critic loop
5. **Data quality** - Ensures metadata consistency across the system

## Next Steps

1. Add validation to interactive query flow (post-LLM generation)
2. Add pre-check before sort/filter operations
3. Create admin endpoint for debugging existing queries
4. Add validation metrics/logging to track LLM accuracy
5. Consider auto-fixing simple cases (exact match between SQL and metadata)
