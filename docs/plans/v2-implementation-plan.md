# v2 Implementation Plan

## Overview

This document outlines the step-by-step implementation plan for Semantic Grid v2, incorporating:
- [v2 Architecture](../future/v2-architecture.md) - Core system redesign
- [DB Onboarding Flow](./db-onboarding-flow.md) - Database configuration workflow

## Guiding Principles

1. **db-meta-v2 first** - Build the "brain" before the client
2. **Validate with Claude Desktop** - Test MCP tools before building custom UI
3. **Incremental delivery** - Each milestone is independently valuable
4. **Coexist with v1** - v2 runs alongside v1 until ready to sunset

## Prerequisites

Before starting:
- [ ] Python 3.13+ installed
- [ ] UV package manager installed
- [ ] Node.js 20+ / Bun 1.2.10+ installed
- [ ] Claude Desktop installed (for testing)
- [ ] Milvus instance available (for query examples)

---

## Phase 1: Foundation

**Goal:** Scaffold db-meta-v2 with core infrastructure, validate with Claude Desktop.

### 1.1 Scaffold db-meta-v2

```
apps/db-meta-v2/
├── pyproject.toml
├── README.md
├── src/
│   └── db_meta_v2/
│       ├── __init__.py
│       ├── server.py           # FastMCP server entry point
│       ├── config.py           # Pydantic Settings
│       └── tools/
│           └── __init__.py
├── tests/
│   └── __init__.py
└── run.sh
```

**Tasks:**
- [ ] Create `apps/db-meta-v2/` directory structure
- [ ] Set up `pyproject.toml` with dependencies:
  - `fastmcp` - MCP server framework
  - `pydantic-ai` - Agent framework with sampling support
  - `pydantic-graph` - State machine for workflows
  - `sqlalchemy` - Database introspection
  - `sqlglot` - SQL parsing and validation
  - `trino[sqlalchemy]` - Trino driver
  - `clickhouse-sqlalchemy` - ClickHouse driver
  - `psycopg2-binary` - PostgreSQL driver
- [ ] Create basic `server.py` with FastMCP
- [ ] Create `config.py` with database connection settings
- [ ] Add `run.sh` script
- [ ] Test server starts and responds to MCP ping

**Validation:** `uv run python -m db_meta_v2.server` starts without errors.

### 1.2 Create Shared Models Package

```
packages/sg-models/
├── pyproject.toml
├── src/
│   └── sg_models/
│       ├── __init__.py
│       ├── task.py         # Task, TaskStatus
│       ├── plan.py         # QueryPlan, PlanStep
│       ├── query.py        # QueryResult, QueryMetadata
│       ├── ui.py           # GridSpec, ColumnSpec
│       └── onboarding.py   # OnboardingState, OnboardingPhase
└── tests/
```

**Tasks:**
- [ ] Create `packages/sg-models/` directory structure
- [ ] Define core models in each module
- [ ] Add sg-models as dependency to db-meta-v2
- [ ] Ensure models are JSON-serializable for MCP

**Validation:** Models can be imported and serialized.

### 1.3 Database Connectivity

**Tasks:**
- [ ] Implement multi-dialect connection factory
- [ ] Support connection strings for: Trino, PostgreSQL, ClickHouse
- [ ] Add connection pooling
- [ ] Create `test_connection` tool
- [ ] Implement schema introspection (list schemas, tables, columns)

**Validation:** Connect to test database, list tables via MCP tool.

### 1.4 Claude Desktop Integration

**Tasks:**
- [ ] Create Claude Desktop MCP config for db-meta-v2
- [ ] Document setup in README
- [ ] Test basic tool calls from Claude Desktop

**Claude Desktop config (`~/.config/claude/claude_desktop_config.json`):**
```json
{
  "mcpServers": {
    "db-meta-v2": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/apps/db-meta-v2", "python", "-m", "db_meta_v2.server"],
      "env": {
        "DATABASE_URL": "trino://user:pass@host:port/catalog/schema"
      }
    }
  }
}
```

**Validation:** Claude Desktop can call `test_connection` and `list_tables` tools.

---

## Phase 2: Onboarding Flow

**Goal:** Complete database onboarding workflow working in Claude Desktop.

### 2.1 Onboarding State Machine

**Tasks:**
- [ ] Create `OnboardingState` model in sg-models
- [ ] Create `OnboardingPhase` enum
- [ ] Implement pydantic-graph state machine with nodes:
  - `InitNode` - Connection, dialect detection
  - `SchemaNode` - Table description loop
  - `DomainNode` - Domain model generation
  - `BusinessRulesNode` - Rule capture/interview
  - `QueryTrainingNode` - Example collection
- [ ] Implement state persistence (YAML files)
- [ ] Implement state loading and resume

**Validation:** State machine transitions correctly in unit tests.

