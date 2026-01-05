# DB Onboarding Flow - Planning Document

## Overview

An agentic, AI-assisted flow for onboarding new databases to the db-meta v2 MCP server. Designed for DB specialists, data engineers, and analysts to iteratively configure schema descriptions, domain models, and query examples through a conversational interface.

## Goals

1. **Zero-to-configured** - Start with just a DATABASE_URL, end with a fully described schema
2. **AI-assisted** - Generate descriptions and documentation with human approval
3. **Iterative** - Pausable/resumable stateful flow
4. **Self-improving** - Build query examples through real usage feedback

---

## Tech Stack & v2 Architecture Alignment

This onboarding flow is designed to integrate with the [v2 architecture](../future/v2-architecture.md), reusing its core components.

### Design Principles (from v2)

1. **db-meta-v2 owns the intelligence** - Onboarding tools live in db-meta-v2
2. **Client is swappable** - Works with Claude Desktop, ChatGPT, or Web UI
3. **MCP-first** - Uses MCP Sampling (LLM calls) and Elicitation (approvals)
4. **Progressive enhancement** - Core works in any client; rich UX in web UI

### Client Options

| Client | Phase | Pros | Cons |
|--------|-------|------|------|
| **Claude Desktop** | 1 (MVP) | Zero UI work, immediate, native MCP | Limited YAML/MD editing |
| **ChatGPT + MCP** | 1 | Same benefits | Same limitations |
| **Web UI (fm-app-v2)** | 2 | Rich editing, progress tracking | More work to build |

### v2 Components Reused

| v2 Component | Use in Onboarding |
|--------------|-------------------|
| **MCP Sampling** | LLM generates descriptions, rules, domain model via client's LLM |
| **MCP Elicitation** | Admin approvals ("Is this description correct?") |
| **PydanticAI Agents** | Orchestrate multi-step onboarding flows |
| **pydantic-graph** | State machine for phases (init → schema → domain → rules → training) |
| **AG-UI** | Stream onboarding progress to web UI |
| **pydantic-evals** | Validate rule quality, test generated descriptions |
| **FastMCP** | Expose onboarding tools as MCP server |

### Implementation Phases

#### Phase 1: MCP Tools + Claude Desktop (MVP)

Build onboarding as MCP tools in db-meta-v2, test with Claude Desktop:

```python
# db-meta-v2/tools/onboarding.py
from fastmcp import FastMCP
from pydantic_ai import Agent
from pydantic_ai.models.mcp_sampling import MCPSamplingModel

server = FastMCP('db-meta-v2')
description_generator = Agent(MCPSamplingModel(), output_type=TableDescription)

@server.tool()
async def describe_table(table_name: str) -> TableDescription:
    """Generate AI description for a table, request approval via elicitation."""
    schema = await introspect_table(table_name)
    
    # Uses CLIENT's LLM via MCP sampling
    result = await description_generator.run(
        f"Generate description for table:\n{schema}"
    )
    
    # Request approval via MCP elicitation
    approved = await ctx.elicit(
        ApprovalSchema,
        message=f"Approve this description?\n\n{result.output}"
    )
    
    if approved.accept:
        await save_description(table_name, result.output)
        return result.output
    else:
        # Re-generate with feedback
        return await describe_table_with_feedback(table_name, approved.feedback)
```

**Claude Desktop session example:**
```
User: /init
db-meta: Connected to Trino. Detected dialect: trino. Found 45 tables.

User: /describe-tables
db-meta: Generating description for 'users' table...
         
         "User accounts storing authentication credentials and profile data"
         
         Columns:
         - id: Primary key, unique user identifier
         - email: User email for authentication
         ...
         
         [Approve] [Edit] [Skip]
```

**Validation:** Connect Claude Desktop to db-meta-v2, complete full onboarding flow via chat.

#### Phase 2: Web UI Enhancements

Once core tools work with Claude Desktop, add web UI features via AG-UI:

- **YAML/MD Editor**: Monaco editor with syntax highlighting
- **Progress Dashboard**: Visual phase tracker with completion %
- **Rule Management**: Approve/reject candidate rules from distillation
- **Diff View**: Show changes before saving
- **Batch Operations**: Approve multiple descriptions at once

```tsx
// Web UI using AG-UI for state streaming
function OnboardingDashboard() {
  const { state } = useAgent<OnboardingState>({
    url: '/api/v2/onboarding'
  });

  return (
    <Box>
      <PhaseIndicator current={state.phase} />
      
      {state.phase === 'schema' && (
        <SchemaDescriptionEditor 
          table={state.currentTable}
          description={state.proposedDescription}
          onApprove={...}
          onEdit={...}
        />
      )}
      
      {state.phase === 'business_rules' && (
        <RuleCandidateReview 
          candidates={state.candidateRules}
          onApprove={...}
          onReject={...}
        />
      )}
    </Box>
  );
}
```

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Onboarding MCP Tools                          │
│                    (lives in db-meta-v2)                         │
│                                                                  │
│  Tools: init, detect_dialect, describe_table, capture_rule...   │
│  Uses: MCP Sampling (LLM calls) + MCP Elicitation (approvals)   │
│  State: pydantic-graph state machine                             │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
      ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
      │Claude Desktop│ │   ChatGPT    │ │  Web UI      │
      │  (Phase 1)   │ │   (works)    │ │ (Phase 2)    │
      └──────────────┘ └──────────────┘ └──────────────┘
                                              │
                                              ▼
                                    ┌──────────────────┐
                                    │ Enhanced features│
                                    │ - Monaco editor  │
                                    │ - Progress bar   │
                                    │ - Diff view      │
                                    │ - Rule dashboard │
                                    └──────────────────┘
