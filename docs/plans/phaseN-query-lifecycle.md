# Phase 3: Query Lifecycle - Register, Execute, Store

## Overview

This phase implements the query lifecycle separation in db-meta, enabling:
1. Query registration with cost estimation (before execution)
2. Deferred/approved execution
3. Query record persistence
4. Data artifact caching for LLM analysis

This is a critical step toward making FM-APP replaceable by any MCP client.

## Goals

1. **Move query execution from FM-APP to DB-META** - Currently FM-APP connects directly to warehouse
2. **Separate registration from execution** - Allow review before expensive queries
3. **Store query records** - Enable cross-harness query history
4. **Cache data artifacts** - Enable LLM analysis without re-execution

## Current State

### Where Queries Execute Today

```
FM-APP (current):
┌─────────────────────────────────────────────────────────────────┐
│  fm_app/api/db_session.py                                       │
│  ├── wh_engine = create_engine(WH_URL)  ← Direct DB connection  │
│  ├── wh_session = sessionmaker(bind=wh_engine)                  │
│  └── get_wh_db() → Session                                      │
│                                                                 │
│  fm_app/api/routes.py                                           │
│  ├── Uses wh_session to execute queries                         │
│  └── Returns results directly to frontend                       │
└─────────────────────────────────────────────────────────────────┘

DB-META (current):
┌─────────────────────────────────────────────────────────────────┐
│  Only validates SQL (EXPLAIN)                                   │
│  Does NOT execute queries                                       │
│  Does NOT store query records                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Target State

```
FM-APP (target):
┌─────────────────────────────────────────────────────────────────┐
│  No direct warehouse connection                                 │
│  Calls db-meta MCP tools for all query operations               │
│  Stores references to query_ids, not query results              │
└─────────────────────────────────────────────────────────────────┘

DB-META (target):
┌─────────────────────────────────────────────────────────────────┐
│  register_query(sql) → query_id, estimates                      │
│  execute_query(query_id) → results + data artifact              │
│  query://{id} resources → SQL, metadata, results                │
│  Stores query records in PostgreSQL                             │
│  Caches data artifacts in S3/Redis                              │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Plan

### Step 1: Add Query Registry to DB-META

**New database table in db-meta:**

```sql
-- apps/db-meta/alembic/versions/xxx_add_query_registry.py
CREATE TABLE query_registry (
    query_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sql             TEXT NOT NULL,
    db              VARCHAR(50) NOT NULL,
    name            VARCHAR(255),
    
    -- Validation results (from EXPLAIN)
    columns         JSONB,
    estimated_rows  BIGINT,
    estimated_cost  FLOAT,
    
    -- Execution state
    status          VARCHAR(20) DEFAULT 'registered',
    executed_at     TIMESTAMP,
    execution_ms    INT,
    actual_rows     BIGINT,
    
    -- Metadata
    created_by      VARCHAR(255),
    created_at      TIMESTAMP DEFAULT NOW(),
    
    -- Soft delete
    deleted_at      TIMESTAMP
);

CREATE INDEX idx_query_registry_status ON query_registry(status);
CREATE INDEX idx_query_registry_created_by ON query_registry(created_by);
CREATE INDEX idx_query_registry_created_at ON query_registry(created_at);
```

**Files to create/modify:**
- `apps/db-meta/dbmeta_app/db/models.py` - SQLAlchemy model
- `apps/db-meta/dbmeta_app/db/query_registry.py` - CRUD operations
- `apps/db-meta/alembic/versions/xxx_add_query_registry.py` - Migration

### Step 2: Add MCP Tools for Query Lifecycle

**New tools in db-meta:**

