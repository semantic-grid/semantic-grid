# Critical Fix: Add Column Validation to Data Handler

## The Problem

**Current code** allows ANY valid identifier as `sort_by`:

```python
# User requests: GET /data/{query_id}?sort_by=nonexistent_column

col = _sanitize_sort_by(sort_by)  # Only checks if valid identifier
if col:
    base += f"\nORDER BY t.{col} {direction}"  # Adds to SQL blindly

# Result: Database error "Unknown column 'nonexistent_column'"
```

**We just validated QueryMetadata.column_name but we're not using it!**

---

## The Fix

### Step 1: Add Validation Function

```python
# Add to routes.py

def validate_sort_column(
    sort_by: str,
    query_metadata: Optional[QueryMetadata],
) -> tuple[bool, Optional[str]]:
    """
    Validate sort_by against QueryMetadata columns.

    Returns:
        (is_valid, error_message)
    """
    if not query_metadata or not query_metadata.columns:
        return False, "Query metadata not available - cannot validate sort column"

    # Get valid column names from metadata
    valid_columns = {
        col.column_name.lower(): col.column_name
        for col in query_metadata.columns
        if col.column_name
    }

    if not valid_columns:
        return False, "No columns found in query metadata"

    # Check if sort_by matches (case-insensitive)
    sort_by_lower = sort_by.lower()
    if sort_by_lower not in valid_columns:
        available = ", ".join(sorted(valid_columns.values()))
        return False, f"Invalid sort column '{sort_by}'. Available: {available}"

    # Return the canonical column name (from metadata)
    return True, valid_columns[sort_by_lower]
```

### Step 2: Use in get_query_data()

```python
@api_router.get("/data/{query_id}")
async def get_query_data(
    query_id: UUID,
    limit: int = 100,
    offset: int = 0,
    sort_by: Optional[str] = None,
    sort_order: str = Query("asc", regex="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # ... existing code to fetch SQL ...

    # NEW: Fetch query metadata for validation
    query_response = await get_query_by_id(query_id=query_id, db=db)

    if query_response:
        sql = query_response.sql if query_response.sql else ""
        sql = sql.strip().rstrip(";")

        # NEW: Validate sort_by against metadata
        if sort_by:
            query_metadata = QueryMetadata(
                id=query_response.query_id,
                columns=query_response.columns,
                sql=query_response.sql,
            )

            is_valid, result = validate_sort_column(sort_by, query_metadata)
            if not is_valid:
                raise HTTPException(status_code=400, detail=result)

            # Use canonical column name from metadata
            sort_by = result

    else:
        # Try request, then session (existing logic)
        request_response = await get_request_by_id(...)
        if request_response and request_response.query:
            # ... same validation here ...

    # ... rest of existing code ...
```

---

## Alternative: Simpler Version

If you don't want to fetch metadata again:

```python
@api_router.get("/data/{query_id}")
async def get_query_data(
    query_id: UUID,
    limit: int = 100,
    offset: int = 0,
    sort_by: Optional[str] = None,
    sort_order: str = Query("asc", regex="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # ... fetch SQL as before ...

    # NEW: If sort_by is provided, validate it's a simple identifier
    if sort_by:
        col = _sanitize_sort_by(sort_by)
        if not col:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid sort column '{sort_by}'. Must be a simple column name."
            )

        # Try to execute with better error handling
        try:
            combined_sql = build_sorted_paginated_sql(
                sql,
                sort_by=col,
                sort_order=sort_order,
                include_total_count=True,
            )

            with wh_session() as session:
                result = session.execute(
                    text(combined_sql),
                    {"limit": limit, "offset": offset},
                )
                # ...

        except Exception as e:
            error_msg = str(e).lower()

            # Check if it's a column error
            if "unknown column" in error_msg or "column" in error_msg and "not found" in error_msg:
                raise HTTPException(
                    status_code=400,
                    detail=f"Column '{sort_by}' not found in query results. Please check the column name.",
                )

            # Generic error
            raise HTTPException(
                status_code=500,
                detail=f"Error executing query: {str(e)}"
            )
```

---

## Recommendation

**Use the full validation approach (Step 1 + 2)** because:

1. ✅ Validates BEFORE database query (faster)
2. ✅ Uses QueryMetadata we just validated
3. ✅ Clear error messages with available columns
4. ✅ Case-insensitive matching
5. ✅ Returns canonical column name

**Cost**: One extra database query to fetch metadata
**Benefit**: Prevents 100% of invalid sort column errors

---

## Test Cases

```python
# Test 1: Valid column
GET /data/{query_id}?sort_by=wallet&sort_order=asc
→ ✓ Works

# Test 2: Invalid column
GET /data/{query_id}?sort_by=nonexistent&sort_order=asc
→ 400 "Invalid sort column 'nonexistent'. Available: wallet, amount, date"

# Test 3: Case insensitive
GET /data/{query_id}?sort_by=WALLET&sort_order=desc
→ ✓ Works (uses lowercase 'wallet')

# Test 4: No metadata
GET /data/{legacy_query_id}?sort_by=wallet
→ 400 "Query metadata not available - cannot validate sort column"
   OR: Falls back to database validation (if using alternative approach)

# Test 5: No sort_by
GET /data/{query_id}?limit=100
→ ✓ Works (no sorting, just pagination)
```

---

## Impact

**Before**:
```
User sorts by invalid column
  ↓
Database query executes
  ↓
Database error: "Unknown column"
  ↓
Generic 500 error to user
```

**After**:
```
User sorts by invalid column
  ↓
Validate against QueryMetadata
  ↓
400 error with available columns
  ↓
No database query wasted
  ↓
Clear error message to user
```

**Benefits**:
- ✅ Faster (no wasted DB query)
- ✅ Better UX (clear error message)
- ✅ Uses validated QueryMetadata
- ✅ Prevents database errors

---

## Should You Implement This?

**YES - if**:
- You want to use the QueryMetadata we just validated
- You want better error messages
- You want to prevent invalid database queries

**MAYBE - if**:
- Extra metadata fetch is a performance concern
- You're okay with database validation

**NO - if**:
- You rarely get invalid sort columns
- Current error handling is good enough
- You want minimum code changes

---

## My Recommendation

**Implement the full validation** (Step 1 + 2) because:

1. You already validated QueryMetadata.column_name - use it!
2. Small code change, big UX improvement
3. Prevents wasted database queries
4. Aligns with the metadata validation work we just did

The metadata fetch is fast (from your operational DB) and you can cache it if needed.