```

---

## Orchestration & Artifact Storage

### The Problem

Without orchestration, the flow is fragile:
- User can skip steps or execute out of order
- Artifacts (descriptions, rules, examples) get scattered
- No enforcement of prerequisites (e.g., schema descriptions before domain model)
- Progress lost on disconnect/crash

### Solution: pydantic-graph State Machine + Persistent Store

**db-meta-v2 orchestrates the flow** using pydantic-graph for state machine logic and a persistent store for artifacts.

```
┌─────────────────────────────────────────────────────────────────┐
│                        db-meta-v2                                │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              Onboarding Orchestrator                        │ │
│  │                  (pydantic-graph)                           │ │
│  │                                                             │ │
│  │   ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌─────┐ │ │
│  │   │ Init │───▶│Schema│───▶│Domain│───▶│Rules │───▶│Train│ │ │
│  │   └──────┘    └──────┘    └──────┘    └──────┘    └─────┘ │ │
│  │       │           │           │           │          │     │ │
│  │       ▼           ▼           ▼           ▼          ▼     │ │
│  │   ┌─────────────────────────────────────────────────────┐  │ │
│  │   │            Artifact Store (per provider)            │  │ │
│  │   │  - onboarding_state.yaml (current phase, progress)  │  │ │
│  │   │  - schema_descriptions.yaml                         │  │ │
│  │   │  - domain_model.md                                  │  │ │
│  │   │  - prompt_instructions.yaml                         │  │ │
│  │   │  - sql_dialect.yaml                                 │  │ │
│  │   │  - candidate_rules.yaml (pending approval)          │  │ │
│  │   └─────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    MCP Tools (exposed)                      │ │
│  │  - onboarding_status: get current state, next action       │ │
│  │  - onboarding_next: execute next step (or specific step)   │ │
│  │  - onboarding_approve: approve pending artifact            │ │
│  │  - onboarding_edit: modify artifact before approval        │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        Claude Desktop    ChatGPT        Web UI
```

### Orchestrator Design

The orchestrator enforces the flow and manages state:

```python
# db-meta-v2/onboarding/orchestrator.py
from pydantic_graph import Graph, Node, Edge, End
from pydantic import BaseModel
from enum import Enum

class OnboardingPhase(str, Enum):
    INIT = "init"
    SCHEMA = "schema"
    DOMAIN = "domain"
    BUSINESS_RULES = "business_rules"
    QUERY_TRAINING = "query_training"
    COMPLETE = "complete"

class OnboardingState(BaseModel):
    """Persisted state for onboarding flow."""
    provider_id: str
    phase: OnboardingPhase = OnboardingPhase.INIT
    
    # Phase 0: Init
    database_url_configured: bool = False
    connection_verified: bool = False
    dialect_detected: str | None = None
    schemas_discovered: list[str] = []
    tables_discovered: list[str] = []
    
    # Phase 1: Schema
    tables_total: int = 0
    tables_described: int = 0
    current_table: str | None = None
    pending_description: str | None = None  # awaiting approval
    
    # Phase 2: Domain
    domain_model_generated: bool = False
    domain_model_approved: bool = False
    pending_domain_model: str | None = None
    
    # Phase 3: Business Rules
    entities_total: int = 0
    entities_interviewed: int = 0
    rules_captured: int = 0
    current_entity: str | None = None
    pending_rules: list[dict] = []
    
    # Phase 4: Query Training
    examples_added: int = 0
    
    # Timestamps
    started_at: str | None = None
    last_updated_at: str | None = None


# Define graph nodes for each phase
class InitNode(Node[OnboardingState]):
    """Initialize connection and detect dialect."""
    
    async def run(self, state: OnboardingState, ctx: GraphContext) -> OnboardingState:
        # Test connection
        state.connection_verified = await test_db_connection(state.provider_id)
        
        # Detect dialect
        state.dialect_detected = await detect_sql_dialect(state.provider_id)
        await save_dialect_file(state.provider_id, state.dialect_detected)
        
        # Introspect schema
        tables = await introspect_tables(state.provider_id)
        state.tables_discovered = tables
        state.tables_total = len(tables)
        
        state.phase = OnboardingPhase.SCHEMA
        await persist_state(state)
        return state


class SchemaNode(Node[OnboardingState]):
    """Generate and approve schema descriptions."""
    
    async def run(self, state: OnboardingState, ctx: GraphContext) -> OnboardingState:
        # Find next undescribed table
        described = await get_described_tables(state.provider_id)
        remaining = [t for t in state.tables_discovered if t not in described]
        
        if not remaining:
            state.phase = OnboardingPhase.DOMAIN
            await persist_state(state)
            return state
        
        state.current_table = remaining[0]
        
        # Generate description via MCP sampling (uses client's LLM)
        description = await ctx.sample(
            f"Generate description for table {state.current_table}:\n"
            f"{await get_table_schema(state.current_table)}"
        )
        
        state.pending_description = description
        
        # Request approval via MCP elicitation
        approval = await ctx.elicit(
            ApprovalSchema,
            message=f"Approve description for {state.current_table}?\n\n{description}"
        )
        
        if approval.approved:
            await save_table_description(state.provider_id, state.current_table, description)
            state.tables_described += 1
            state.pending_description = None
        elif approval.edited:
            await save_table_description(state.provider_id, state.current_table, approval.edited_value)
            state.tables_described += 1
            state.pending_description = None
        # else: skipped, move to next
        
        state.current_table = None
        await persist_state(state)
        return state


# Build the graph
onboarding_graph = Graph(
    nodes=[InitNode, SchemaNode, DomainNode, BusinessRulesNode, QueryTrainingNode],
    edges=[
        Edge(InitNode, SchemaNode, condition=lambda s: s.connection_verified),
        Edge(SchemaNode, SchemaNode, condition=lambda s: s.tables_described < s.tables_total),
        Edge(SchemaNode, DomainNode, condition=lambda s: s.tables_described >= s.tables_total),
        Edge(DomainNode, BusinessRulesNode, condition=lambda s: s.domain_model_approved),
        Edge(BusinessRulesNode, QueryTrainingNode, condition=lambda s: s.entities_interviewed >= s.entities_total),
        Edge(QueryTrainingNode, End, condition=lambda s: False),  # Continuous
    ]
)
```

### MCP Tools (Thin Wrappers)

MCP tools are thin wrappers around the orchestrator:

```python
# db-meta-v2/tools/onboarding_tools.py
from fastmcp import FastMCP
from .orchestrator import onboarding_graph, OnboardingState, load_state, persist_state

server = FastMCP('db-meta-v2')

@server.tool()
async def onboarding_status(provider_id: str) -> dict:
    """Get current onboarding state and next recommended action."""
    state = await load_state(provider_id)
    if not state:
        return {
            "status": "not_started",
            "next_action": "Call onboarding_start to begin",
            "provider_id": provider_id
        }
    
    return {
        "status": state.phase.value,
        "progress": _calculate_progress(state),
        "current_step": _get_current_step(state),
        "next_action": _get_next_action(state),
        "artifacts": _list_artifacts(state)
    }