### 2.2 SQL Dialect Detection

**Tasks:**
- [ ] Implement connection string parsing for dialect detection
- [ ] Implement server query verification fallback
- [ ] Create pre-defined dialect files:
  - `packages/resources/dbmeta_app/sql-dialects/trino.yaml`
  - `packages/resources/dbmeta_app/sql-dialects/postgresql.yaml`
  - `packages/resources/dbmeta_app/sql-dialects/clickhouse.yaml`
- [ ] Implement `detect_dialect` tool
- [ ] Implement `set_dialect` tool (manual override)

**Validation:** Correct dialect detected from various connection strings.

### 2.3 Schema Description Tools

**Tasks:**
- [ ] Implement `onboarding_start` tool
- [ ] Implement `onboarding_status` tool
- [ ] Implement `onboarding_next` tool
- [ ] Implement `describe_table` with MCP sampling
- [ ] Implement `onboarding_approve` tool
- [ ] Implement `onboarding_skip` tool
- [ ] Create artifact storage structure:
  ```
  packages/resources/dbmeta_app/providers/{provider_id}/
  ├── onboarding_state.yaml
  ├── sql_dialect.yaml
  ├── schema_descriptions.yaml
  └── ...
  ```

**Validation:** Complete schema description flow in Claude Desktop.

### 2.4 Domain Model Generation

**Tasks:**
- [ ] Implement domain model generation via MCP sampling
- [ ] Implement `generate_domain_model` tool
- [ ] Implement approval workflow for domain model
- [ ] Save approved domain model to `domain_model.md`

**Validation:** Domain model generated and approved in Claude Desktop.

### 2.5 Business Rules Capture

**Tasks:**
- [ ] Implement `analyze_schema_for_rules` tool
- [ ] Implement `start_entity_interview` tool
- [ ] Implement `capture_rule` tool
- [ ] Implement rule categorization (synonyms, logic, filters, etc.)
- [ ] Generate `prompt_instructions.yaml` from captured rules
- [ ] Implement `test_rules_with_query` tool

**Validation:** Capture 5+ rules through interview, generate YAML.

---

## Phase 3: Query Generation

**Goal:** Generate SQL from natural language using onboarded schema/rules.

### 3.1 Query Planning

**Tasks:**
- [ ] Define `QueryPlan` model with steps
- [ ] Implement `plan_query` tool using MCP sampling
- [ ] Implement plan validation against schema
- [ ] Implement plan approval via MCP elicitation

**Validation:** Generate and approve query plan in Claude Desktop.

### 3.2 SQL Generation

**Tasks:**
- [ ] Implement `generate_sql` tool using MCP sampling
- [ ] Include schema descriptions in prompt
- [ ] Include dialect rules in prompt
- [ ] Include business rules in prompt
- [ ] Implement SQL syntax validation (sqlglot)

**Validation:** Generate syntactically valid SQL for various intents.

### 3.3 SQL Validation & Repair

**Tasks:**
- [ ] Implement `validate_sql` tool with EXPLAIN
- [ ] Implement cost estimation and tier classification
- [ ] Implement `repair_sql` tool for fixing errors
- [ ] Implement repair loop (max 3 iterations)
- [ ] Implement read-only enforcement

**Validation:** Invalid SQL is detected and repaired automatically.

### 3.4 Query Execution

**Tasks:**
- [ ] Implement `execute_sql` tool
- [ ] Implement result limiting and pagination
- [ ] Implement query timeout handling
- [ ] Implement result caching

**Validation:** Execute validated query, return results.

### 3.5 End-to-End `get_data` Tool

**Tasks:**
- [ ] Implement unified `get_data` tool
- [ ] Orchestrate: plan → generate → validate → repair → execute
- [ ] Stream state updates during execution
- [ ] Return results with metadata

**Validation:** Natural language query returns data in Claude Desktop.

---

## Phase 4: Query Examples & Semantic Search

**Goal:** Store and retrieve query examples for improved generation.

### 4.1 Milvus Integration

**Tasks:**
- [ ] Set up Milvus collection for query examples
- [ ] Define embedding schema
- [ ] Implement embedding generation (OpenAI)
- [ ] Implement `add_query_example` tool
- [ ] Implement `list_examples` tool

**Validation:** Add and list query examples.

### 4.2 Semantic Query Matching

**Tasks:**
- [ ] Implement semantic search in `get_data` flow
- [ ] Surface similar existing queries before generating new
- [ ] Implement "use existing or generate new" elicitation
- [ ] Track query usage counts

**Validation:** Similar queries surfaced when asking equivalent questions.

### 4.3 Query Training Loop

**Tasks:**
- [ ] Integrate query training into onboarding flow
- [ ] Implement feedback collection on generated queries
- [ ] Store approved queries as examples
- [ ] Track iteration history per example

