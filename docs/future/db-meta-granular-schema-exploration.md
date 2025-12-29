# DB-Meta Granular Schema Exploration - Implementation Plan

## Overview

Enhance db-meta MCP server to support granular, on-demand database exploration where:
1. Agent planning phase selects table candidates (lightweight)
2. Agent requests detailed metadata for specific tables (rich, on-demand)

**Key Principle**: Backward compatible - existing tools continue to work unchanged.

---

## Current State

### Existing MCP Tools (must remain unchanged):
- `prompt_items_v2` - Returns schema + examples + instructions
- `preflight_query` - Validates SQL syntax
- `validate_plan` - Checks tables/columns exist
- `get_database_overview` - Discovery/help

### Current Schema Depth:
- Table names + descriptions
- Column names, types, nullable, defaults
- Human descriptions from YAML
- Sample values from YAML

### Missing (to be added):
- PK-FK relationships
- Column cardinality + distinct values
- Min/max ranges for numeric/date columns
- Index information

---

## New MCP Prompts (Read-Only Resources)

Expose static/semi-static content as MCP prompts instead of tools:

### `domain_model`
- **Purpose**: Entity relationships, business concepts, vocabulary
- **Source**: `packages/resources/.../domain_model.md`
- **Usage**: Agent reads once at session start or when switching domains
- **Update frequency**: Rarely changes (documentation)

### `sql_dialect`
- **Purpose**: Database-specific SQL syntax rules and quirks
- **Source**: `packages/resources/.../sql_dialect.md`
- **Usage**: Agent reads when generating SQL for specific database
- **Update frequency**: Changes with database version upgrades

### `prompt_instructions` (Business Rules)
- **Purpose**: Query generation rules, constraints, best practices
- **Source**: `packages/resources/.../prompt_instructions.yaml`
- **Usage**: Agent reads to understand business-specific query constraints
- **Update frequency**: Changes as business rules evolve

### Benefits of MCP Prompts vs Tools:
- **Cacheable**: Client can cache and reuse without repeated calls
- **Declarative**: Agent knows these are static context, not actions
- **Discoverable**: Listed in MCP prompt registry for agent introspection

---

## Proposed Architecture

### Two-Phase Schema Exploration:

```
Phase 1: Lightweight Discovery (existing behavior)
┌─────────────────────────────────────────────────────────┐
│ prompt_items_v2(items=["DBStruct"], schema_top_k=10)    │
│ Returns: Table names, descriptions, column overview     │
│ Used by: Query Planner to select candidate tables       │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
Phase 2: Deep Table Details (NEW)
┌─────────────────────────────────────────────────────────┐
│ table_details(tables=["t1", "t2"], include=[...])   │
│ Returns: FK relationships, cardinality, value ranges    │
│ Used by: SQL Generator after plan is approved           │
└─────────────────────────────────────────────────────────┘
```

---

## New MCP Tool: `table_details`

### Request Model:
```python
class GetTableDetailsRequest(BaseModel):
    db: str  # "wh", "new_wh", "wh_v2"
    tables: list[str]  # Fully qualified table names
    include: list[str] = ["relationships", "cardinality", "ranges"]
    # Options:
    #   "relationships" - PK-FK constraints
    #   "cardinality" - Distinct value counts
    #   "low_cardinality_values" - Actual values for low-cardinality columns
    #   "ranges" - Min/max for numeric/date columns
    #   "indexes" - Index information
    cardinality_threshold: int = 100  # Max distinct values to fetch
    sample_size: int = 10000  # Rows to sample for stats
```

### Response Model:
```python
class TableDetails(BaseModel):
    table_name: str
    primary_key: list[str] | None
    foreign_keys: list[ForeignKeyInfo]
    columns: list[ColumnDetails]

class ForeignKeyInfo(BaseModel):
    columns: list[str]
    referred_table: str
    referred_columns: list[str]

class ColumnDetails(BaseModel):
    name: str
    type: str
    nullable: bool
    is_primary_key: bool
    is_foreign_key: bool
    # New fields:
    distinct_count: int | None  # Approximate cardinality
    is_low_cardinality: bool  # distinct_count < threshold
    distinct_values: list[str] | None  # If low cardinality
    min_value: str | None  # For numeric/date
    max_value: str | None

class GetTableDetailsResponse(BaseModel):
    tables: list[TableDetails]
    content_hash: str
    metadata: dict
```