@server.tool()
async def onboarding_start(provider_id: str, database_url: str) -> dict:
    """Start onboarding flow for a new database provider."""
    state = OnboardingState(
        provider_id=provider_id,
        started_at=datetime.utcnow().isoformat()
    )
    
    # Configure database URL
    await save_database_config(provider_id, database_url)
    state.database_url_configured = True
    
    # Run init phase
    state = await onboarding_graph.run(state, start_node=InitNode)
    
    return {
        "status": "initialized",
        "dialect": state.dialect_detected,
        "tables_found": len(state.tables_discovered),
        "next_action": "Call onboarding_next to describe first table"
    }


@server.tool()
async def onboarding_next(provider_id: str) -> dict:
    """Execute next step in onboarding flow."""
    state = await load_state(provider_id)
    if not state:
        return {"error": "Onboarding not started. Call onboarding_start first."}
    
    # Run graph from current state - it will execute appropriate node
    state = await onboarding_graph.run(state)
    
    return {
        "status": state.phase.value,
        "progress": _calculate_progress(state),
        "action_taken": _describe_last_action(state),
        "pending_approval": state.pending_description or state.pending_domain_model,
        "next_action": _get_next_action(state)
    }


@server.tool()
async def onboarding_approve(
    provider_id: str, 
    approve: bool = True, 
    edited_value: str | None = None,
    feedback: str | None = None
) -> dict:
    """Approve or reject pending artifact (description, domain model, rule)."""
    state = await load_state(provider_id)
    
    # Handle based on what's pending
    if state.pending_description:
        if approve:
            await save_table_description(
                provider_id, 
                state.current_table, 
                edited_value or state.pending_description
            )
            state.tables_described += 1
        state.pending_description = None
        state.current_table = None
    
    elif state.pending_domain_model:
        if approve:
            await save_domain_model(
                provider_id,
                edited_value or state.pending_domain_model
            )
            state.domain_model_approved = True
        state.pending_domain_model = None
    
    await persist_state(state)
    
    return await onboarding_status(provider_id)


@server.tool()
async def onboarding_skip(provider_id: str) -> dict:
    """Skip current pending item and move to next."""
    state = await load_state(provider_id)
    state.pending_description = None
    state.pending_domain_model = None
    state.current_table = None
    await persist_state(state)
    
    return await onboarding_next(provider_id)
```

### Artifact Storage Structure

Artifacts stored per provider in db-meta-v2's resource directory:

```
packages/resources/dbmeta_app/providers/{provider_id}/
├── onboarding_state.yaml       # Current flow state (phase, progress)
├── database_config.yaml        # Connection details (encrypted)
├── sql_dialect.yaml            # Detected/configured dialect rules
├── schema_descriptions.yaml    # Table and column descriptions
├── domain_model.md             # Business domain documentation
├── prompt_instructions.yaml    # Business rules
├── candidate_rules.yaml        # Rules pending approval (from distillation)
└── query_examples/
    ├── index.yaml              # Example metadata
    └── embeddings/             # Milvus collection reference
```

### Flow Enforcement

The orchestrator **enforces prerequisites**:

```python
def _validate_phase_transition(current: OnboardingPhase, target: OnboardingPhase, state: OnboardingState) -> bool:
    """Ensure prerequisites are met before phase transition."""
    
    transitions = {
        (OnboardingPhase.INIT, OnboardingPhase.SCHEMA): lambda s: (
            s.connection_verified and s.dialect_detected
        ),
        (OnboardingPhase.SCHEMA, OnboardingPhase.DOMAIN): lambda s: (
            s.tables_described >= s.tables_total * 0.8  # At least 80% described
        ),
        (OnboardingPhase.DOMAIN, OnboardingPhase.BUSINESS_RULES): lambda s: (
            s.domain_model_approved
        ),
        (OnboardingPhase.BUSINESS_RULES, OnboardingPhase.QUERY_TRAINING): lambda s: (
            s.rules_captured >= 5  # Minimum rules before training
        ),
    }
    
    validator = transitions.get((current, target))
    return validator(state) if validator else False
```

### Resume After Disconnect

State is persisted after every action. On reconnect:

```
User: /onboarding_status provider_id=my_db

db-meta-v2: 
  Provider: my_db
  Phase: schema (2/5)
  Progress: 15 of 45 tables described (33%)
  Current: None pending
  
  Next action: Call /onboarding_next to describe table 'orders'
  
  Artifacts created:
  ✓ sql_dialect.yaml (Trino)
  ✓ schema_descriptions.yaml (15 tables)
  ○ domain_model.md (pending)
  ○ prompt_instructions.yaml (pending)
```

### Why This Works

1. **db-meta-v2 is the orchestrator** - not the client
2. **State machine enforces order** - can't skip to query training without descriptions
3. **Artifacts stored in canonical location** - ready for use by query generation
4. **Resumable** - persistent state survives disconnects
5. **Client-agnostic** - same flow works in Claude Desktop, ChatGPT, Web UI
6. **Temporal-ready** - state is serializable, can migrate to Temporal later

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agentic Chat Interface                       │
│              (MD/YAML display and editing support)               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Onboarding Flow Engine                        │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Init    │───▶│  Schema  │───▶│  Domain  │───▶│  Query   │  │
│  │  Phase   │    │  Phase   │    │  Model   │    │  Training│  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                                  │
│                    State Management (pausable/resumable)         │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     db-meta v2 MCP Server                        │
│                                                                  │
│  Tools: init, describe_schema, validate_sql, add_example, ...   │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │   Target Database │
                    └───────────────────┘
```

## Flow Phases

### Phase 0: Initialization & SQL Dialect Detection

**Trigger**: `init` tool invocation

**Steps**:
1. Check for `DATABASE_URL` environment variable
2. If not set, prompt admin for connection string
3. Test database connectivity
4. **Detect SQL dialect** (see below)
5. Introspect database to enumerate catalogs, schemas, tables
6. Create initial state file tracking progress

#### SQL Dialect Detection

The system automatically detects the SQL dialect from the connection and loads appropriate dialect-specific instructions.

**Detection Methods** (in order of precedence):

