# Implementation Plan: Data Fetch Tracking

## Overview

Add a `data_fetch` table to track metadata for each data fetch operation, providing observability into fetch patterns, performance, and errors.

## Schema

### Table: `data_fetch`

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | uuid | PK | Primary key |
| query_id | uuid | FK to query(query_id), NOT NULL | Required link to query |
| request_id | uuid | FK to request(request_id), NULL | Optional link to request |
| task_id | varchar | NULL | Celery task ID |
| requestor | varchar | NOT NULL | 'user' or 'system' |
| status | data_fetch_status_type | NOT NULL | enum: pending, running, success, error, cancelled, timed_out |
| created_at | timestamp with time zone | NOT NULL, DEFAULT now() | When fetch was requested |
| started_at | timestamp with time zone | NULL | When execution began |
| completed_at | timestamp with time zone | NULL | When finished |
| duration_ms | int | NULL | Execution time in ms |
| query_params | jsonb | NULL | {limit, offset, sort_by, sort_order, force} |
| row_count | int | NULL | Rows returned |
| error | text | NULL | Error message if failed |
| cache_hit | boolean | DEFAULT false | Served from cache? |

### Indexes

- `idx_data_fetch_query_id` on `query_id`
- `idx_data_fetch_request_id` on `request_id`
- `idx_data_fetch_created_at` on `created_at`
- `idx_data_fetch_status` on `status`

## Files to Modify

### 1. Migration: `apps/fm-app/alembic/versions/xxx_add_data_fetch_table.py`

Create new migration with:
- `data_fetch_status_type` enum
- `data_fetch` table with all fields
- Foreign key constraints
- Indexes

### 2. Models: `apps/fm-app/fm_app/api/model.py`

Add:
- `DataFetchStatus` enum (pending, running, success, error, cancelled, timed_out)
- `DataFetchRequestor` enum (user, system)
- `CreateDataFetchModel` - for inserting new records
- `UpdateDataFetchModel` - for updating status/completion
- `GetDataFetchModel` - for reading records

### 3. DB Functions: `apps/fm-app/fm_app/db/data_fetch_db.py` (new file)

Implement:
- `create_data_fetch()` - Insert new record with pending status
- `update_data_fetch_started()` - Set started_at, status=running
- `update_data_fetch_completed()` - Set completed_at, duration_ms, row_count, status=success
- `update_data_fetch_error()` - Set error, status=error/timed_out/cancelled
- `get_data_fetches_by_query()` - List fetches for a query
- `get_data_fetches_for_admin()` - Paginated list with filters for admin

### 4. SSE Endpoint: `apps/fm-app/fm_app/api/routes.py`

In `stream_data_fetch()`:
- **Before task launch**: Create data_fetch record with status=pending
- Pass `data_fetch_id` to Celery task args

### 5. Worker Task: `apps/fm-app/fm_app/workers/worker.py`

In `wrk_fetch_data()`:
- **At task start**: Update status=running, started_at
- **On cache hit**: Update status=success, cache_hit=True, completed_at, duration_ms
- **On success**: Update status=success, completed_at, duration_ms, row_count
- **On error**: Update status=error, error message
- **On timeout**: Update status=timed_out, error message
- **On cancel**: (handled in SSE endpoint when client disconnects)

### 6. Admin API: `apps/fm-app/fm_app/api/routes.py`

Add new endpoints:
- `GET /admin/data-fetches` - List all data fetches with pagination/filtering
- `GET /admin/data-fetches/{query_id}` - List fetches for specific query

### 7. Admin DB: `apps/fm-app/fm_app/db/admin_db.py`

Add:
- `get_all_data_fetches_admin()` - Paginated query with filters (status, date range, etc.)

## Implementation Order

1. **Migration** - Create table and enum
2. **Models** - Define Pydantic models
3. **DB Functions** - CRUD operations
4. **Worker Task** - Add tracking calls (core functionality)
5. **SSE Endpoint** - Create record before task launch
6. **Admin API** - Expose for monitoring
7. **Testing** - Verify end-to-end flow

## Data Flow

```
User Request → SSE Endpoint
                    │
                    ├─► CREATE data_fetch (status=pending)
                    │
                    └─► Launch Celery Task (with data_fetch_id)
                              │
                              ├─► UPDATE status=running, started_at
                              │
                              ├─► Check cache
                              │     ├─► HIT: UPDATE status=success, cache_hit=true
                              │     └─► MISS: Execute query
                              │               │
                              │               ├─► SUCCESS: UPDATE status=success, row_count
                              │               ├─► ERROR: UPDATE status=error
                              │               └─► TIMEOUT: UPDATE status=timed_out
                              │
                              └─► [If client disconnects: UPDATE status=cancelled]
```

## Admin Query Examples

```sql
-- Recent fetches with errors
SELECT * FROM data_fetch 
WHERE status IN ('error', 'timed_out') 
ORDER BY created_at DESC LIMIT 100;

-- Average execution time by query
SELECT query_id, 
       COUNT(*) as fetch_count,
       AVG(duration_ms) as avg_duration,
       SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits
FROM data_fetch 
WHERE status = 'success'
GROUP BY query_id;

-- Fetches per hour
SELECT date_trunc('hour', created_at) as hour,
       COUNT(*) as total,
       SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cached
FROM data_fetch
GROUP BY 1
ORDER BY 1 DESC;
```

## Notes

- The `request_id` field allows tracing back to session when fetch originated from a chat request
- `requestor` distinguishes user-initiated fetches from system operations (future: scheduled refreshes, etc.)
- `cache_hit` helps understand cache effectiveness
- `duration_ms` is computed as `completed_at - started_at` for consistency