---

## YAML Configuration Extensions

### Mark columns for special handling:
```yaml
profiles:
  wh_v2:
    tables:
      iceberg.radius.wifi_sessions:
        columns:
          status:
            low_cardinality: true  # Fetch distinct values
            cardinality_limit: 50  # Override default threshold
          event_timestamp:
            stats: true  # Fetch min/max
          nas_identifier:
            stats: false  # Skip stats (too many values)
```

### Default behavior (no YAML config):
- Auto-detect low cardinality: `COUNT(DISTINCT) < 100`
- Auto-fetch ranges for: `timestamp`, `date`, `int`, `float` types
- Skip stats for: `text`, `varchar(>256)`, `blob` types

---

## Implementation Steps

### Step 1: Database Introspection Enhancements (db-meta)

**File: `apps/db-meta/dbmeta_app/prompt_items/db_struct.py`**

Add functions:
```python
async def get_primary_keys(engine, table_name, schema) -> list[str]
async def get_foreign_keys(engine, table_name, schema) -> list[ForeignKeyInfo]
async def get_column_cardinality(engine, table_name, column, sample_size) -> int
async def get_column_distinct_values(engine, table_name, column, limit) -> list[str]
async def get_column_range(engine, table_name, column) -> tuple[Any, Any]
```

Database-specific implementations:
- **ClickHouse**: Use system.columns for stats, SAMPLE for cardinality
- **PostgreSQL**: Use pg_stats for pre-computed stats
- **Trino**: Use ANALYZE stats if available, else sample

### Step 2: New MCP Tool (db-meta)

**File: `apps/db-meta/dbmeta_app/api/routes.py`**

```python
@mcp.tool()
async def table_details(req: GetTableDetailsRequest) -> GetTableDetailsResponse:
    """Get detailed metadata for specific tables including relationships and stats."""
    ...
```

### Step 3: Caching Layer (db-meta)

**File: `apps/db-meta/dbmeta_app/cache/redis_cache.py`**

- Cache key: `table_details:{db}:{table_name}:{include_hash}`
- TTL: 1 hour for stats, 24 hours for relationships
- Invalidation: Manual refresh endpoint

### Step 4: fm-app Integration

**File: `apps/fm-app/fm_app/mcp_servers/db_meta.py`**

Add function:
```python
async def table_details_mcp(
    tables: list[str],
    db: str,
    include: list[str] = ["relationships", "cardinality", "ranges"]
) -> TableDetailsResult:
    ...
```

### Step 5: Query Planner Integration

**File: `apps/fm-app/fm_app/workers/interactive_flow/query_planner.py`**

After plan validation, before SQL generation:
```python
if query_plan.tables:
    table_details = await table_details_mcp(
        tables=query_plan.tables,
        db=db_name,
        include=["relationships", "low_cardinality_values", "ranges"]
    )
    # Store in query_plan.table_details for SQL generator
```

### Step 6: SQL Generator Integration

**File: `apps/fm-app/fm_app/workers/interactive_flow/interactive_query.py`**

Inject table details into prompt:
```python
if query_plan and query_plan.table_details:
    interactive_query_vars["table_details"] = format_table_details(query_plan.table_details)
```

### Step 7: Prompt Template Updates

**File: `packages/resources/fm_app/system-pack/v1.2.0/slots/interactive_query/prompt.md`**

Add section:
```markdown
{% if table_details %}
## Table Relationships & Statistics

{{ table_details }}
{% endif %}
```

---

## Backward Compatibility Guarantees