1. **Connection String Analysis**
   - Parse the driver/protocol from DATABASE_URL
   - Mappings:
     - `trino://` → Trino
     - `postgresql://` or `postgres://` → PostgreSQL
     - `clickhouse://` or `clickhouse+native://` → ClickHouse
     - `mysql://` → MySQL
     - `mssql://` or `sqlserver://` → SQL Server

2. **Server Query Verification** (if ambiguous)
   - Execute dialect-specific version query:
     - PostgreSQL: `SELECT version()` → looks for "PostgreSQL"
     - ClickHouse: `SELECT version()` → looks for numeric version pattern
     - Trino: `SELECT node_version FROM system.runtime.nodes LIMIT 1`
     - MySQL: `SELECT version()` → looks for "MySQL" or "MariaDB"

3. **Manual Override**
   - Admin can specify `--dialect=<name>` if auto-detection fails
   - Useful for custom/proxy setups

**Dialect Files**:

Pre-defined dialect instruction files are stored in:
```
packages/resources/dbmeta_app/sql-dialects/
├── trino.yaml
├── postgresql.yaml
├── clickhouse.yaml
├── mysql.yaml
└── common.yaml  # Shared rules
```

**Dialect File Structure** (reference: `packages/client-configs/wifiqm/prod/dbmeta_app/overlays/resources/sql_dialect.yaml`):
```yaml
version: 1.0.0
description: SQL dialect instructions for [Dialect Name]
profiles:
  default:
    - "Rule 1: Specific syntax requirement"
    - "Rule 2: Function differences from standard SQL"
    - |
      **Multi-line rule**: Detailed explanation
      with examples and code blocks
```

**Dialect-Specific Rules Include**:
- Type casting syntax differences
- Date/time function variations
- JSON extraction syntax
- Array handling
- String concatenation
- Aggregate function names
- Window function support
- Fully-qualified table name requirements
- Performance optimization patterns

**State Created**:
```yaml
# .onboarding/state.yaml
status: initialized
database_url_configured: true
connection_verified: true
started_at: "2025-01-05T10:00:00Z"
current_phase: schema_descriptions
sql_dialect:
  detected: trino
  detection_method: connection_string
  dialect_file: packages/resources/dbmeta_app/sql-dialects/trino.yaml
  custom_overrides: null  # or path to client-specific overlay
schemas_discovered:
  - name: public
    tables: 45
    status: pending
```

**Output**: Summary of discovered schemas and tables, detected dialect, ready for Phase 1

---

### Phase 1: Schema Descriptions

**Goal**: Create `schema_descriptions.yaml` with human-approved descriptions for all tables and columns

**Reference**: `packages/client-configs/wifiqm/prod/dbmeta_app/overlays/resources/schema_descriptions.yaml`

**Approach Options** (admin chooses):

#### Option A: Interactive Per-Table Review
- For each table:
  1. AI generates description based on table/column names and sample data
  2. Present to admin for approval/edit
  3. Move to next table
- Pros: High quality, immediate feedback
- Cons: Time-consuming for large schemas

#### Option B: Batch Draft + Review
- AI generates complete draft `schema_descriptions.yaml`
- Present entire file for admin review in editor
- Admin makes bulk edits
- Pros: Faster for experienced users
- Cons: May miss nuances

**AI Description Generation**:
- Analyze table name, column names, data types
- Sample N rows to understand data patterns
- Infer relationships from foreign keys
- Generate business-friendly descriptions

**Output Format**:
```yaml
# schema_descriptions.yaml
tables:
  - name: users
    description: "User accounts and profile information"
    columns:
      - name: id
        description: "Unique user identifier"
      - name: email
        description: "User's email address, used for login"
      - name: created_at
        description: "Timestamp when the user account was created"
  
  - name: orders
    description: "Customer purchase orders"
    columns:
      - name: id
        description: "Unique order identifier"
      - name: user_id
        description: "Reference to the user who placed the order"
      # ...
```

**State Update**:
```yaml
current_phase: schema_descriptions
schema_descriptions:
  total_tables: 45
  completed_tables: 12
  current_table: "orders"
  approach: "interactive"  # or "batch"
```

**Pause/Resume**: Admin can stop at any point; progress is saved per-table

---

### Phase 2: Domain Model

**Goal**: Create `domain_model.md` documenting the business domain and data relationships

**Reference**: `packages/client-configs/wifiqm/prod/dbmeta_app/overlays/resources/domain_model.md`

**Prerequisites**: Completed schema descriptions from Phase 1

**Steps**:
1. AI analyzes approved schema descriptions
2. Identifies key entities and relationships
3. Generates domain model document including:
   - Business domain overview
   - Key entities and their purposes
   - Relationships between entities
   - Common query patterns
   - Data freshness and update frequencies (if detectable)
4. Present to admin for review/edit
5. Admin approves or requests regeneration with feedback

**Output Format**:
```markdown
# Domain Model: [Database Name]

## Overview
[High-level description of what this database represents]

## Key Entities

### Users
Primary entity representing...

### Orders
Transactional entity capturing...

## Relationships
- Users → Orders (1:many): A user can place multiple orders
- Orders → Products (many:many): Orders contain multiple products

## Common Query Patterns
- User activity analysis: Join users with orders, aggregate by time
- Product performance: Join orders with products, aggregate sales

## Data Characteristics
- Primary time-series dimension: created_at columns
- Update frequency: Real-time for orders, daily for aggregates
```

**State Update**:
```yaml
current_phase: domain_model
domain_model:
  status: "review_pending"  # draft, review_pending, approved
  generated_at: "2025-01-05T11:00:00Z"
  revision: 1
```

---

### Phase 3: Business Rules & Prompt Instructions

**Goal**: Create `prompt_instructions.yaml` containing business rules, terminology, synonyms, lookup logic, and domain-specific guidance for accurate SQL generation.

**Reference**: `packages/client-configs/wifiqm/prod/dbmeta_app/overlays/resources/prompt_instructions.yaml`

**Prerequisites**: Completed schema descriptions and domain model

**Why This Phase Matters**:
- Technical schema alone is insufficient for accurate queries
- Business logic often contradicts intuitive assumptions
- Synonyms and jargon vary by organization
- Performance patterns are data-specific
- Lookup relationships aren't always in FK constraints

#### Rule Discovery Approaches