**Validation:** Complete training loop adds examples to Milvus.

---

## Phase 5: Rule Distillation

**Goal:** Automatically discover business rules from usage patterns.

### 5.1 Feedback Collection

**Tasks:**
- [ ] Define feedback record schema
- [ ] Implement feedback storage
- [ ] Capture: user input, generated SQL, corrections, final SQL
- [ ] Link feedback to query executions

**Validation:** Feedback records stored for queries with corrections.

### 5.2 Distillation Pipeline

**Tasks:**
- [ ] Implement `collect_feedback_batch` tool
- [ ] Implement `run_distillation` tool
- [ ] Implement pattern analysis via LLM
- [ ] Generate candidate rules with confidence scores
- [ ] Store candidates in `candidate_rules.yaml`

**Validation:** Distillation proposes rules from synthetic feedback data.

### 5.3 Rule Approval Workflow

**Tasks:**
- [ ] Implement `list_candidate_rules` tool
- [ ] Implement `review_candidate_rule` tool
- [ ] Implement `approve_rule` / `reject_rule` tools
- [ ] Append approved rules to `prompt_instructions.yaml`
- [ ] Track distillation metrics

**Validation:** Approve candidate rule, verify it appears in prompt instructions.

### 5.4 Scheduled Distillation

**Tasks:**
- [ ] Implement scheduled distillation job
- [ ] Configure schedule (daily/weekly)
- [ ] Implement notification of pending rules for review

**Validation:** Scheduled job runs and surfaces new candidates.

---

## Phase 6: UI Specification

**Goal:** db-meta-v2 returns UI specs alongside query results.

### 6.1 GridSpec Model

**Tasks:**
- [ ] Define `GridSpec` model in sg-models
- [ ] Define `ColumnSpec` with formatters
- [ ] Define `ChartSpec` for visualization suggestions
- [ ] Infer column types from SQL result metadata

**Validation:** GridSpec model serializes correctly.

### 6.2 UI Generation

**Tasks:**
- [ ] Generate GridSpec from query results
- [ ] Infer appropriate formatters (address, currency, datetime)
- [ ] Suggest default sort and grouping
- [ ] Generate chart suggestions when appropriate
- [ ] Include UI spec in `get_data` response

**Validation:** Query results include UI spec in Claude Desktop.

---

## Phase 7: fm-app-v2

**Goal:** Thin PydanticAI agent that connects to db-meta-v2.

### 7.1 Scaffold fm-app-v2

```
apps/fm-app-v2/
├── pyproject.toml
├── src/
│   └── fm_app_v2/
│       ├── __init__.py
│       ├── main.py           # FastAPI app
│       ├── agent.py          # PydanticAI agent
│       ├── config.py         # Settings
│       └── routes/
│           └── agent.py      # AG-UI endpoint
├── tests/
└── run.sh
```

**Tasks:**
- [ ] Create `apps/fm-app-v2/` directory structure
- [ ] Set up `pyproject.toml` with dependencies:
  - `pydantic-ai` - Agent framework
  - `fastapi` - Web framework
  - `sg-models` - Shared models
- [ ] Create basic FastAPI app
- [ ] Create PydanticAI agent with db-meta-v2 as toolset
- [ ] Add `run.sh` script

**Validation:** fm-app-v2 starts and can call db-meta-v2 tools.

### 7.2 AG-UI Integration

**Tasks:**
- [ ] Implement AG-UI adapter endpoint
- [ ] Stream state updates from db-meta-v2
- [ ] Handle plan approval interrupts
- [ ] Forward query results with UI spec

**Validation:** AG-UI client receives streamed state updates.

### 7.3 Session Management

**Tasks:**
- [ ] Implement session storage (conversations)
- [ ] Implement user preferences
- [ ] Implement message history

**Validation:** Conversations persisted across requests.

---

## Phase 8: Web Frontend

**Goal:** Web UI with enhanced features for v2.

### 8.1 v2 API Routes

**Tasks:**
- [ ] Add `/api/v2/agent` endpoint for AG-UI
- [ ] Feature-flag between v1 and v2 routes
- [ ] Implement authentication for v2

**Validation:** Web app can call v2 API.

### 8.2 AG-UI React Integration

**Tasks:**
- [ ] Add CopilotKit dependencies
- [ ] Implement `useAgent` hook for query workspace
- [ ] Implement reactive status display
- [ ] Implement plan approval UI
- [ ] Render GridSpec to MUI X Data Grid Pro

**Validation:** Query flow works end-to-end in web UI.

### 8.3 Onboarding Dashboard

**Tasks:**
- [ ] Create admin onboarding page
- [ ] Implement phase progress visualization
- [ ] Implement Monaco editor for YAML/MD
- [ ] Implement diff view for approvals
- [ ] Implement rule candidate review UI