1. **Existing tools unchanged**: `prompt_items_v2`, `preflight_query`, `validate_plan` keep same signatures
2. **New tool is additive**: `table_details` is a new tool, not a replacement
3. **YAML config optional**: Existing YAML files work without changes
4. **Graceful degradation**: If stats unavailable, return `null` instead of error
5. **fm-app fallback**: If `table_details` fails, continue with existing flow

---

## Performance Considerations

1. **On-demand only**: Stats fetched only for selected tables, not all tables
2. **Sampling**: Use SAMPLE/TABLESAMPLE for large tables
3. **Caching**: Cache stats in Redis (1hr TTL for stats, 24hr for relationships)
4. **Parallel fetching**: Fetch stats for multiple tables concurrently
5. **Timeout**: 10s timeout per table, skip if exceeded

---

## MCP Response Caching Strategy

### Cacheability by Response Type

| Response Type | Cacheable | TTL | Cache Key | Invalidation |
|--------------|-----------|-----|-----------|--------------|
| **MCP Prompts** | ✅ Highly | 24h+ | `{db}:{prompt_name}` | Deploy/config change |
| **Relationships (FK/PK)** | ✅ Highly | 24h | `{db}:{table}:relationships` | Schema migration |
| **Low-cardinality values** | ✅ Medium | 1h | `{db}:{table}:{column}:values` | Data change |
| **Cardinality counts** | ✅ Medium | 1h | `{db}:{table}:{column}:cardinality` | Data change |
| **Min/Max ranges** | ⚠️ Low | 15m | `{db}:{table}:{column}:range` | Data ingestion |
| **DBStruct (schema)** | ✅ Medium | 1h | `{db}:schema:{top_k}:{query_hash}` | Schema migration |
| **Query examples** | ✅ Highly | 24h | `{db}:examples:{query_hash}` | Manual update |
| **preflight_query** | ❌ Never | - | - | Query-specific |
| **validate_plan** | ❌ Never | - | - | Plan-specific |

### Two-Layer Caching Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FM-APP (Client)                          │
├─────────────────────────────────────────────────────────────────┤
│  L1: In-Memory Session Cache                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • MCP Prompts (domain_model, sql_dialect, instructions) │   │
│  │ • Per-session, survives multiple requests               │   │
│  │ • Invalidated on session end or explicit refresh        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DB-META (Server)                           │
├─────────────────────────────────────────────────────────────────┤
│  L2: Redis Distributed Cache                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • table_details results (relationships, stats)          │   │
│  │ • Shared across all fm-app instances                    │   │
│  │ • TTL-based expiration with manual invalidation API     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  L3: Database Statistics (Pre-computed)                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • pg_stats (PostgreSQL) - maintained by ANALYZE         │   │
│  │ • system.columns (ClickHouse) - real-time stats         │   │
│  │ • No TTL needed - always fresh from DB engine           │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Cache Key Design

```python
# MCP Prompts (L1 - fm-app in-memory)
prompt_cache_key = f"mcp_prompt:{db}:{prompt_name}"
# Example: "mcp_prompt:wh_v2:domain_model"

# Table Details (L2 - Redis)
table_details_key = f"table_details:{db}:{table_name}:{include_hash}"
# Example: "table_details:wh_v2:iceberg.radius.wifi_sessions:abc123"

# Individual Column Stats (L2 - Redis, for granular invalidation)
column_stats_key = f"col_stats:{db}:{table}:{column}:{stat_type}"
# Example: "col_stats:wh_v2:iceberg.radius.wifi_sessions:status:values"
```

### FM-App Session Cache Implementation