There are three complementary approaches to discovering business rules:

| Approach | Source | Best For | Automation Level |
|----------|--------|----------|------------------|
| **Manual Interview** | Domain expert | Initial onboarding, complex logic | Low |
| **Usage Pattern Mining** | Query logs + feedback | Ongoing refinement | High |
| **Hybrid** | Both | Comprehensive coverage | Medium |

---

#### Approach A: Automated Rule Distillation from Usage

**Concept**: Analyze the gap between user intent, generated SQL, and feedback to automatically discover implicit business rules.

**Data Sources**:
1. **User natural language input** - What they asked for
2. **Generated SQL** - What the system produced
3. **User feedback** - Corrections, regeneration requests, thumbs down
4. **Final accepted SQL** - What actually worked
5. **Admin fixes** - Manual SQL corrections in admin interface

**Distillation Pipeline**:

```
┌─────────────────────────────────────────────────────────────────┐
│                   Rule Distillation Pipeline                     │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Collect  │───▶│ Analyze  │───▶│ Propose  │───▶│ Validate │  │
│  │ Feedback │    │ Patterns │    │ Rules    │    │ & Store  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Step 1: Collect Feedback Signals**

```yaml
# Example feedback record
feedback_record:
  request_id: "abc123"
  user_input: "Show me traffic for TMO subscribers"
  generated_sql: |
    SELECT * FROM cdr_agg_day WHERE carrier = 'TMO'
  feedback_type: "correction"
  feedback_text: "TMO is stored as 'ameriband' in the carrier column"
  corrected_sql: |
    SELECT * FROM cdr_agg_day WHERE carrier = 'ameriband'
  accepted: true
```

**Step 2: AI Pattern Analysis**

Periodically (daily/weekly), run analysis on accumulated feedback:

```
Prompt to LLM:
"Analyze these feedback records and identify recurring patterns that could become business rules.

For each pattern found:
1. Describe the rule in plain English
2. Categorize it (synonym, business logic, table selection, etc.)
3. Provide confidence score based on frequency
4. Show supporting examples

Feedback records:
[batch of 50-100 records]
"
```

**Step 3: Propose Candidate Rules**

```yaml
# AI-generated candidate rules
candidate_rules:
  - rule: "TMO, T-Mobile, and macro network should map to carrier='ameriband'"
    category: terminology_synonym
    confidence: 0.92
    supporting_evidence:
      - count: 15
        pattern: "User said 'TMO', system used 'TMO', corrected to 'ameriband'"
    status: pending_review
    
  - rule: "When querying subscriber traffic, filter completed sessions only"
    category: implicit_filter
    confidence: 0.78
    supporting_evidence:
      - count: 8
        pattern: "Users added 'WHERE status = completed' in corrections"
    status: pending_review
```

**Step 4: Human Review & Approval**

Present candidate rules to admin for approval:

```
┌─────────────────────────────────────────────────────────────────┐
│ Candidate Rule Review                                            │
│                                                                  │
│ Rule: "TMO should map to carrier='ameriband'"                   │
│ Category: Terminology/Synonym                                    │
│ Confidence: 92%                                                  │
│ Evidence: 15 corrections over past 30 days                       │
│                                                                  │
│ Example corrections:                                             │
│ • "Show TMO traffic" → WHERE carrier='ameriband'                │
│ • "TMO subscriber count" → WHERE carrier='ameriband'            │
│                                                                  │
│ [Approve] [Edit] [Reject] [Need More Evidence]                  │
└─────────────────────────────────────────────────────────────────┘
```

**Feedback Loop Integration**:

```
User Query ──▶ SQL Generation ──▶ User Feedback
                    │                    │
                    │                    ▼
                    │            Feedback Store
                    │                    │
                    ▼                    ▼
            prompt_instructions ◀── Rule Distillation
                    │                (periodic)
                    │
                    ▼
            Improved SQL Generation
