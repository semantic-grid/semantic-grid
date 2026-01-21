# Metrics Layer Plan

## Overview

A semantic metrics layer for DB-Meta v2 MCP server that enables natural language queries over business metrics with composability, portability, and versioning. Standard agents (Claude Desktop, etc.) can query metrics like "DAU" or "retention rate" and get consistent, auditable SQL.

## Context: DB-Meta v2 Architecture

DB-Meta v2 is an MCP server designed for standard agents (Claude Desktop, Cursor, etc.):

**Claude Desktop / MCP Client**
↓ *MCP Protocol (stdio/http)*

**DB-Meta v2 MCP Server**
- **Tools:** shell, run_sql, validate_sql, get_result, list_tables, describe_table, mcp_setup_*, mcp_metrics_* (NEW)
- **Resources:** dbmeta://ground-rules, dbmeta://sql-rules, dbmeta://metrics (NEW)
- **Connection Vault:** `~/.dbmeta/connections/{name}/`
  - PROTOCOL.md
  - schema/descriptions.yaml
  - examples/*.yaml
  - instructions/sql_rules.md
  - domain/model.md
  - **metrics/** (NEW)

↓

**Database** (Trino, ClickHouse, PostgreSQL)

Key insight: The agent (Claude) does the reasoning. DB-Meta provides tools and knowledge. Metrics fit naturally as another knowledge layer in the connection vault.

## Why a Metrics Layer?

### Current Problem

User asks Claude Desktop: *"What's our DAU?"*

Without metrics:
1. Claude reads `schema/descriptions.yaml` via shell
2. Infers what "DAU" might mean from column descriptions
3. Generates SQL based on its interpretation
4. Different sessions may compute it differently

With metrics:
1. Claude reads `metrics/catalog.yaml` via shell
2. Finds canonical "DAU" definition with exact SQL
3. Uses or adapts the definition
4. Results are reproducible across sessions

### Goals

1. **Consistency**: Same question → same SQL → same answer
2. **Composability**: Metrics can reference other metrics
3. **Portability**: Metrics work across databases and agents
4. **Discoverability**: Agents and humans can browse metrics
5. **Versioning**: Git-based tracking of definition changes
6. **Zero infrastructure**: Just files in the vault, no new services

---

## Metric Definition Format

### Prescriptive vs. Descriptive: The Trade-off

| Approach | Definition | When LLM Uses It |
|----------|------------|------------------|
| **Prescriptive** | Exact SQL template | Substitute parameters, execute directly |
| **Descriptive** | Semantic guidance | Interpret and generate SQL |
| **Hybrid** | Both | Try prescriptive first, fall back to descriptive |

### Industry Approaches

| Tool | Approach | Pros | Cons |
|------|----------|------|------|
| **Looker/LookML** | Prescriptive | Guaranteed consistency | Rigid, template explosion |
| **dbt Metrics** | Prescriptive | Versioned, testable | Deprecated, less flexible |
| **Cube.dev** | Prescriptive | Pre-aggregation, fast | Infrastructure overhead |
| **RAG/Text-to-SQL** | Descriptive | Flexible, natural | Inconsistent, harder to audit |

### Recommendation: Hybrid for DB-Meta v2

Since DB-Meta works with LLM agents, we leverage both prescriptive and descriptive:

```yaml
# Example metric definition
metrics:
  - name: daily_active_users
    display_name: "Daily Active Users (DAU)"
    description: "Unique users with at least one transaction per day"
    category: engagement
    
    # PRESCRIPTIVE: Exact SQL for common case
    canonical:
      sql: |
        SELECT 
          DATE_TRUNC('day', timestamp) AS date,
          COUNT(DISTINCT user_id) AS dau
        FROM {table}
        WHERE timestamp >= {start_date} 
          AND timestamp < {end_date}
        GROUP BY 1
        ORDER BY 1
      parameters:
        - name: table
          default: transactions
        - name: start_date
          type: date
          required: true
        - name: end_date
          type: date
          required: true
    
    # DESCRIPTIVE: Guidance for novel queries
    semantic:
      base_table: transactions
      entity_field: user_id
      time_field: timestamp
      aggregation: count_distinct
      grain: day
      dimensions:
        - chain
        - protocol
      gotchas:
        - "Use timestamp, not block_time"
        - "Don't double-count cross-chain users unless asked"
```

**How Claude uses this:**

1. **Pure metric query** ("What's our DAU for last week?")
   - Claude finds `daily_active_users` in metrics
   - Substitutes parameters into `canonical.sql`
   - Runs via `run_sql`

2. **Modified query** ("DAU by chain for Ethereum users only")
   - Claude reads `semantic` section
   - Understands DAU = `COUNT(DISTINCT user_id)` on `transactions`
   - Adds `chain` dimension and `WHERE chain = 'ethereum'`
   - Generates adapted SQL

3. **Novel query** ("DAU but only counting users with >$100 volume")
   - Claude uses `semantic` as starting point
   - Adds custom filter based on understanding
   - Flags that this is a non-standard DAU variant

---

## Composability

Compound questions are where metrics shine:

- *"What's our 7-day retention?"* → DAU day 7 / DAU day 0
- *"Revenue per active user?"* → Revenue / DAU
- *"Week-over-week DAU growth?"* → (DAU this week - DAU last week) / DAU last week

### Composition Types

```yaml
metrics:
  # Ratio metric
  - name: revenue_per_active_user
    type: ratio
    numerator: total_revenue
    denominator: daily_active_users
    description: "Average revenue per active user"
    
  # Time-shifted metric  
  - name: retention_rate_7d
    type: ratio
    numerator: daily_active_users
    denominator:
      metric: daily_active_users
      time_shift: -7d
    description: "% of users still active after 7 days"
    
  # Derived (formula)
  - name: net_revenue
    type: derived
    formula: "gross_revenue - refunds - fees"
    description: "Revenue after refunds and fees"
    
  # Period-over-period
  - name: dau_wow_growth
    type: growth
    base_metric: daily_active_users
    period: week
    description: "Week-over-week DAU growth rate"
```

### How Composition Works

When Claude sees "What's our 7-day retention?":

1. Finds `retention_rate_7d` in metrics catalog
2. Sees it's a ratio of `daily_active_users` / `daily_active_users (shifted -7d)`
3. Generates SQL with CTEs:

```sql
WITH dau_current AS (
  SELECT date, COUNT(DISTINCT user_id) AS users
  FROM transactions
  WHERE date = '2025-01-19'
  GROUP BY 1
),
dau_7d_ago AS (
  SELECT date + INTERVAL '7 days' AS date, COUNT(DISTINCT user_id) AS users
  FROM transactions  
  WHERE date = '2025-01-12'
  GROUP BY 1
)
SELECT 
  c.date,
  c.users AS current_dau,
  p.users AS dau_7d_ago,
  ROUND(100.0 * c.users / NULLIF(p.users, 0), 2) AS retention_pct
FROM dau_current c
LEFT JOIN dau_7d_ago p ON c.date = p.date
```

---

## Portability

### Why Portability Matters

Same metrics should work:
- Across databases (Trino prod, ClickHouse dev, PostgreSQL local)
- Across agents (Claude Desktop, Cursor, custom MCP clients)
- Across environments (dev/staging/prod)

### Two-Layer Design

**Logical Layer (Portable)** — `metrics/portable/core.yaml`
- Entity: user
- Event: transaction
- Aggregation: count_distinct
- Grain: day

↓ *resolved at runtime*

**Physical Layer (DB-Specific)** — `metrics/bindings.yaml`
- table: iceberg.prod.transactions
- user_field: wallet_address
- time_field: block_timestamp
- sql_dialect: trino

### Portable Metric Format

```yaml
# metrics/portable/core.yaml
# This file can be copied between connections

version: "1.0"
dialect: portable

entities:
  user:
    description: "Unique actor (wallet, account, etc.)"
  transaction:
    description: "On-chain transaction event"

metrics:
  - name: daily_active_users
    entity: user
    event: transaction
    aggregation: count_distinct
    grain: day
    description: "Unique users with activity per day"
```

```yaml
# metrics/bindings.yaml
# Connection-specific bindings

bindings:
  daily_active_users:
    table: iceberg.analytics.transactions
    entity_field: user_address
    time_field: block_timestamp
    dialect_sql: |
      SELECT 
        DATE_TRUNC('day', block_timestamp) AS date,
        COUNT(DISTINCT user_address) AS dau
      FROM iceberg.analytics.transactions
      WHERE block_timestamp >= TIMESTAMP '{start_date}'
      GROUP BY 1
```

### Sharing Metrics Between Connections

```bash
# Export portable metrics from one connection
cp ~/.dbmeta/connections/prod/metrics/portable/* /tmp/metrics/

# Import to another connection  
cp /tmp/metrics/* ~/.dbmeta/connections/dev/metrics/portable/

# Or use git for the whole vault
cd ~/.dbmeta/connections/prod
git init && git add metrics/ && git commit -m "metrics"
git remote add origin git@github.com:org/metrics.git && git push
```

---

## Versioning

### Git-Based Approach

Metrics live in the connection vault, which can be git-versioned:

```yaml
# metrics/manifest.yaml
version: "1.2.0"
updated: 2025-01-19
owner: data-team

changelog:
  - version: "1.2.0"
    date: 2025-01-19
    changes:
      - "Added retention_rate_7d metric"
      - "Fixed DAU to exclude bot addresses"
  - version: "1.1.0"
    date: 2025-01-10
    changes:
      - "Added revenue_per_user metric"
```

### Version in Query Response

When Claude uses metrics, include lineage:

```
I calculated DAU using the `daily_active_users` metric (v1.2.0).

| Date       | DAU    |
|------------|--------|
| 2025-01-19 | 15,234 |
| 2025-01-18 | 14,891 |

Metric definition: COUNT(DISTINCT user_id) from transactions, grouped by day.
```

---

## File Structure

Canonical directory structure for metrics in the connection vault:

```
~/.dbmeta/connections/{name}/
├── PROTOCOL.md                    # Ground rules (updated with metrics section)
├── schema/
│   └── descriptions.yaml
├── examples/
│   └── *.yaml
├── instructions/
│   └── sql_rules.md
├── domain/
│   └── model.md
└── metrics/                       # NEW - Metrics layer
    ├── manifest.yaml              # Version, catalog metadata
    ├── catalog.yaml               # Approved, stable metrics (engagement, revenue, etc.)
    ├── discovered.yaml            # Distilled from queries, pending review
    ├── derived.yaml               # Composed metrics (ratios, growth, etc.)
    ├── bindings.yaml              # Connection-specific SQL overrides
    └── portable/                  # DB-agnostic definitions (for sharing)
        └── core.yaml
```

**File purposes:**
- `manifest.yaml` - Version info, changelog, ownership
- `catalog.yaml` - Primary metrics catalog (approved, stable)
- `discovered.yaml` - Metrics distilled from queries (staging area)
- `derived.yaml` - Composed/calculated metrics
- `bindings.yaml` - SQL overrides for this specific database
- `portable/` - Shareable definitions without connection-specific bindings

---

## Metric Capture Workflows

Three workflows for creating metrics, used at different stages:

### Workflow A: Onboarding-Time Capture

**When**: During initial `mcp_setup_*` / `mcp_domain_*` flow

**How it works**:
1. After schema discovery, agent analyzes tables for metric patterns
2. Agent proposes metrics based on common patterns:
   - Tables with `user_id` + `timestamp` → DAU/MAU candidates
   - Tables with `amount`/`value` columns → Revenue candidates
   - Event tables with status fields → Funnel candidates
3. User approves/edits proposed metrics
4. Metrics saved to `metrics/catalog.yaml`

**Pros**: Metrics defined upfront, consistent from day one  
**Cons**: User may not know what metrics they need yet

### Workflow B: Distillation During Normal Operation

**When**: Continuously, as agent handles queries

**How it works**:
1. Agent answers business question with SQL
2. Agent recognizes this could be a reusable metric
3. Agent proposes: "This looks like a metric. Save as 'daily_active_users'?"
4. If user approves, metric saved to `metrics/discovered.yaml`

**Example conversation**:
```
User: "How many unique users transacted yesterday?"

Claude: Here's yesterday's unique user count:
| date       | users  |
|------------|--------|
| 2025-01-20 | 12,453 |

💡 This looks like a reusable metric. Would you like me to save it as 
"daily_active_users" for consistent future queries?
```

**Pros**: Metrics emerge from real usage, zero upfront effort  
**Cons**: Inconsistent until metric is captured

### Workflow C: Dedicated Metrics Analyst Session

**When**: Explicit metrics definition session

**How it works**:
1. User invokes: "Let's define our business metrics"
2. Agent conducts structured interview:
   - What does "active user" mean to you?
   - How do you calculate revenue?
   - What time granularity matters?
3. Agent generates metric definitions
4. User reviews and approves → saved to `metrics/catalog.yaml`

**Alternative**: Import from existing definitions (dbt, Looker, Cube, etc.)

**Pros**: Comprehensive, well-thought-out metrics  
**Cons**: Requires dedicated time

### Recommended: Hybrid Lifecycle

**ONBOARDING** → **NORMAL OPERATION** → **REVIEW**

| Phase | Action | Output |
|-------|--------|--------|
| Onboarding | Auto-propose metrics from schema patterns | → `catalog.yaml` (approved) |
| Normal Operation | Distill metrics from queries ("Save this as a metric?") | → `discovered.yaml` (staging) |
| Review | Analyst session to promote/clean up | discovered → `catalog.yaml` (promoted) |

---

## Ensuring Agent Awareness

How do we make sure Claude actually uses the metrics?

### Multi-Layer Awareness Stack

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| 1. Server instructions | MCP server `instructions` field | First thing agent sees on connect |
| 2. PROTOCOL.md | Ground rules in vault | Detailed workflow instructions |
| 3. MCP Resource | `dbmeta://metrics` | Quick catalog lookup |
| 4. Validation hook | `run_sql` response | Catch misses, suggest metrics |
| 5. Distillation | Post-query prompt | Grow catalog from usage |

### Layer 1: Server Instructions

```python
INSTRUCTIONS = """
Database metadata and query intelligence server.

## BEFORE ANY QUERY WORK

1. Read the protocol: `shell(command="cat PROTOCOL.md")`

2. **CHECK METRICS FIRST** for business questions:
   `shell(command="cat metrics/catalog.yaml")`
   
   If asking about users, revenue, retention, growth - a metric likely exists.
   Use the metric definition, don't reinvent the SQL.

3. Check SQL rules: `shell(command="cat instructions/sql_rules.md")`
"""
```

### Layer 2: PROTOCOL.md Updates

Add to the agent's ground rules:

```markdown
## Metrics Catalog

Business metrics are defined in `metrics/`. Before writing SQL for common 
business questions, you MUST check if a metric exists.

### Quick Reference
```bash
cat metrics/catalog.yaml           # View all approved metrics
cat metrics/discovered.yaml        # View metrics pending review
grep -ri "revenue" metrics/        # Search for specific metrics
```

### Using Metrics

1. **Standard query**: Use `canonical.sql`, substitute parameters
2. **With filters/dimensions**: Adapt based on `semantic` section
3. **Composed metrics**: Follow composition rules in `derived.yaml`

### When to Use Metrics vs Raw SQL

| Question Type | Use Metrics? | Example |
|--------------|--------------|---------|
| Business KPI | YES | "What's our DAU?" |
| Exploratory | NO | "Show me the users table" |
| Metric variant | ADAPT | "DAU for Ethereum only" |
| Novel analysis | NO, but DISTILL | "Users with >$100 volume" |

### Distillation Rule

After answering a business question, consider if it should be a metric:
- Aggregations over time → metric candidate
- Entity counts → metric candidate  
- Ratios/rates → metric candidate

If yes, offer to save to `metrics/discovered.yaml`.

### Attribution

Always tell the user which metric you used and its version:
"Calculated using `daily_active_users` metric (v1.2.0)"
```

### Layer 3: MCP Resource

```python
@server.resource("dbmeta://metrics")
def get_metrics() -> str:
    """Business metrics catalog - CHECK THIS for any business question.
    
    Returns summary of all defined metrics with names and descriptions.
    Use `cat metrics/<file>.yaml` for full definitions.
    """
    metrics_dir = get_connection_path() / "metrics"
    
    summary = ["# Available Metrics\n"]
    
    for yaml_file in ["catalog.yaml", "derived.yaml", "discovered.yaml"]:
        path = metrics_dir / yaml_file
        if path.exists():
            data = yaml.safe_load(path.read_text())
            section = yaml_file.replace(".yaml", "").title()
            summary.append(f"## {section}\n")
            for metric in data.get("metrics", []):
                summary.append(f"- **{metric['name']}**: {metric['description']}")
            summary.append("")
    
    return "\n".join(summary)
```

### Layer 4: Validation Hook

```python
@server.tool(name="run_sql")
async def _run_sql(sql: str, ...) -> dict:
    # ... existing validation ...
    
    # Check if query matches a known metric pattern
    metric_match = check_metric_patterns(sql)
    if metric_match:
        result["metric_note"] = (
            f"ℹ️ This query resembles the '{metric_match.name}' metric. "
            f"Consider using the canonical definition for consistency."
        )
    
    return result
```

### Query Workflow (All Layers Combined)

**Example:** User asks *"What's our DAU for last week?"*

1. **CLASSIFY** — Is this a business metric question?
   - Keywords detected: DAU, users → Yes

2. **CHECK METRICS** — Search catalog
   - `cat metrics/catalog.yaml` or read `dbmeta://metrics`
   - Found: `daily_active_users`

3. **LOAD & USE** — Extract and adapt
   - Get canonical SQL from metric definition
   - Substitute `{start_date}`, `{end_date}` from user's "last week"

4. **EXECUTE & ATTRIBUTE** — Run and report
   - Execute via `run_sql`
   - Response includes: *"Calculated using `daily_active_users` metric (v1.2.0)"*

---

## MCP Tools

All metric-related MCP tools in one place:

### Discovery Tools

```python
@server.tool(name="list_metrics")
async def _list_metrics(category: str | None = None) -> dict:
    """List available business metrics.
    
    Args:
        category: Filter by category (engagement, revenue, etc.)
    
    Returns:
        List of metrics with names and descriptions
    """

@server.tool(name="get_metric")
async def _get_metric(
    name: str,
    dimensions: list[str] | None = None,
    filters: dict | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Get SQL for a business metric with parameters filled in.
    
    Args:
        name: Metric name (e.g., "daily_active_users")
        dimensions: Optional grouping dimensions
        filters: Optional dimension filters  
        start_date: Start of time range
        end_date: End of time range
    
    Returns:
        SQL query and metric metadata
    """
```

### Capture Tools (Onboarding)

```python
@server.tool(name="mcp_metrics_propose")
async def _metrics_propose() -> dict:
    """Analyze schema and propose business metrics.
    
    Examines discovered tables for common metric patterns:
    - User activity → DAU, MAU, retention
    - Transaction amounts → Revenue, ARPU
    - Event sequences → Conversion funnels
    
    Returns proposed metrics for user approval.
    """

@server.tool(name="mcp_metrics_approve")
async def _metrics_approve(metrics: list[str]) -> dict:
    """Approve proposed metrics and save to catalog.yaml."""

@server.tool(name="mcp_metrics_edit")  
async def _metrics_edit(name: str, definition: dict) -> dict:
    """Edit a metric definition."""
```

### Import Tools

```python
@server.tool(name="mcp_metrics_import")
async def _metrics_import(
    source: str,  # "dbt", "looker", "cube", "yaml", "sql"
    path_or_url: str,
) -> dict:
    """Import metrics from external sources.
    
    Supported formats:
    - dbt: metrics.yml or semantic_models.yml
    - looker: LookML model files
    - cube: Cube.js schema files
    - yaml: Our portable metric format
    - sql: Directory of .sql files with metric queries
    """
```

---

## Implementation Phases

### Phase 1: Foundation (MVP)

**Goal**: Metrics as documentation that Claude reads via shell

**Tasks**:
1. Define YAML schema for metrics
2. Create `metrics/` directory structure in vault
3. Add 5-10 core metrics manually (DAU, MAU, revenue)
4. Update PROTOCOL.md with metrics section
5. Add `dbmeta://metrics` resource
6. Test Claude using metrics via shell commands

**Validation**: Claude consistently uses metric definitions when asked about DAU.

### Phase 2: MCP Tools + Awareness

**Goal**: Dedicated tools and robust awareness

**Tasks**:
1. Add `list_metrics`, `get_metric` tools
2. Update server instructions  
3. Add validation hook to `run_sql`
4. Test multi-layer awareness

### Phase 3: Capture Workflows

**Goal**: Automated metric discovery and distillation

**Tasks**:
1. Add `mcp_metrics_propose` for onboarding
2. Add distillation prompts to PROTOCOL.md
3. Add `mcp_metrics_approve`, `mcp_metrics_edit`
4. Implement `discovered.yaml` → `catalog.yaml` promotion

### Phase 4: Composition

**Goal**: Support derived metrics (ratios, growth, time-shifted)

**Tasks**:
1. Implement composition types in YAML schema
2. Add composition resolver
3. Create derived metrics (retention, growth, ARPU)
4. Document composition rules

### Phase 5: Portability

**Goal**: Share metrics across connections

**Tasks**:
1. Implement logical/physical layer separation
2. Add bindings resolution
3. Add `mcp_metrics_import` tool
4. Test cross-connection sharing

---

## Open Questions

1. **Metric Discovery UX**: How should Claude present available metrics?
   - List in initial context? (uses tokens)
   - Agent searches on demand? (current approach)
   - Always read `dbmeta://metrics` resource first?

2. **Metric Conflicts**: What if schema changes break metrics?
   - Validation on schema update
   - Metric health checks
   - Deprecation workflow

3. **Multi-Connection Metrics**: Same metric, different connections?
   - Portable definitions with bindings (proposed)
   - Fully independent per connection
   - Central metrics registry

4. **Discovered → Approved Lifecycle**: How to promote `discovered.yaml`?
   - Auto-promote after N uses?
   - Require explicit approval?
   - Periodic cleanup prompts?

---

## Success Criteria

1. **Consistency**: Same metric query → identical SQL 95%+ of time
2. **Adoption**: Claude references metrics in 50%+ of business queries
3. **Discoverability**: Users can ask "what metrics are available?"
4. **Portability**: Core metrics work on Trino and ClickHouse
5. **Zero friction**: Works with existing shell-based workflow

---

## Comparative Analysis: DB-Meta vs MetricFlow vs Cube.dev

### Architecture Comparison

| Aspect | DB-Meta v2 | dbt MetricFlow | Cube.dev |
|--------|------------|----------------|----------|
| **Deployment** | Files in vault, no server | Python package + dbt Cloud/Core | Dedicated API server |
| **Infrastructure** | Zero (just YAML files) | dbt project required | Cube server + optional Redis |
| **Query interface** | LLM agent (Claude, etc.) | SQL via dbt proxy, Semantic Layer API | REST API, GraphQL, SQL API |
| **Caching** | None (relies on DB) | None (pushdown to warehouse) | Built-in pre-aggregations |
| **Target users** | Analysts via natural language | Analytics engineers | Developers building apps |

### Definition Format: Same Metric, Three Systems

**DAU (Daily Active Users) in each format:**

**DB-Meta v2:**
```yaml
metrics:
  - name: daily_active_users
    description: "Unique users with at least one transaction per day"
    canonical:
      sql: |
        SELECT DATE_TRUNC('day', timestamp) AS date,
               COUNT(DISTINCT user_id) AS dau
        FROM {table}
        WHERE timestamp >= {start_date} AND timestamp < {end_date}
        GROUP BY 1
    semantic:
      base_table: transactions
      entity_field: user_id
      time_field: timestamp
      aggregation: count_distinct
      grain: day
```

**dbt MetricFlow:**
```yaml
semantic_models:
  - name: transactions
    defaults:
      agg_time_dimension: transaction_date
    entities:
      - name: user
        type: foreign
        expr: user_id
      - name: transaction
        type: primary
        expr: transaction_id
    measures:
      - name: users
        agg: count_distinct
        expr: user_id
    dimensions:
      - name: transaction_date
        type: time
        type_params:
          time_granularity: day
        expr: timestamp

metrics:
  - name: daily_active_users
    description: "Unique users with at least one transaction per day"
    type: simple
    type_params:
      measure: users
```

**Cube.dev:**
```javascript
cube(`Transactions`, {
  sql: `SELECT * FROM transactions`,
  
  measures: {
    dau: {
      type: `countDistinct`,
      sql: `user_id`,
      title: `Daily Active Users`
    }
  },
  
  dimensions: {
    timestamp: {
      type: `time`,
      sql: `timestamp`
    },
    userId: {
      type: `string`,
      sql: `user_id`
    }
  }
});
```

### Query Flow Comparison

**User asks: "What's our DAU for the last 7 days?"**

**DB-Meta v2:**
1. User → Claude Desktop → "What's our DAU for the last 7 days?"
2. Claude reads `metrics/catalog.yaml` via shell
3. Claude finds `daily_active_users`, extracts canonical SQL
4. Claude substitutes date parameters, calls `run_sql`
5. DB-Meta validates and executes against warehouse
6. Results returned with metric attribution

**dbt MetricFlow:**
1. User/App → Semantic Layer API or `mf query`
2. Request: `mf query --metrics daily_active_users --group-by metric_time__day --where "metric_time >= '2025-01-14'"`
3. MetricFlow compiles to SQL using semantic model
4. SQL pushed to warehouse (Snowflake, BigQuery, etc.)
5. Results returned via API

**Cube.dev:**
1. User/App → Cube API (REST/GraphQL)
2. Request: `{ "measures": ["Transactions.dau"], "timeDimensions": [{"dimension": "Transactions.timestamp", "granularity": "day", "dateRange": "last 7 days"}] }`
3. Cube checks pre-aggregation cache
4. If miss, generates SQL and queries warehouse
5. Results cached and returned

### Feature Comparison

| Feature | DB-Meta v2 | MetricFlow | Cube.dev |
|---------|------------|------------|----------|
| **Natural language queries** | Native (LLM-powered) | No (API/SQL only) | No (API only) |
| **Metric composition** | Yes (ratios, derived) | Yes (derived metrics) | Yes (calculated measures) |
| **Time-shifted metrics** | Yes | Yes (offset windows) | Yes (rolling windows) |
| **Pre-aggregations/caching** | No | No | Yes (primary feature) |
| **Multi-database** | Yes (via bindings) | Limited (dbt adapters) | Yes (many drivers) |
| **Access control** | No | Via dbt Cloud | Yes (row-level security) |
| **Version control** | Git (files in vault) | Git (dbt project) | Git (schema files) |
| **Real-time metrics** | Yes (direct queries) | Yes (pushdown) | Configurable refresh |
| **Self-service exploration** | Via LLM conversation | Via BI tools | Via Playground UI |
| **Governance/lineage** | Basic (metric version) | dbt lineage | Cube lineage |

### Trade-offs Analysis

**When to use DB-Meta v2:**
- Natural language is the primary interface
- Zero infrastructure appetite
- Metrics evolve through usage (distillation)
- LLM agent already in workflow
- Database can handle direct queries (no caching needed)

**When to use MetricFlow:**
- Already using dbt for transformations
- Need tight integration with dbt models/tests
- Team prefers SQL/API over natural language
- Snowflake/BigQuery/Databricks warehouse
- Want dbt Cloud governance features

**When to use Cube.dev:**
- Building an application with embedded analytics
- Need sub-second response times (pre-aggregations)
- High query volume requires caching
- Need row-level security
- Want GraphQL/REST API for frontend

### What We Gain vs Existing Solutions

**Advantages of DB-Meta approach:**

1. **LLM-native** — Designed for agent-driven queries, not API calls
2. **Zero infrastructure** — Just YAML files, no servers to run
3. **Adaptive** — Hybrid prescriptive/descriptive handles novel queries
4. **Distillation** — Metrics emerge from actual usage patterns
5. **Simple portability** — Copy files between connections

**What we give up:**

1. **No caching** — Every query hits the warehouse
2. **No pre-aggregations** — Can't pre-compute for speed
3. **No access control** — Relies on database-level permissions
4. **No API** — Only accessible through MCP/agent interface
5. **Less governance** — No built-in approval workflows

### Integration Possibilities

**Importing from other systems:**

| Source | Import Method | Complexity |
|--------|---------------|------------|
| MetricFlow | Parse `semantic_models.yml`, extract measures → metrics | Medium |
| Cube.dev | Parse JS schema, extract measures/dimensions | Medium |
| LookML | Parse `.lkml` files, extract measures | High (complex format) |
| SQL files | Parse SQL, extract aggregation patterns | Low |

**Exporting to other systems:**

| Target | Export Method | Use Case |
|--------|---------------|----------|
| MetricFlow | Generate `semantic_models.yml` from catalog | Migrate to dbt |
| Cube.dev | Generate JS schema from catalog | Add caching layer |
| dbt tests | Generate metric tests (`assert DAU > 0`) | CI validation |

### Recommendation

**Start with DB-Meta approach when:**
- Primary interface is conversational (Claude Desktop, etc.)
- Small-medium query volume (< 1000/day)
- Team is exploring what metrics matter
- Want rapid iteration without infrastructure

**Consider adding Cube.dev later when:**
- Query volume grows significantly
- Need to embed analytics in an app
- Cache hit rate would be high (repeated queries)
- Sub-second latency becomes critical

**Consider MetricFlow if:**
- Already invested in dbt ecosystem
- Need tight transformation-to-metric lineage
- Team prefers SQL over natural language
- Using dbt Cloud for governance

---

## References

- [dbt Semantic Layer](https://docs.getdbt.com/docs/build/about-metricflow)
- [Cube.dev Data Modeling](https://cube.dev/docs/product/data-modeling)
- [LookML Reference](https://cloud.google.com/looker/docs/reference/lookml-quick-reference)
- [Metrics Layer Comparison](https://benn.substack.com/p/metrics-layer)
- [MetricFlow (open source)](https://github.com/dbt-labs/metricflow)