**Validation:** Complete onboarding flow in web UI.

---

## Phase 9: Evaluation & Quality

**Goal:** Systematic evaluation of query generation quality.

### 9.1 pydantic-evals Setup

**Tasks:**
- [ ] Set up evals directory structure in db-meta-v2
- [ ] Implement SQL syntax evaluator
- [ ] Implement semantic correctness evaluator
- [ ] Implement intent match evaluator (LLM-as-judge)
- [ ] Implement workflow evaluator (span-based)

**Validation:** Evals run and produce scores.

### 9.2 Eval Datasets

**Tasks:**
- [ ] Create `get_data.yaml` test cases
- [ ] Create `repair_loop.yaml` test cases
- [ ] Create `edge_cases.yaml` test cases
- [ ] Import cases from existing query examples

**Validation:** Datasets load and run against tools.

### 9.3 CI Integration

**Tasks:**
- [ ] Add GitHub Actions workflow for evals
- [ ] Run on push to db-meta-v2
- [ ] Upload results as artifacts
- [ ] Set up Logfire integration (optional)

**Validation:** Evals run in CI on every push.

---

## Phase 10: Production Hardening

**Goal:** Production-ready v2 deployment.

### 10.1 Error Handling

**Tasks:**
- [ ] Implement comprehensive error handling in all tools
- [ ] Add retry logic for transient failures
- [ ] Implement graceful degradation
- [ ] Add structured logging

**Validation:** System recovers gracefully from errors.

### 10.2 Performance

**Tasks:**
- [ ] Implement query result caching
- [ ] Optimize large schema handling (100+ tables)
- [ ] Add connection pool tuning
- [ ] Profile and optimize hot paths

**Validation:** Performance benchmarks meet targets.

### 10.3 Security

**Tasks:**
- [ ] Implement authentication for MCP endpoints
- [ ] Encrypt stored database credentials
- [ ] Audit logging for all operations
- [ ] Read-only enforcement verification

**Validation:** Security audit passes.

### 10.4 Deployment

**Tasks:**
- [ ] Create Dockerfile for db-meta-v2
- [ ] Create Dockerfile for fm-app-v2
- [ ] Update Kubernetes manifests
- [ ] Set up staging environment
- [ ] Document deployment process

**Validation:** v2 deployed to staging, functional end-to-end.

---

## Milestone Summary

| Phase | Milestone | Key Deliverable | Validation |
|-------|-----------|-----------------|------------|
| 1 | Foundation | db-meta-v2 scaffold | Claude Desktop connects |
| 2 | Onboarding | Complete onboarding flow | Onboard DB via Claude Desktop |
| 3 | Query Gen | `get_data` tool | NL → SQL → Results |
| 4 | Examples | Semantic search | Similar queries surfaced |
| 5 | Distillation | Auto rule discovery | Rules proposed from usage |
| 6 | UI Spec | GridSpec in responses | UI hints in results |
| 7 | fm-app-v2 | Thin agent client | Agent calls db-meta-v2 |
| 8 | Web UI | Enhanced frontend | Full flow in browser |
| 9 | Evals | Quality measurement | CI runs evals |
| 10 | Production | Deployment ready | Staging functional |

---

## Dependencies Between Phases

```
Phase 1: Foundation
    │
    ├──► Phase 2: Onboarding ──► Phase 5: Distillation
    │         │
    │         ▼
    │    Phase 3: Query Gen ──► Phase 4: Examples
    │         │
    │         ▼
    │    Phase 6: UI Spec
    │         │
    ▼         ▼
Phase 7: fm-app-v2
    │
    ▼
Phase 8: Web UI
    │
    ▼
Phase 9: Evals
    │
    ▼
Phase 10: Production
```

---

## Getting Started

Begin with **Phase 1.1: Scaffold db-meta-v2**:

```bash
cd apps
mkdir -p db-meta-v2/src/db_meta_v2/tools
mkdir -p db-meta-v2/tests
cd db-meta-v2

# Create pyproject.toml
cat > pyproject.toml << 'EOF'
[project]
name = "db-meta-v2"
version = "0.1.0"
description = "MCP server for database semantics and query intelligence"
requires-python = ">=3.13"
dependencies = [
    "fastmcp>=0.1.0",
    "pydantic-ai>=0.1.0",
    "pydantic-graph>=0.1.0",
    "pydantic-settings>=2.0.0",
    "sqlalchemy>=2.0.0",
    "sqlglot>=20.0.0",
    "trino[sqlalchemy]>=0.330.0",
    "clickhouse-sqlalchemy>=0.3.0",
    "psycopg2-binary>=2.9.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
EOF

# Initialize with uv
uv sync
```

Then proceed through each phase sequentially, validating at each milestone.