```

**Metrics to Track**:
- Rules discovered per week
- Rule approval rate (quality of AI proposals)
- Query accuracy improvement after rule adoption
- Time from pattern emergence to rule adoption

---

#### Approach B: Manual Interview (Initial Onboarding)

The manual approach is still valuable for initial setup when no usage data exists:

```
Agent: "I see you have a 'realm' column in cdr_agg_day. What does this represent?"
Admin: "It identifies which carrier/partner the subscriber belongs to. NULL means Helium Mobile."
Agent: "Are there common synonyms users might use when asking about carriers?"
Admin: "Yes - TMO, T-Mobile, macro network all mean the same thing..."
```

**Category-Based Elicitation**

Systematically cover these categories:

| Category | Description | Examples |
|----------|-------------|----------|
| **Terminology & Synonyms** | Alternative names for entities | "TMO = T-Mobile = macro network" |
| **Business Logic** | Rules that affect query construction | "Paid sub means plan NOT LIKE '%Zero%'" |
| **Implicit Filters** | Default conditions users expect | "When asking about network, exclude TMO by default" |
| **Aggregation Rules** | How to correctly aggregate data | "Subs count can't be summed across days" |
| **Table Selection** | Which table for which question | "For per-hotspot stats use cdr_agg_day, not hh_agg_day" |
| **Join Logic** | Non-obvious join patterns | "Join wifi_hotspots on agw_sn, bf_inventory on telco_id" |
| **Performance Hints** | Patterns to avoid/prefer | "Always filter subs CTE before joining cdr_agg_day" |
| **Output Formatting** | Presentation preferences | "Show traffic in GB/TB, not bytes" |
| **Data Freshness** | Time-based data characteristics | "Detailed RADIUS data only available for past 30 days" |

**Example-Driven Discovery**

For each major entity/table, ask:
- "What are the most common questions users ask about [X]?"
- "What mistakes do people commonly make when querying [X]?"
- "Are there any gotchas or non-obvious behaviors in [X]?"

**Validate Against Real Queries**

- Review historical queries (if available) for patterns
- Ask admin to provide 5-10 sample questions they'd expect users to ask
- Generate SQL for each, have admin validate and explain corrections

---

#### Approach C: Hybrid (Recommended)

Combine both approaches for comprehensive coverage:

**Phase 3a: Initial Onboarding (Manual)**
- Run structured interview for critical entities
- Capture known synonyms, business logic, gotchas
- Establish baseline `prompt_instructions.yaml`

**Phase 3b: Continuous Refinement (Automated)**
- Enable feedback collection from day one
- Run weekly distillation jobs
- Surface candidate rules to admin for review
- Automatically append approved rules to `prompt_instructions.yaml`

**Benefits of Hybrid**:
- Fast initial setup with expert knowledge
- Discovers unknown unknowns from real usage
- Self-improving system over time
- Captures edge cases manual interview would miss

#### Generation Flow

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│  │ Analyze │───▶│Interview│───▶│ Draft   │───▶│ Review  │  │
│  │ Schema  │    │ Admin   │    │ Rules   │    │ & Test  │  │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘  │
│       │              │              │              │        │
│       ▼              ▼              ▼              ▼        │
│   Identify       Capture        Generate      Validate     │
│   entities,      synonyms,      YAML with     rules with   │
│   patterns       rules,         categories    test queries │
│                  gotchas                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Steps**:

1. **Schema Analysis** (automated)
   - Identify key entities from schema descriptions
   - Detect potential synonym candidates (similar column names)
   - Find tables with similar purposes (potential selection rules needed)
   - Identify large tables (performance rules likely needed)

2. **Structured Interview** (interactive)
   - For each identified entity, ask targeted questions
   - Use category checklist to ensure coverage
   - Capture admin responses in structured format

3. **Draft Generation** (AI-assisted)
   - Generate `prompt_instructions.yaml` from interview data
   - Organize by category for maintainability
   - Include inline comments explaining each rule's purpose

4. **Validation** (interactive)
   - Present 5-10 test questions covering different rule categories
   - Generate SQL for each
   - Admin validates; misses reveal missing rules
   - Iterate until accuracy is acceptable

**Output Format**:
```yaml
# prompt_instructions.yaml
version: 1.0.0
description: "Business rules and prompt instructions for [Database Name]"
profiles:
  default:
    #────────────────────────────────────────────────────────
    # TERMINOLOGY & SYNONYMS
    #────────────────────────────────────────────────────────
    - "T-Mobile, TMO, Tmo, tmo, macro network are synonyms."
    - "Wi-Fi network, wifi network, Helium network are synonyms."
    - "HMH or hmh or greenfield hotspot is a Helium Mobile hotspot."
    
    #────────────────────────────────────────────────────────
    # BUSINESS LOGIC
    #────────────────────────────────────────────────────────
    - "Paid sub means 'plan_name' NOT LIKE '%Zero%'"
    - "Subscriber may have only one active subscription."
    - "Price for 1 GB rewarded data traffic is 0.5 USD"
    
    #────────────────────────────────────────────────────────
    # IMPLICIT FILTERS & DEFAULTS
    #────────────────────────────────────────────────────────
    - "When asked about network by default do not include TMO in queries."
    - "When asked about subscribers without specifying carrier, include all carriers."
    - "'realm' field NULL means Helium Mobile subscriber."
    
    #────────────────────────────────────────────────────────
    # TABLE SELECTION RULES
    #────────────────────────────────────────────────────────
    - "For history data use 'wifi_hotspots_history', for current state use 'wifi_hotspots'."
    - "For network-wide stats (DAU, traffic) use 'daily_stats_cdrs'."
    - "For per-hotspot or per-subscriber stats use 'cdr_agg_day'."
    - "For rewarded/unrewarded traffic breakdown use 'hh_agg_day'."
    
    #────────────────────────────────────────────────────────
    # JOIN & LOOKUP PATTERNS
    #────────────────────────────────────────────────────────
    - "Join wifi_hotspots (greenfield) with cdr_agg_day on agw_sn column."
    - "Join bf_inventory (brownfield) with cdr_agg_day on telco_id column."
    - "To get carrier name from realm, lookup in 'wifi_realms' table."
    - |
      For traffic per hotspot for all types, use:
      CASE
        WHEN c.agw_sn = 'brownfield' THEN TRIM(c.telco_id)
        ELSE TRIM(c.agw_sn)
      END AS hotspot_id
    
    #────────────────────────────────────────────────────────
    # AGGREGATION RULES
    #────────────────────────────────────────────────────────
    - "Subs count in daily_stats_cdrs cannot be summed across days - use for daily granularity only."
    - "For subs count over multiple days, use 'cdr_agg_day' table."
    - "Traffic, voice, and SMS values CAN be summed across days."
    
    #────────────────────────────────────────────────────────
    # PERFORMANCE PATTERNS
    #────────────────────────────────────────────────────────
    - |
      When querying subscriber-level usage from cdr_agg_day:
      1. Filter subscribers in subs into a small CTE first
      2. Aggregate cdr_agg_day by subscriber_id separately
      3. Join the aggregated CTE with filtered subs CTE
      NEVER join subs and cdr_agg_day directly.
    
    #────────────────────────────────────────────────────────
    # OUTPUT FORMATTING
    #────────────────────────────────────────────────────────
    - "When asked about data usage, return answers in GB or TB, never bytes."
    - "When converting bytes to TB use exact formula: 1TB = 1,099,511,627,776 bytes."
    - "Replace realm values with carrier names in results unless realms explicitly requested."
    
    #────────────────────────────────────────────────────────
    # DATA FRESHNESS & LIMITS
    #────────────────────────────────────────────────────────
    - "Detailed RADIUS data (iceberg.radius DB) available for past 30 days only."
    - "Always limit iceberg.radius queries to 3 days unless user specifies otherwise."
    - "When limiting results, inform user of the limit applied."
    
    #────────────────────────────────────────────────────────
    # CARRIER/PARTNER MAPPINGS
    #────────────────────────────────────────────────────────
    - |
      Carrier name to column value mappings:
      - 'Helium Mobile' → 'helium_mobile'
      - 'TMO' → 'ameriband'
      - 'ATT' → 'att'
      - 'Telefonica' → 'movistar'
      - 'Google' or 'Orion' → use both 'google' AND 'orion'
```

**Interview Question Templates**:

For each major entity discovered in schema:
```
1. "What is a [ENTITY] in your business context?"
2. "What other names might users use for [ENTITY]?"
3. "What are the most common questions about [ENTITY]?"
4. "What mistakes do people make when querying [ENTITY]?"
5. "Are there any implicit assumptions about [ENTITY]?"
6. "How should [ENTITY] data be aggregated?"
7. "Are there performance considerations for [ENTITY] queries?"
```

**State Update**:
```yaml
current_phase: business_rules
business_rules:
  status: "interview_in_progress"  # analyzing, interview_in_progress, draft, testing, approved
  entities_covered: 5
  entities_total: 12
  rules_captured: 23
  test_queries_validated: 3
  test_queries_total: 10