```python
# apps/db-meta/dbmeta_app/api/routes.py

@mcp.tool()
async def register_query(req: RegisterQueryRequest) -> RegisterQueryResponse:
    """
    Register a query WITHOUT executing it.
    
    - Validates SQL syntax (EXPLAIN)
    - Estimates cost/rows
    - Stores query record with status='registered'
    - Returns query_id for later execution
    """
    pass

@mcp.tool()
async def execute_query(req: ExecuteQueryRequest) -> ExecuteQueryResponse:
    """
    Execute a previously registered query.
    
    - Runs query against warehouse
    - Updates query record with execution stats
    - Optionally caches results as data artifact
    - Returns results
    """
    pass

@mcp.tool()
async def execute_sql(req: ExecuteSqlRequest) -> ExecuteSqlResponse:
    """
    Register and execute SQL in one step.
    
    Convenience wrapper for simple cases.
    Equivalent to register_query + execute_query.
    """
    pass

@mcp.tool()
async def get_query_history(req: QueryHistoryRequest) -> QueryHistoryResponse:
    """
    Get query history for a user.
    
    Returns list of query records with metadata.
    """
    pass
```

**New models:**

```python
# apps/db-meta/dbmeta_app/api/model.py

class QueryStatus(str, Enum):
    registered = "registered"
    executing = "executing"
    executed = "executed"
    failed = "failed"
    expired = "expired"

class RegisterQueryRequest(BaseModel):
    sql: str
    db: Optional[str] = None
    name: Optional[str] = None
    created_by: Optional[str] = None

class RegisterQueryResponse(BaseModel):
    query_id: str
    sql: str
    columns: Optional[list[dict]] = None
    estimated_rows: Optional[int] = None
    estimated_cost: Optional[float] = None
    warning: Optional[str] = None  # e.g., "Large query, ~10 min runtime"

class ExecuteQueryRequest(BaseModel):
    query_id: str
    limit: int = 1000
    cache_results: bool = True

class ExecuteQueryResponse(BaseModel):
    query_id: str
    columns: list[dict]
    rows: list[dict]
    execution_time_ms: int
    actual_rows: int
    truncated: bool
    cached: bool

class ExecuteSqlRequest(BaseModel):
    sql: str
    db: Optional[str] = None
    limit: int = 1000
    name: Optional[str] = None
    created_by: Optional[str] = None

class ExecuteSqlResponse(BaseModel):
    query_id: str
    columns: list[dict]
    rows: list[dict]
    execution_time_ms: int
    actual_rows: int
```

### Step 3: Add Warehouse Connection to DB-META

**Move warehouse connection from fm-app to db-meta:**

```python
# apps/db-meta/dbmeta_app/wh_db/executor.py

class QueryExecutor:
    """Execute queries against warehouse databases."""
    
    def __init__(self, settings: Settings):
        self.engines = self._create_engines(settings)
    
    def _create_engines(self, settings: Settings) -> dict:
        """Create SQLAlchemy engines for each warehouse profile."""
        return {
            "wh": self._create_engine(settings, "wh"),
            "wh_new": self._create_engine(settings, "wh_new"),
            "wh_v2": self._create_engine(settings, "wh_v2"),
        }
    
    async def execute(
        self, 
        sql: str, 
        db: str, 
        limit: int,
        timeout: int = 300
    ) -> ExecutionResult:
        """Execute SQL and return results."""
        engine = self.engines.get(db, self.engines["wh_v2"])
        
        with engine.connect() as conn:
            # Add LIMIT if not present
            limited_sql = self._add_limit(sql, limit)
            
            start = time.time()
            result = conn.execute(text(limited_sql))
            execution_ms = int((time.time() - start) * 1000)
            
            columns = [{"name": c, "type": str(result.cursor.description[i][1])} 
                      for i, c in enumerate(result.keys())]
            rows = [dict(row) for row in result.mappings().fetchall()]
            
            return ExecutionResult(
                columns=columns,
                rows=rows,
                execution_ms=execution_ms,
                actual_rows=len(rows),
                truncated=len(rows) >= limit,
            )
```

### Step 4: Add Data Artifact Storage

**Store query results for LLM analysis:**