```python
# In fm_app/mcp_servers/mcp_cache.py

from functools import lru_cache
from typing import Optional
import time

class MCPSessionCache:
    """In-memory cache for MCP prompts within a session."""
    
    def __init__(self, ttl_seconds: int = 3600):
        self._cache: dict[str, tuple[str, float]] = {}
        self._ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[str]:
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value
            del self._cache[key]
        return None
    
    def set(self, key: str, value: str) -> None:
        self._cache[key] = (value, time.time())
    
    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)
    
    def clear(self) -> None:
        self._cache.clear()


# Usage in flow context
class FlowContext:
    def __init__(self, ...):
        # ... existing fields ...
        self.mcp_cache = MCPSessionCache(ttl_seconds=3600)
    
    async def get_mcp_prompt(self, prompt_name: str, db: str) -> str:
        cache_key = f"mcp_prompt:{db}:{prompt_name}"
        
        # Check L1 cache first
        cached = self.mcp_cache.get(cache_key)
        if cached:
            return cached
        
        # Fetch from db-meta
        result = await fetch_mcp_prompt(prompt_name, db, self.settings)
        
        # Cache for session
        self.mcp_cache.set(cache_key, result)
        return result
```

### DB-Meta Redis Cache Implementation

```python
# In apps/db-meta/dbmeta_app/cache/redis_cache.py

import hashlib
import json
from typing import Optional
import redis.asyncio as redis

class TableDetailsCache:
    """Redis cache for table details with tiered TTLs."""
    
    # TTLs by data type
    TTL_RELATIONSHIPS = 86400  # 24 hours - schema rarely changes
    TTL_CARDINALITY = 3600     # 1 hour - data changes moderately
    TTL_RANGES = 900           # 15 minutes - ranges change with ingestion
    TTL_VALUES = 3600          # 1 hour - enum-like values stable
    
    def __init__(self, redis_url: str):
        self._redis = redis.from_url(redis_url)
    
    def _make_key(self, db: str, table: str, include: list[str]) -> str:
        include_hash = hashlib.md5(
            json.dumps(sorted(include)).encode()
        ).hexdigest()[:8]
        return f"table_details:{db}:{table}:{include_hash}"
    
    async def get(
        self, db: str, table: str, include: list[str]
    ) -> Optional[dict]:
        key = self._make_key(db, table, include)
        data = await self._redis.get(key)
        if data:
            return json.loads(data)
        return None
    
    async def set(
        self, db: str, table: str, include: list[str], data: dict
    ) -> None:
        key = self._make_key(db, table, include)
        
        # Use shortest TTL based on what's included
        ttl = self.TTL_RELATIONSHIPS  # Start with longest
        if "ranges" in include:
            ttl = min(ttl, self.TTL_RANGES)
        if "cardinality" in include or "low_cardinality_values" in include:
            ttl = min(ttl, self.TTL_CARDINALITY)
        
        await self._redis.setex(key, ttl, json.dumps(data))
    
    async def invalidate_table(self, db: str, table: str) -> None:
        """Invalidate all cached data for a table."""
        pattern = f"table_details:{db}:{table}:*"
        async for key in self._redis.scan_iter(pattern):
            await self._redis.delete(key)
    
    async def invalidate_db(self, db: str) -> None:
        """Invalidate all cached data for a database (after migration)."""
        pattern = f"table_details:{db}:*"
        async for key in self._redis.scan_iter(pattern):
            await self._redis.delete(key)
```

### Content Hash for Cache Validation

Every cached response includes a `content_hash` for lineage and validation:

```python
def compute_content_hash(data: dict) -> str:
    """Compute deterministic hash of response content."""
    # Sort keys for deterministic serialization
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]

# Response always includes hash
response = {
    "tables": [...],
    "content_hash": compute_content_hash(tables_data),
    "cached": True,  # Indicates this came from cache
    "cache_age_seconds": 1234,  # How old the cached data is
}
```

### Cache Invalidation Triggers

| Trigger | Action | Scope |
|---------|--------|-------|
| Schema migration (DDL) | Invalidate relationships + schema | Per-table or per-db |
| Data load (ETL complete) | Invalidate ranges + cardinality | Per-table |
| Config deploy | Clear MCP prompts | All sessions |
| Manual refresh API | Invalidate specific keys | Targeted |
| TTL expiration | Automatic removal | Per-key |

### Invalidation API (db-meta)