```

---

### Phase 4: Query Training (Interactive)

**Goal**: Build query examples through real usage and feedback

**Prerequisites**: Completed schema descriptions and domain model

**Mode**: Continuous interactive loop (no defined end)

**Flow**:
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│  │ Admin   │───▶│ db-meta │───▶│ Admin   │───▶│ Add to  │  │
│  │ Query   │    │ Gen SQL │    │ Feedback│    │ Examples│  │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘  │
│       ▲                              │                      │
│       └──────────────────────────────┘                      │
│              (iterate until satisfied)                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Steps per Query**:
1. Admin enters natural language query
2. db-meta generates SQL using schema descriptions + domain model
3. SQL is displayed to admin
4. Admin provides feedback:
   - **Approve**: SQL is correct, optionally add to examples
   - **Feedback**: Free-form text explaining what's wrong
   - **Skip**: Move on without saving
5. If feedback provided:
   - AI regenerates SQL incorporating feedback
   - Repeat from step 3
6. If approved with "add to examples":
   - Store in Milvus as query example
   - Example includes: natural language, SQL, and any relevant context

**Example Storage** (Milvus):
```json
{
  "id": "uuid",
  "natural_language": "Show me total sales by product category for last month",
  "sql": "SELECT category, SUM(amount) FROM orders JOIN products ON ... WHERE created_at > ...",
  "embedding": [0.1, 0.2, ...],
  "feedback_history": [
    {"feedback": "Include only completed orders", "iteration": 1}
  ],
  "created_at": "2025-01-05T12:00:00Z",
  "created_by": "admin@example.com"
}
```

**State Update**:
```yaml
current_phase: query_training
query_training:
  session_count: 5
  examples_added: 12
  last_session: "2025-01-05T12:00:00Z"
```

---

## MCP Tools

### Core Tools

| Tool | Description | Phase |
|------|-------------|-------|
| `init` | Start onboarding flow, check DATABASE_URL, detect dialect | 0 |
| `get_state` | Return current onboarding state | All |
| `set_database_url` | Configure database connection | 0 |
| `test_connection` | Verify database connectivity | 0 |
| `detect_dialect` | Auto-detect SQL dialect from connection | 0 |
| `set_dialect` | Manually override SQL dialect | 0 |
| `get_dialect_rules` | Return loaded dialect-specific rules | 0+ |

### Schema Phase Tools

| Tool | Description | Phase |
|------|-------------|-------|
| `list_schemas` | List all schemas/catalogs | 1 |
| `list_tables` | List tables in a schema | 1 |
| `describe_table` | Get columns and types for a table | 1 |
| `generate_description` | AI-generate description for table/column | 1 |
| `save_schema_descriptions` | Save approved descriptions to YAML | 1 |
| `load_schema_descriptions` | Load existing descriptions for editing | 1 |

### Domain Model Tools

| Tool | Description | Phase |
|------|-------------|-------|
| `generate_domain_model` | Generate domain model from schema | 2 |
| `save_domain_model` | Save approved domain model to MD | 2 |
| `load_domain_model` | Load existing domain model for editing | 2 |

### Business Rules Tools (Manual Interview)

| Tool | Description | Phase |
|------|-------------|-------|
| `analyze_schema_for_rules` | Identify entities needing business rules | 3 |
| `start_entity_interview` | Begin interview for specific entity | 3 |
| `capture_rule` | Record a business rule from interview | 3 |
| `generate_prompt_instructions` | Generate YAML from captured rules | 3 |
| `save_prompt_instructions` | Save approved rules to YAML | 3 |
| `load_prompt_instructions` | Load existing rules for editing | 3 |
| `test_rules_with_query` | Test a query to validate rules | 3 |
| `list_rule_categories` | Show coverage by rule category | 3 |

### Rule Distillation Tools (Automated)

| Tool | Description | Phase |
|------|-------------|-------|
| `collect_feedback_batch` | Gather recent feedback records for analysis | 3+ |
| `run_distillation` | Analyze feedback batch and propose candidate rules | 3+ |
| `list_candidate_rules` | Show pending candidate rules with confidence scores | 3+ |
| `review_candidate_rule` | Get details and evidence for a specific candidate | 3+ |
| `approve_rule` | Approve candidate rule and add to prompt_instructions | 3+ |
| `reject_rule` | Reject candidate rule with reason | 3+ |
| `get_distillation_metrics` | Show rule discovery stats and accuracy trends | 3+ |
| `configure_distillation` | Set schedule, thresholds, categories to watch | 3+ |

### Query Training Tools

| Tool | Description | Phase |
|------|-------------|-------|
| `generate_sql` | Generate SQL from natural language | 4 |
| `validate_sql` | Validate SQL syntax and explain plan | 4 |
| `execute_sql` | Execute SQL and return results (limited) | 4 |
| `add_query_example` | Add approved query to Milvus | 4 |
| `list_examples` | List stored query examples | 4 |

---

## State Management

### State File Location
```
.onboarding/
├── state.yaml           # Main state file
├── schema_descriptions.yaml  # Work in progress
├── domain_model.md      # Work in progress
└── sessions/
    ├── 2025-01-05-001.yaml  # Query training sessions
    └── 2025-01-05-002.yaml
```

### State Transitions
```
INITIALIZED ──▶ SCHEMA_IN_PROGRESS ──▶ SCHEMA_COMPLETE
                                              │
                                              ▼
              DOMAIN_COMPLETE ◀── DOMAIN_IN_PROGRESS
                    │
                    ▼
         BUSINESS_RULES_IN_PROGRESS ──▶ BUSINESS_RULES_COMPLETE
                                              │
                                              ▼
                                    QUERY_TRAINING (continuous)
                                              │
                                              ▼
                                    RULE_DISTILLATION (background, ongoing)
