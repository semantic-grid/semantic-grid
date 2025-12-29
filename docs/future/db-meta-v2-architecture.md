# DB-Meta v2 Architecture: Database Context Layer

## Overview

This document captures the architectural vision for db-meta v2, which transforms the current metadata service into a complete "Database Context Layer" (or "AI-Native Semantic Layer"). The key principle is clean separation between:

- **DB-META**: All database knowledge, execution, and artifact storage (MCP server)
- **FM-APP**: Agentic orchestration harness only (replaceable by Claude Desktop, Cursor, etc.)

## Core Principle: Harness Replaceability

FM-APP should be replaceable by any MCP client. This means:

```
┌─────────────────────────────────────────┐ ┌─────────────────────────────────────────┐
│            FM-APP v2                    │ │            DB-META v2                   │
│     "Agentic Orchestration Layer"       │ │     "Database Context Layer"            │
│      (Replaceable Harness)              │ │         (MCP Server)                    │
├─────────────────────────────────────────┤ ├─────────────────────────────────────────┤
│                                         │ │                                         │
│  INTERFACE                              │ │  MCP INTERFACE                          │
│  ├── REST API (for Web UI)              │ │  ├── Resources                          │
│  ├── WebSocket (real-time)              │ │  │   ├── schema://                      │
│  └── MCP Client (to db-meta)            │ │  │   ├── docs://                        │
│                                         │ │  │   ├── query://                       │
│                                         │ │  │   └── data://                        │
│                                         │ │  ├── Tools                              │
│                                         │ │  │   ├── register_query                 │
│                                         │ │  │   ├── execute_query                  │
│                                         │ │  │   ├── validate_sql                   │
│                                         │ │  │   └── get_column_stats               │
│                                         │ │  └── Prompts                            │
│                                         │ │      ├── sql_generation                 │
│                                         │ │      └── query_analysis                 │
├─────────────────────────────────────────┤ ├─────────────────────────────────────────┤
│  AGENT LOOP                             │ │  KNOWLEDGE LAYER                        │
│  ├── Intent analysis                    │ │  ├── Schema introspection               │
│  ├── Clarification (ask_user)           │ │  ├── Domain documentation               │
│  ├── Goal tracking                      │ │  ├── SQL dialect rules                  │
│  ├── Plan generation                    │ │  ├── Query patterns/examples            │
│  ├── Plan approval UX                   │ │  └── Column statistics                  │
│  ├── Step execution                     │ │                                         │
│  └── Result verification                │ │                                         │
├─────────────────────────────────────────┤ ├─────────────────────────────────────────┤
│  LLM INTEGRATION                        │ │  EXECUTION LAYER                        │
│  ├── Anthropic (Claude)                 │ │  ├── SQL validation (EXPLAIN)           │
│  ├── OpenAI (GPT)                       │ │  ├── Query execution                    │
│  └── Others (pluggable)                 │ │  └── Async jobs (Celery + RabbitMQ)     │
├─────────────────────────────────────────┤ ├─────────────────────────────────────────┤
│  AGENT MEMORY (Session State)           │ │  STORAGE LAYER                          │
│  ├── Conversation history               │ │  ├── PostgreSQL (query registry)        │
│  ├── Current goal                       │ │  ├── Redis (cache)                      │
│  ├── Active plan + step state           │ │  ├── Milvus (vector search)             │
│  ├── User preferences                   │ │  └── S3/Blob (data artifacts)           │
│  └── References to MCP artifacts        │ │                                         │
├─────────────────────────────────────────┤ ├─────────────────────────────────────────┤
│  VALUE-ADD FEATURES                     │ │  CONNECTIONS                            │
│  ├── Web UI                             │ │  ├── Trino (warehouse)                  │
│  ├── Multi-tenant auth                  │ │  ├── ClickHouse (warehouse)             │
│  ├── Team sharing                       │ │  └── PostgreSQL (warehouse)             │
│  └── Cost controls / quotas             │ │                                         │
└─────────────────────────────────────────┘ └─────────────────────────────────────────┘
```

## What Moves from FM-APP to DB-META

| Current Location (FM-APP) | New Location (DB-META MCP) |
|---------------------------|---------------------------|
| `packages/resources/.../domain.md` | `docs://{db}/domain_model` resource |
| `packages/resources/.../sql_dialect.md` | `docs://{db}/sql_dialect` resource |
| Query examples in prompts | `docs://{db}/query_patterns` resource |
| Query execution (direct to warehouse) | `execute_query` tool |

## MCP Interface Design

### Resources (Read-only, Deterministic)

```
schema://{db}/tables              → Table list + descriptions
schema://{db}/table/{name}        → Column details, types, PKs, FKs
schema://{db}/table/{name}/stats  → Cardinality, ranges

docs://{db}/domain_model          → Business entities/concepts
docs://{db}/sql_dialect           → SQL syntax rules, quirks
docs://{db}/query_patterns        → Example queries

query://{id}/sql                  → SQL for executed query
query://{id}/metadata             → Columns, stats
query://user/{user}/history       → User's query history

data://{query_id}                 → Cached result rows
data://{query_id}/summary         → Stats about results
```

### Tools (Callable, Side Effects)

```python
register_query(sql, db, name) → {query_id, estimated_rows, estimated_cost}
    # Validates SQL, creates query record, does NOT execute

execute_query(query_id, limit, cache) → {columns, rows, execution_time}
    # Runs registered query, creates data artifact

execute_sql(sql, db, limit) → {query_id, columns, rows}
    # Convenience: register + execute in one call

validate_sql(sql, db) → {valid, error, explain_plan}
    # Check syntax, EXPLAIN (no storage)

get_column_stats(table, column) → {distinct_count, min, max, values}
    # Column statistics (no storage)
```