```python
# apps/db-meta/dbmeta_app/cache/data_artifacts.py

class DataArtifactStore:
    """Store and retrieve query result artifacts."""
    
    def __init__(self, redis_client, s3_client=None, max_rows=10000, ttl=86400):
        self.redis = redis_client
        self.s3 = s3_client
        self.max_rows = max_rows
        self.ttl = ttl
    
    async def store(self, query_id: str, data: list[dict]) -> bool:
        """Store data artifact, use S3 for large datasets."""
        if len(data) > self.max_rows:
            return False  # Too large to cache
        
        serialized = json.dumps(data, default=str)
        
        if len(serialized) > 1_000_000:  # >1MB, use S3
            if self.s3:
                await self._store_s3(query_id, serialized)
                await self.redis.setex(
                    f"artifact:{query_id}:location", 
                    self.ttl, 
                    "s3"
                )
            else:
                return False
        else:
            await self.redis.setex(
                f"artifact:{query_id}:data", 
                self.ttl, 
                serialized
            )
        
        return True
    
    async def get(self, query_id: str) -> Optional[list[dict]]:
        """Retrieve data artifact."""
        location = await self.redis.get(f"artifact:{query_id}:location")
        
        if location == "s3":
            return await self._get_s3(query_id)
        
        data = await self.redis.get(f"artifact:{query_id}:data")
        if data:
            return json.loads(data)
        
        return None
```

### Step 5: Add MCP Resources for Query Access

**Read-only resources for query data:**

```python
# apps/db-meta/dbmeta_app/api/routes.py

@mcp.resource("query://{query_id}/sql")
async def get_query_sql(query_id: str) -> Resource:
    """Get SQL for a registered query."""
    query = await query_registry.get(query_id)
    if not query:
        raise ResourceNotFound(f"Query {query_id} not found")
    
    return Resource(
        uri=f"query://{query_id}/sql",
        name=query.name or f"Query {query_id[:8]}",
        mimeType="text/plain",
        text=query.sql,
    )

@mcp.resource("query://{query_id}/metadata")
async def get_query_metadata(query_id: str) -> Resource:
    """Get metadata for a query (columns, stats, status)."""
    query = await query_registry.get(query_id)
    if not query:
        raise ResourceNotFound(f"Query {query_id} not found")
    
    return Resource(
        uri=f"query://{query_id}/metadata",
        mimeType="application/json",
        text=json.dumps({
            "query_id": query.query_id,
            "status": query.status,
            "columns": query.columns,
            "estimated_rows": query.estimated_rows,
            "actual_rows": query.actual_rows,
            "execution_ms": query.execution_ms,
            "created_at": query.created_at.isoformat(),
        }),
    )

@mcp.resource("data://{query_id}")
async def get_data_artifact(query_id: str) -> Resource:
    """Get cached result data for a query."""
    data = await artifact_store.get(query_id)
    if not data:
        raise ResourceNotFound(f"No cached data for query {query_id}")
    
    return Resource(
        uri=f"data://{query_id}",
        mimeType="application/json",
        text=json.dumps(data, default=str),
    )

@mcp.resource("query://user/{user_id}/history")
async def get_user_query_history(user_id: str) -> Resource:
    """Get query history for a user."""
    queries = await query_registry.get_by_user(user_id, limit=50)
    
    return Resource(
        uri=f"query://user/{user_id}/history",
        mimeType="application/json",
        text=json.dumps([
            {
                "query_id": q.query_id,
                "name": q.name,
                "status": q.status,
                "created_at": q.created_at.isoformat(),
            }
            for q in queries
        ]),
    )
```

### Step 6: Update FM-APP to Use DB-META

**Add new MCP client functions:**

```python
# apps/fm-app/fm_app/mcp_servers/db_meta.py

async def register_query_mcp(
    req: McpServerRequest,
    sql: str,
    flow_step_num: int,
    settings,
    logger,
    name: Optional[str] = None,
) -> RegisterQueryResult:
    """Register a query in db-meta without executing."""
    pass

async def execute_query_mcp(
    req: McpServerRequest,
    query_id: str,
    flow_step_num: int,
    settings,
    logger,
    limit: int = 1000,
) -> ExecuteQueryResult:
    """Execute a registered query via db-meta."""
    pass

async def execute_sql_mcp(
    req: McpServerRequest,
    sql: str,
    flow_step_num: int,
    settings,
    logger,
    limit: int = 1000,
) -> ExecuteQueryResult:
    """Register and execute SQL in one call."""
    pass
```