```python
@mcp.tool()
async def invalidate_cache(
    db: str,
    table: Optional[str] = None,
    cache_type: Optional[str] = None,  # "relationships", "stats", "all"
) -> dict:
    """
    Manually invalidate cached table details.
    
    Use after schema migrations or significant data changes.
    """
    cache = TableDetailsCache(settings.redis_url)
    
    if table:
        await cache.invalidate_table(db, table)
        return {"invalidated": f"{db}:{table}"}
    else:
        await cache.invalidate_db(db)
        return {"invalidated": f"{db}:*"}
```

---

## Files to Modify

### db-meta (apps/db-meta/):
- `dbmeta_app/api/model.py` - Add new Pydantic models
- `dbmeta_app/api/routes.py` - Add `table_details` MCP tool
- `dbmeta_app/prompt_items/db_struct.py` - Add introspection functions
- `dbmeta_app/cache/redis_cache.py` - Add caching for table details

### fm-app (apps/fm-app/):
- `fm_app/mcp_servers/db_meta.py` - Add `table_details_mcp()` function
- `fm_app/api/model.py` - Add TableDetails to QueryPlan model
- `fm_app/workers/interactive_flow/query_planner.py` - Fetch details after plan validation
- `fm_app/workers/interactive_flow/interactive_query.py` - Include details in SQL generation

### Resources (packages/resources/):
- `fm_app/system-pack/v1.2.0/slots/interactive_query/prompt.md` - Add table details section

---

## Testing Strategy

1. **Unit tests**: New introspection functions with mock databases
2. **Integration tests**: End-to-end flow with real db-meta
3. **Backward compat tests**: Existing flows still work without changes
4. **Performance tests**: Verify stats collection completes within timeout

---

## FM-App Integration Details

### 1. MCP Client Function (`fm_app/mcp_servers/db_meta.py`)

Add new client function following existing patterns:

```python
@dataclass
class TableDetailsResult:
    """Result from table_details MCP call."""
    tables: list[dict]  # TableDetails as dicts
    content_hash: str
    source: str


async def get_table_details_mcp(
    req: McpServerRequest,
    tables: list[str],
    flow_step_num: int,
    settings,
    logger,
    include: list[str] = ["relationships", "cardinality", "ranges"],
    cardinality_threshold: int = 100,
) -> TableDetailsResult:
    """
    Get detailed metadata for specific tables.
    
    Called after plan approval, before SQL generation.
    Fetches FK relationships, cardinality stats, and value ranges
    for the tables identified in the approved plan.
    
    Args:
        req: MCP server request context
        tables: List of fully-qualified table names from QueryPlan.tables
        flow_step_num: Current flow step for logging
        settings: App settings with db-meta URL
        logger: Logger instance
        include: What details to fetch (relationships, cardinality, ranges, etc.)
        cardinality_threshold: Max distinct values for low-cardinality detection
    
    Returns:
        TableDetailsResult with table details and content hash for lineage
    """
    db = get_db_name(req)
    client = Client(f"{settings.dbmeta}sse")
    
    async with client:
        try:
            result = await client.call_tool(
                "table_details",
                {
                    "req": {
                        "db": db,
                        "tables": tables,
                        "include": include,
                        "cardinality_threshold": cardinality_threshold,
                    }
                },
            )
            
            response_data = json.loads(result[0].text)
            
            logger.info(
                "Got table details",
                flow_stage="mcp_table_details",
                flow_step_num=flow_step_num,
                db=db,
                tables_count=len(response_data.get("tables", [])),
                include=include,
            )
            
            return TableDetailsResult(
                tables=response_data.get("tables", []),
                content_hash=response_data.get("content_hash", ""),
                source="db_meta",
            )
            
        except Exception as e:
            logger.warning(
                "Error fetching table details, continuing without",
                flow_stage="mcp_table_details_error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            # Graceful degradation - return empty result, don't fail flow
            return TableDetailsResult(tables=[], content_hash="", source="db_meta")
```

### 2. Query Planner Integration (`fm_app/workers/interactive_flow/query_planner.py`)

After plan validation passes, fetch table details for the approved tables:

```python
# After validation_result.valid check passes:

# Fetch detailed table metadata for SQL generation
table_details = None
if llm_response.tables:
    try:
        table_details = await get_table_details_mcp(
            req=mcp_ctx["req"],
            tables=llm_response.tables,
            flow_step_num=next(flow_step),
            settings=ctx.settings,
            logger=logger,
            include=["relationships", "low_cardinality_values", "ranges"],
        )
        
        if table_details.tables:
            # Attach to plan for downstream SQL generation
            llm_response.table_details = table_details.tables
            llm_response.table_details_hash = table_details.content_hash
            
            logger.info(
                "Enriched plan with table details",
                flow_stage="plan_enrichment",
                flow_step_num=next(flow_step),
                tables_with_details=len(table_details.tables),
            )
    except Exception as e:
        # Non-blocking - continue without details
        logger.warning(
            "Could not fetch table details",
            error=str(e),
        )
```

### 3. QueryPlan Model Extension (`fm_app/api/model.py`)

Add fields to QueryPlan to carry table details:

```python
class QueryPlan(BaseModel):
    # ... existing fields ...
    
    # New fields for table details (populated after plan approval)
    table_details: Optional[list[dict]] = None
    table_details_hash: Optional[str] = None
```

### 4. Interactive Query Integration (`fm_app/workers/interactive_flow/interactive_query.py`)

Inject table details into the SQL generation prompt:

```python
# In handle_interactive_query, after query_plan context setup:

if query_plan is not None:
    # ... existing plan variable setup ...
    
    # Add table details if available
    if query_plan.table_details:
        interactive_query_vars["table_details"] = format_table_details(
            query_plan.table_details
        )
        logger.info(
            "Including table details in SQL generation",
            flow_stage="table_details_context",
            flow_step_num=next(flow_step),
            tables_count=len(query_plan.table_details),
        )


def format_table_details(table_details: list[dict]) -> str:
    """Format table details for prompt injection."""
    sections = []
    
    for table in table_details:
        table_name = table.get("table_name", "unknown")
        lines = [f"### {table_name}"]
        
        # Primary key
        pk = table.get("primary_key")
        if pk:
            lines.append(f"Primary Key: {', '.join(pk)}")
        
        # Foreign keys
        fks = table.get("foreign_keys", [])
        if fks:
            lines.append("Foreign Keys:")
            for fk in fks:
                cols = ', '.join(fk.get("columns", []))
                ref_table = fk.get("referred_table", "?")
                ref_cols = ', '.join(fk.get("referred_columns", []))
                lines.append(f"  - {cols} → {ref_table}({ref_cols})")
        
        # Column stats
        columns = table.get("columns", [])
        low_card_cols = [c for c in columns if c.get("is_low_cardinality")]
        if low_card_cols:
            lines.append("Low-Cardinality Columns:")
            for col in low_card_cols:
                values = col.get("distinct_values", [])
                if values:
                    vals_str = ', '.join(f"'{v}'" for v in values[:10])
                    if len(values) > 10:
                        vals_str += f" ... ({len(values)} total)"
                    lines.append(f"  - {col['name']}: [{vals_str}]")
        
        # Ranges for date/numeric columns
        range_cols = [c for c in columns if c.get("min_value") or c.get("max_value")]
        if range_cols:
            lines.append("Value Ranges:")
            for col in range_cols:
                min_v = col.get("min_value", "?")
                max_v = col.get("max_value", "?")
                lines.append(f"  - {col['name']}: {min_v} to {max_v}")
        
        sections.append('\n'.join(lines))
    
    return '\n\n'.join(sections)
```

### 5. Prompt Template Update (`packages/resources/.../interactive_query/prompt.md`)

Add conditional section for table details:

```markdown
{% if table_details %}
## Table Relationships & Statistics

The following detailed information is available for the tables in your query plan:

{{ table_details }}

Use this information to:
- Write correct JOIN conditions using foreign key relationships
- Filter by valid values for low-cardinality columns (use exact values shown)
- Apply reasonable date/numeric range filters based on actual data ranges

{% endif %}
```