```

**Note**: Rule distillation runs as a background process once query training begins, continuously analyzing feedback and proposing new rules.

### Resume Behavior
- On `init` call, check for existing state
- If state exists, offer to resume or start fresh
- Resume picks up at exact point (e.g., specific table in schema phase)

---

## Chat Interface Requirements

### Display Capabilities
- Render Markdown documents inline
- Render YAML with syntax highlighting
- Show diffs when editing
- Display SQL with syntax highlighting

### Editing Capabilities
- Inline edit for small changes
- Full editor modal for large documents
- YAML validation before save
- Markdown preview

### Interaction Patterns
- Confirmation prompts for destructive actions
- Progress indicators for long operations
- Clear phase/step indicators
- Help command showing available actions

---

## Example Session

```
> init

Checking database configuration...
DATABASE_URL not found in environment.

Please provide your database connection string:
> postgresql://user:pass@localhost:5432/mydb

Testing connection... Success!
Connected to PostgreSQL 14.5

Discovered:
- 3 schemas
- 47 tables
- 312 columns

How would you like to proceed with schema descriptions?
1. Interactive (review each table individually)
2. Batch (generate all, review as a file)

> 1

Starting interactive schema description...

─────────────────────────────────────────
Table: public.users (1/47)
Columns: id, email, name, created_at, updated_at

AI-generated description:
"User accounts storing authentication and profile information"

Column descriptions:
- id: "Primary key, unique user identifier"
- email: "User's email address for authentication"
- name: "User's display name"
- created_at: "Account creation timestamp"
- updated_at: "Last profile update timestamp"

[Approve] [Edit] [Skip] [Pause]
> approve

Saved. Moving to next table...

─────────────────────────────────────────
Table: public.orders (2/47)
...

[After completing all tables]

Schema descriptions complete!
Saved to: schema_descriptions.yaml

Generating domain model...

─────────────────────────────────────────
# Domain Model: MyDB

## Overview
E-commerce platform database capturing user accounts,
product catalog, and order transactions...

[Full document displayed]

[Approve] [Edit] [Regenerate with feedback]
> approve

Domain model saved!

─────────────────────────────────────────
Entering Query Training mode.

You can now ask natural language questions about your data.
Good examples will help improve future query generation.

Type 'help' for commands, 'exit' to end session.

> Show me the top 10 customers by total order value

Generated SQL:
```sql
SELECT u.name, SUM(o.total) as total_value
FROM users u
JOIN orders o ON o.user_id = u.id
GROUP BY u.id, u.name
ORDER BY total_value DESC
LIMIT 10
```

[Approve] [Add to Examples] [Feedback] [Execute]
> feedback: should only include completed orders

Regenerating...

```sql
SELECT u.name, SUM(o.total) as total_value
FROM users u
JOIN orders o ON o.user_id = u.id
WHERE o.status = 'completed'
GROUP BY u.id, u.name
ORDER BY total_value DESC
LIMIT 10
```

[Approve] [Add to Examples] [Feedback] [Execute]
> add to examples

Added to query examples!

> exit

Session saved. 3 examples added.
You can resume anytime with 'init'.
```

---

## Implementation Roadmap

### Milestone 1: MCP Foundation (Claude Desktop MVP)

**Goal:** Complete onboarding flow working in Claude Desktop

- [ ] Scaffold onboarding tools in db-meta-v2 using FastMCP
- [ ] Implement state management with pydantic-graph
- [ ] `init` tool: connection, dialect detection, schema introspection
- [ ] `describe_table` tool: sampling for generation, elicitation for approval
- [ ] `generate_domain_model` tool: generate from approved descriptions
- [ ] `capture_rule` tool: interview-based rule capture
- [ ] State persistence (YAML files in `.onboarding/`)
- [ ] Test end-to-end with Claude Desktop

**Validation:** Admin can onboard a new database entirely through Claude Desktop chat.

### Milestone 2: Business Rules & Query Training

**Goal:** Complete rule capture and query example loop

- [ ] `analyze_schema_for_rules` tool: identify entities needing rules
- [ ] `start_entity_interview` tool: structured interview flow
- [ ] `test_rules_with_query` tool: validate rules against test queries
- [ ] `generate_sql` tool: SQL from natural language using schema + rules
- [ ] `add_query_example` tool: store validated examples in Milvus
- [ ] Feedback collection infrastructure

**Validation:** Generated SQL improves measurably after adding rules/examples.

### Milestone 3: Automated Rule Distillation

**Goal:** Self-improving rules from production usage

- [ ] Feedback record schema and storage
- [ ] `collect_feedback_batch` tool: gather recent feedback
- [ ] `run_distillation` tool: AI analysis of patterns
- [ ] `list_candidate_rules` / `approve_rule` / `reject_rule` tools
- [ ] Scheduled distillation job (daily/weekly)
- [ ] Metrics tracking (rules discovered, approval rate)

**Validation:** System proposes valid rules from real usage patterns.

### Milestone 4: Web UI Enhancements

**Goal:** Rich admin experience for onboarding

- [ ] Onboarding dashboard in fm-app-v2 / web
- [ ] AG-UI integration for state streaming
- [ ] Monaco editor for YAML/MD editing
- [ ] Progress visualization (phases, completion %)
- [ ] Diff view before saving changes
- [ ] Batch approval for descriptions/rules
- [ ] Rule candidate review dashboard

**Validation:** Admin prefers web UI over Claude Desktop for complex edits.

### Milestone 5: Production Hardening

**Goal:** Production-ready onboarding system

- [ ] Error handling and recovery for all tools
- [ ] Resume from any state after crash/disconnect
- [ ] Performance optimization for large schemas (100+ tables)
- [ ] Multi-tenant support (multiple databases in parallel)
- [ ] Audit logging for all onboarding actions
- [ ] pydantic-evals test suite for onboarding quality
- [ ] Documentation and admin guide

---

## Open Questions

1. **Multi-user support**: Should state be per-user or global?
2. **Version control**: Should schema_descriptions.yaml changes be git-tracked?
3. **Rollback**: How to handle mistakes in approved descriptions?
4. **Permissions**: Who can add query examples vs. just use them?
5. **Example quality**: Should there be a review process for examples?

---

## Success Metrics

- Time to complete initial onboarding (target: < 2 hours for 50-table DB)
- Schema description approval rate (target: > 80% first-try approval)
- Query example utility (target: examples improve SQL generation accuracy)
- User satisfaction with flow (target: NPS > 40)