**Migrate routes.py to use MCP:**

```python
# apps/fm-app/fm_app/api/routes.py

# Before:
# result = wh_session.execute(text(sql))
# rows = result.mappings().fetchall()

# After:
# result = await execute_sql_mcp(mcp_req, sql, step, settings, logger)
# rows = result.rows
```

## Migration Strategy

### Phase 3a: Add DB-META Capabilities (Non-Breaking)

1. Add query registry table to db-meta
2. Add `register_query`, `execute_query`, `execute_sql` tools
3. Add `query://` and `data://` resources
4. Add data artifact storage

**FM-APP unchanged - still uses direct connection**

### Phase 3b: Add FM-APP Client Functions

1. Add MCP client functions in `fm_app/mcp_servers/db_meta.py`
2. Add feature flag for new execution path
3. Test with flag enabled in staging

### Phase 3c: Migrate FM-APP Execution

1. Replace direct warehouse calls with MCP calls
2. Remove `wh_engine`, `wh_session` from db_session.py
3. Update routes to use new flow

### Phase 3d: Remove Old Code

1. Remove warehouse connection from fm-app
2. Remove direct query execution code
3. Full verification

## Files to Create/Modify

### DB-META (New)

| File | Description |
|------|-------------|
| `dbmeta_app/db/models.py` | SQLAlchemy model for query_registry |
| `dbmeta_app/db/query_registry.py` | CRUD operations for queries |
| `dbmeta_app/wh_db/executor.py` | Query execution against warehouse |
| `dbmeta_app/cache/data_artifacts.py` | Data artifact storage |
| `alembic/versions/xxx_add_query_registry.py` | Database migration |

### DB-META (Modify)

| File | Changes |
|------|---------|
| `dbmeta_app/api/model.py` | Add query lifecycle models |
| `dbmeta_app/api/routes.py` | Add tools and resources |
| `dbmeta_app/config.py` | Add S3/artifact config |

### FM-APP (Modify)

| File | Changes |
|------|---------|
| `fm_app/mcp_servers/db_meta.py` | Add query lifecycle functions |
| `fm_app/api/routes.py` | Replace direct execution with MCP |
| `fm_app/api/db_session.py` | Eventually remove wh_engine |

## Infrastructure Requirements

| Component | Purpose | Required for Phase 3? |
|-----------|---------|----------------------|
| PostgreSQL (db-meta) | Query registry | Yes |
| Redis | Data artifact cache | Yes |
| S3/MinIO | Large artifact storage | Optional (Phase 3+) |

## Testing Strategy

1. **Unit tests** for query registry CRUD
2. **Unit tests** for query executor
3. **Integration tests** for full MCP flow
4. **A/B tests** with feature flag in staging
5. **Performance comparison** vs direct execution

## Rollback Plan

Feature flag allows instant rollback:
- `QUERY_EXECUTION_VIA_MCP=false` → Use direct connection
- `QUERY_EXECUTION_VIA_MCP=true` → Use db-meta MCP

## Success Criteria

1. All queries execute via db-meta MCP
2. Query history visible across harnesses
3. Data artifacts cached and retrievable
4. No regression in query performance (< 100ms overhead)
5. FM-APP has no direct warehouse connection

## Timeline Estimate

| Step | Scope | Complexity |
|------|-------|------------|
| Step 1: Query registry | DB model + migration | Low |
| Step 2: MCP tools | 4 new tools | Medium |
| Step 3: Warehouse connection | Move from fm-app | Low |
| Step 4: Data artifacts | Cache layer | Medium |
| Step 5: MCP resources | 4 new resources | Low |
| Step 6: FM-APP migration | Replace calls | Medium |

## Related Documents

- `docs/plans/phase2-granular-schema-exploration.md` - Previous phase (completed)
- `docs/future/db-meta-v2-architecture.md` - Overall architecture vision
- `docs/future/autonomous-agentic-flow.md` - FM-APP agent loop