### Prompts (Server Templates)

```python
sql_generation(intent, schema, domain, dialect) → prompt messages
query_analysis(data, question) → prompt messages
```

## Query Lifecycle: Register → Execute (Deferred)

A key insight is separating query registration from execution:

```
LLM generates SQL
       │
       ▼
register_query(sql)  ──► Query record created, estimates returned
       │
       ▼
User reviews / modifies / approves
       │
       ▼
execute_query(id)    ──► Query runs, data artifact created
       │
       ▼
data://{id}          ──► Results available for analysis
```

This allows:
- User review before expensive queries
- Cost estimation upfront
- Query modification without re-execution
- Saved queries for later

## Agent Memory vs MCP Artifacts

Clear separation between interpretation and facts:

```
AGENT MEMORY (Harness - fm-app):
├── Conversation history (user said X, I said Y)
├── Current goal ("understand revenue drop")
├── Plan state (step 2 of 5 complete)
├── Findings / interpretations ("EMEA down 23%")
└── References to MCP artifacts (query_ids)

MCP ARTIFACTS (DB-META):
├── Schema (tables, columns, types)
├── Query records (SQL that was registered/executed)
├── Data artifacts (result rows from execution)
└── Documentation (domain model, dialect)

PRINCIPLE:
- MCP = Library (books, facts, data) - same for everyone
- Agent Memory = Notes about the books - personal to harness
```

## Goal Hierarchy

Three levels of objectives:

| Level | Example | Scope | Owner |
|-------|---------|-------|-------|
| **Goal** | "Understand EMEA revenue drop" | Multi-request, business objective | Harness (optional) |
| **Task/Intent** | "Generate a query for X" | Single request action | Harness (implemented) |
| **Step** | "Validate SQL" | Internal operation | Both |

Current implementation operates at Task/Intent level. Business Goals are an optional enhancement for sophisticated agentic behavior.

## Data Artifact Storage

DB-META stores query results for LLM analysis:

```
QUERY RECORD (small, permanent):
├── query_id, sql, db, columns
├── estimated_rows, estimated_cost
├── status (registered | executed)
└── execution_stats

DATA ARTIFACT (potentially large, TTL-based):
├── Stored in S3/Blob
├── Max 10,000 rows per artifact
├── TTL: 24 hours
├── LRU eviction when cache full
```

This enables:
- Cross-harness data sharing
- LLM analysis without re-execution
- Consistent point-in-time snapshots

## Infrastructure Components

| Component | Purpose | Required? |
|-----------|---------|-----------|
| **FastAPI** | MCP server, API | Yes |
| **PostgreSQL** | Query registry, metadata | Yes |
| **Redis** | Cache (stats, hot data) | Yes |
| **Milvus** | Semantic search (schema, queries) | Yes (for large schemas) |
| **S3/Blob** | Data artifacts storage | Yes |
| **Celery** | Async job processing | Phase 2 (for long queries) |
| **RabbitMQ** | Message queue for Celery | Phase 2 |
| **Trino/Warehouse** | Query execution target | Yes (external) |

## Replaceability Test

Can Claude Desktop replace FM-APP for core functionality?

| Capability | FM-APP | Claude Desktop |
|------------|--------|----------------|
| Agent loop | Built custom | Built-in |
| LLM | Multi-provider | Claude |
| Schema exploration | Via db-meta | Via db-meta |
| SQL generation | LLM | LLM |
| Query execution | Via db-meta | Via db-meta |
| Web UI | Yes | No |
| Session persistence | Yes | No (memory only) |
| Goal tracking | Yes | No (implicit) |
| Multi-tenant | Yes | No |

**Verdict**: Core query generation/execution works. Enterprise features (UI, sessions, tenancy) are FM-APP value-add.

## Naming Considerations

DB-META v2 could be called:
- **Database Context Layer** - emphasizes what it provides to LLMs
- **AI-Native Semantic Layer** - positions against traditional BI semantic layers
- **Database MCP Server** - accurate but generic

Key distinction from traditional semantic layers:
- Traditional: Human writes business term → Layer returns SQL
- DB-META: LLM reads context → LLM writes SQL → DB-META validates/executes

## Implementation Phases

### Phase 1: Core (Current Focus)
- `get_table_details` MCP tool (implemented)
- Schema introspection enhancements
- Caching layer

### Phase 2: Query Lifecycle
- `register_query` / `execute_query` separation
- Query record storage
- Data artifact caching

### Phase 3: Knowledge Migration
- Move domain.md to db-meta resources
- Move sql_dialect to db-meta resources
- Add query examples as resources

### Phase 4: Full Replaceability
- All knowledge in db-meta
- FM-APP as thin orchestration layer
- Claude Desktop can use db-meta directly

## Related Documents

- `docs/future/autonomous-agentic-flow.md` - FM-APP agent loop phases
- `docs/future/db-meta-granular-schema-exploration.md` - Detailed implementation plan for Phase 1
- `docs/future/mcp-elicitation-sampling-integration.md` - MCP Elicitation, Sampling & UI integration for autonomous db-meta (includes MCP UI/Apps for rich interactive interfaces)
- `.claude/plans/snoopy-stirring-scott.md` - Current implementation progress