### 6. MCP Prompt Consumption

For the new MCP prompts (`domain_model`, `sql_dialect`, `prompt_instructions`), fm-app will:

```python
# In prompt assembler or MCP provider initialization:

async def get_mcp_prompts(client: Client, db: str) -> dict[str, str]:
    """Fetch static MCP prompts at session/flow start."""
    prompts = {}
    
    for prompt_name in ["domain_model", "sql_dialect", "prompt_instructions"]:
        try:
            result = await client.get_prompt(prompt_name, {"db": db})
            prompts[prompt_name] = result.messages[0].content
        except Exception:
            # Optional prompts - continue without
            pass
    
    return prompts

# These can be cached per session since they rarely change
# Inject into slot variables when rendering query_planner and interactive_query
```

### 7. Integration Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FM-APP FLOW                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. User Request                                                     │
│       │                                                              │
│       ▼                                                              │
│  2. prompt_items_v2(items=["DBStruct"], schema_top_k=10)            │
│     └─► Lightweight schema for planning                              │
│       │                                                              │
│       ▼                                                              │
│  3. Query Planner generates QueryPlan                                │
│     └─► Plan includes: tables, columns, filters, assumptions         │
│       │                                                              │
│       ▼                                                              │
│  4. validate_plan(tables, columns)                                   │
│     └─► Ensure tables/columns exist                                  │
│       │                                                              │
│       ▼                                                              │
│  5. [USER APPROVAL]                                                  │
│       │                                                              │
│       ▼                                                              │
│  6. table_details(tables=plan.tables)  ◄── NEW                      │
│     └─► FK relationships, cardinality, value ranges                  │
│       │                                                              │
│       ▼                                                              │
│  7. Interactive Query (SQL Generation)                               │
│     └─► Uses plan + table_details for accurate SQL                   │
│       │                                                              │
│       ▼                                                              │
│  8. preflight_query(sql)                                             │
│     └─► EXPLAIN validation                                           │
│       │                                                              │
│       ▼                                                              │
│  9. Execute & Return Results                                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 8. Feature Flag Support

Add feature flag for gradual rollout:

```python
# In fm_app/settings.py:
class Settings(BaseSettings):
    # ... existing settings ...
    
    # Feature flags
    enable_table_details: bool = False  # Phase 3: Enable after testing

# In query_planner.py:
if ctx.settings.enable_table_details and llm_response.tables:
    table_details = await get_table_details_mcp(...)
```

### 9. Tracing Integration

Add tracing for table_details calls:

```python
# In get_table_details_mcp:
if tracer:
    await tracer.trace_mcp_call(
        tool_name="table_details",
        input_args={"tables": tables, "include": include},
        output_hash=response_data.get("content_hash", ""),
        duration_ms=timer.duration_ms,
        metadata={
            "tables_returned": len(response_data.get("tables", [])),
            "db": db,
        },
    )
```

---

## Relationship to Autonomous Agentic Flow

This plan provides foundational MCP capabilities for the [Autonomous Agentic Flow](./autonomous-agentic-flow.md):

| MCP Capability | Agent Usage |
|----------------|-------------|
| `table_details` tool | Agent fetches deep schema info when planning complex queries |
| `domain_model` prompt | Agent understands business entities at session start |
| `sql_dialect` prompt | Agent generates correct SQL syntax |
| `prompt_instructions` prompt | Agent follows business rules |
| `validate_plan` tool | Agent validates its own plans before execution |

The granular schema exploration enables the agent to:
1. **Plan intelligently**: Lightweight schema for initial planning, deep details when needed
2. **Self-correct**: Validate tables/columns exist before generating SQL
3. **Ask better questions**: Understand FK relationships to suggest relevant follow-ups

---

## Rollout Plan

1. **Phase 1**: Add `table_details` tool to db-meta (no fm-app changes)
2. **Phase 2**: Add fm-app client function (optional usage)
3. **Phase 3**: Integrate into query planner (behind feature flag)
4. **Phase 4**: Enable by default after validation
