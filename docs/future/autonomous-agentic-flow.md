# Autonomous Agentic Flow - Implementation Plan

## Vision

Transform fm-app from a **fixed-flow system** into a **goal-oriented agent** that:
1. Understands user goals through conversation
2. Asks clarifying questions when needed
3. Selects and orchestrates multiple tools to achieve the goal
4. Iterates until the user's objective is met

**Key Principle**: Human-in-the-loop by design. The agent asks the right questions at the right time, rather than removing human interaction.

---

## Current vs Target Architecture

### Current: Fixed Flow Selection

```
User Request → Intent Analyzer → Fixed Flow Router
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
             InteractiveQuery     DataAnalysis        GeneralChat
                    │                   │                   │
                    ▼                   ▼                   ▼
              Single Path         Single Path         Single Path
                    │                   │                   │
                    ▼                   ▼                   ▼
                 Result              Result              Result
```

**Limitations:**
- Each request maps to exactly one flow
- No multi-step orchestration across flows
- Limited ability to iterate toward a goal
- Clarification happens only at plan approval stage

### Target: Agent with Tools

```
┌────────────────────────────────────────────────────────────────────┐
│                        AGENT LOOP                                   │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  User Request ──► Agent Core                                        │
│                      │                                              │
│                      ├──► Understand (what does user want?)         │
│                      │                                              │
│                      ├──► Clarify (ask questions if ambiguous)      │
│                      │         │                                    │
│                      │         └──► Wait for user response          │
│                      │                                              │
│                      ├──► Plan (propose approach, get approval)     │
│                      │                                              │
│                      ├──► Execute (select and run tools)            │
│                      │         │                                    │
│                      │         ├── InteractiveQuery                 │
│                      │         ├── DataAnalysis                     │
│                      │         ├── DBMeta (schema lookup)           │
│                      │         ├── Discovery                        │
│                      │         └── Visualization                    │
│                      │                                              │
│                      ├──► Verify (check if results match intent)    │
│                      │                                              │
│                      ├──► Iterate (refine if needed)                │
│                      │         │                                    │
│                      │         └──► "Does this answer your          │
│                      │              question? Want to drill deeper?"│
│                      │                                              │
│                      └──► Complete (goal achieved)                  │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

---

## Core Principles

### 1. Human-in-the-Loop by Design

Plan approval stays. The agent can and should ask clarifying questions before, during, and after execution.

```
Agent: "To analyze revenue drop, I could:
        A) Compare month-over-month by segment
        B) Look at individual large account changes  
        C) Check for data quality issues
        
        Which approach would be most useful?"

User: "Start with A, then drill into B if we find something"

Agent: [Executes with clear direction]
```

### 2. Multi-Tool Orchestration

The agent picks the right tool(s) for each step, potentially chaining them:

```
User: "Why did enterprise revenue drop last month?"

Agent Plan:
  Step 1: InteractiveQuery → Get revenue by segment (last 3 months)
  Step 2: DataAnalysis → Identify anomalies in the data
  Step 3: InteractiveQuery → Drill into top anomaly
  Step 4: Present findings with recommendation
```

### 3. Goal-Oriented Iteration

Keep going until the user's goal is met, not just "query executed":

```
Agent: "I found a 23% drop in Enterprise EMEA.
        - 3 large churns (accounts X, Y, Z)
        - 15% fewer new deals
        
        Want me to dig into the churn reasons or pipeline issues?"

User: "Show me the churned accounts"

Agent: [Continues toward the goal]
```

### 4. Conversational Refinement

Natural back-and-forth to narrow down the question:

```
User: "What's our best performing product?"

Agent: "Best performing by what metric?
        - Revenue
        - Growth rate
        - Customer satisfaction
        - Retention"

User: "Revenue growth this quarter"

Agent: [Now has clear criteria to execute]
```

---

## Available Execution Tools

### Current Tools (from InteractiveRequestType)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `interactive_query` | Generate and execute SQL | User wants data from the warehouse |
| `data_analysis` | Analyze existing data | User has data, wants insights |
| `general_chat` | Conversational response | Greeting, explanation, no data needed |
| `disambiguation` | Clarify ambiguous request | Multiple valid interpretations |
| `linked_query` | Modify existing query | User references previous query |
| `manual_query` | Execute user-provided SQL | User writes their own SQL |
| `discovery` | Explore available data | "What data do you have?" |

### New Tools (to be added)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `ask_user` | Request clarification | Need more info to proceed |
| `multi_step_query` | Chain multiple queries | Complex analysis requiring multiple data pulls |
| `visualization` | Generate charts | User wants visual representation |
| `export` | Export data to file | User wants to download results |
| `compare` | Compare two datasets | User wants to see differences |

---

## Gap Analysis: Current vs Autonomous

### Intent Analysis

| Aspect | Current State | Target State | Gap |
|--------|---------------|--------------|-----|
| Request classification | Single `request_type` output | Multi-step plan with tool sequence | Need plan model with steps |
| Ambiguity detection | Limited (returns `disambiguation`) | Proactive clarification questions | Need `ask_user` tool |
| Goal extraction | Implicit in intent | Explicit goal + success criteria | Need goal model |

**Current Implementation:**
- `intent_analyzer.py` returns `IntentAnalysis` with single `request_type`
- `requires_plan_approval` flag triggers query planner

**Gap:** No ability to output "I need to ask the user X before proceeding"

### Plan Generation

| Aspect | Current State | Target State | Gap |
|--------|---------------|--------------|-----|
| Scope | Single query plan | Multi-step execution plan | Need step sequencing |
| Tool selection | Fixed (always SQL) | Dynamic tool selection per step | Need tool registry |
| Iteration | None | Plan can include iteration points | Need conditional steps |

**Current Implementation:**
- `query_planner.py` generates `QueryPlan` for SQL generation
- Plan includes tables, columns, filters, assumptions

**Gap:** Plan is SQL-centric, not tool-agnostic

### Execution

| Aspect | Current State | Target State | Gap |
|--------|---------------|--------------|-----|
| Flow selection | One flow per request | Multiple tools per request | Need orchestrator |
| State management | Per-request | Per-goal (across requests) | Need goal state |
| Result verification | SQL validation only | Goal achievement check | Need verification step |

**Current Implementation:**
- `interactive_flow/__init__.py` routes to handlers based on `request_type`
- Each handler is independent

**Gap:** No way to chain handlers or maintain goal state across requests

### User Interaction

| Aspect | Current State | Target State | Gap |
|--------|---------------|--------------|-----|
| Clarification | Only at plan approval | Any point in flow | Need `ask_user` primitive |
| Feedback | Implicit (next request) | Explicit ("Did this help?") | Need feedback prompts |
| Iteration | New request = new flow | Continue toward same goal | Need goal continuity |

**Current Implementation:**
- Plan approval is the only structured user interaction point
- User feedback comes as new requests

**Gap:** Agent can't pause mid-flow to ask questions

---

## Proposed Architecture

### Agent Core Model

```python
class AgentGoal(BaseModel):
    """Represents what the user is trying to achieve."""
    goal_id: UUID
    description: str  # "Understand why revenue dropped"
    success_criteria: list[str]  # ["Identified root cause", "Quantified impact"]
    status: Literal["active", "achieved", "abandoned"]
    created_at: datetime
    
class AgentStep(BaseModel):
    """Single step in agent's execution plan."""
    step_id: UUID
    tool: str  # "interactive_query", "data_analysis", "ask_user"
    description: str  # "Query revenue by segment"
    inputs: dict  # Tool-specific inputs
    depends_on: list[UUID]  # Previous step IDs
    status: Literal["pending", "running", "completed", "blocked"]
    result: Optional[dict] = None

class AgentPlan(BaseModel):
    """Multi-step plan to achieve a goal."""
    plan_id: UUID
    goal_id: UUID
    steps: list[AgentStep]
    current_step: int
    requires_approval: bool
    
class AgentState(BaseModel):
    """Agent's working memory for a session."""
    session_id: UUID
    current_goal: Optional[AgentGoal]
    active_plan: Optional[AgentPlan]
    completed_steps: list[AgentStep]
    context: dict  # Accumulated knowledge
```

### Tool Registry

```python
class AgentTool(Protocol):
    """Interface for agent tools."""
    name: str
    description: str
    
    async def can_handle(self, intent: str, context: dict) -> float:
        """Return confidence (0-1) that this tool can handle the intent."""
        ...
    
    async def execute(self, inputs: dict, context: dict) -> ToolResult:
        """Execute the tool and return result."""
        ...
    
    async def validate_result(self, result: ToolResult, goal: AgentGoal) -> bool:
        """Check if result contributes to goal achievement."""
        ...

# Tool implementations
class InteractiveQueryTool(AgentTool):
    name = "interactive_query"
    description = "Generate and execute SQL queries against the data warehouse"

class DataAnalysisTool(AgentTool):
    name = "data_analysis"
    description = "Analyze existing data to find patterns and insights"

class AskUserTool(AgentTool):
    name = "ask_user"
    description = "Ask the user a clarifying question and wait for response"
    
class DBMetaTool(AgentTool):
    name = "schema_lookup"
    description = "Look up database schema, table details, and relationships"
```

### Agent Orchestrator

```python
class AgentOrchestrator:
    """Main agent loop."""
    
    async def process_request(
        self,
        request: WorkerRequest,
        ctx: FlowContext,
    ) -> AgentResponse:
        
        # 1. Load or create goal
        goal = await self.get_or_create_goal(request, ctx)
        
        # 2. Check if we need clarification
        if self.needs_clarification(request, goal):
            return await self.ask_clarification(request, goal, ctx)
        
        # 3. Generate or update plan
        plan = await self.generate_plan(goal, ctx)
        
        # 4. If plan needs approval, return for user review
        if plan.requires_approval:
            return AgentResponse(
                type="plan_approval",
                plan=plan,
                message="Here's my plan. Should I proceed?",
            )
        
        # 5. Execute next step(s)
        while self.has_pending_steps(plan):
            step = self.get_next_step(plan)
            
            # Check if step needs user input
            if step.tool == "ask_user":
                return AgentResponse(
                    type="question",
                    question=step.inputs["question"],
                    options=step.inputs.get("options"),
                )
            
            # Execute the tool
            result = await self.execute_step(step, ctx)
            
            # Check if we achieved the goal
            if await self.goal_achieved(goal, plan):
                return AgentResponse(
                    type="complete",
                    result=result,
                    message="Goal achieved!",
                )
            
            # Check if we need to re-plan
            if self.needs_replan(result, plan):
                plan = await self.generate_plan(goal, ctx, feedback=result)
        
        # 6. Return current result and ask if goal is met
        return AgentResponse(
            type="checkpoint",
            result=self.get_current_result(plan),
            message="Does this answer your question?",
        )
```

---

## Integration with DB-Meta Enhancements

The [DB-Meta Granular Schema Exploration](./db-meta-granular-schema-exploration.md) plan provides tools that the agent can leverage:

### MCP Tools as Agent Tools

| MCP Tool | Agent Usage |
|----------|-------------|
| `prompt_items_v2` | Initial schema discovery for planning |
| `table_details` | Deep dive when agent needs FK relationships, value ranges |
| `validate_plan` | Agent validates its own plan before execution |
| `preflight_query` | Agent validates SQL before running |

### MCP Prompts as Agent Context

| MCP Prompt | Agent Usage |
|------------|-------------|
| `domain_model` | Understand business entities and relationships |
| `sql_dialect` | Generate correct SQL syntax |
| `prompt_instructions` | Follow business rules and constraints |

### Enhanced Agent Planning with Schema Details

```python
async def generate_plan(self, goal: AgentGoal, ctx: FlowContext) -> AgentPlan:
    # 1. Get lightweight schema for planning
    schema = await self.db_meta.prompt_items_v2(
        items=["DBStruct"],
        schema_top_k=10
    )
    
    # 2. Generate initial plan
    plan = await self.llm.generate_plan(goal, schema)
    
    # 3. Validate plan tables/columns exist
    validation = await self.db_meta.validate_plan(
        tables=plan.tables,
        columns=plan.columns
    )
    
    if not validation.valid:
        # Re-plan with error feedback
        plan = await self.llm.generate_plan(
            goal, schema, 
            errors=validation.errors
        )
    
    # 4. Get detailed table info for selected tables
    if plan.tables:
        details = await self.db_meta.table_details(
            tables=plan.tables,
            include=["relationships", "low_cardinality_values", "ranges"]
        )
        plan.table_details = details
    
    return plan
```

---

## Implementation Phases

### Phase 1: Ask User Primitive

**Goal:** Agent can ask clarifying questions at any point

**Changes:**
- Add `ask_user` request type to `IntentAnalysis`
- Add question/options fields to request model
- Update frontend to handle question responses
- Modify intent analyzer to output questions when ambiguous

**Files:**
- `fm_app/api/model.py` - Add `AskUserRequest` model
- `fm_app/workers/interactive_flow/intent_analyzer.py` - Output questions
- `apps/web/` - Handle question UI

### Phase 2: Goal State Management

**Goal:** Maintain goal context across multiple requests

**Changes:**
- Add `AgentGoal` model and storage
- Link requests to goals
- Track progress toward goal achievement

**Files:**
- `fm_app/api/model.py` - Add goal models
- `fm_app/db/` - Goal persistence
- `fm_app/workers/interactive_flow/` - Goal-aware handlers

### Phase 3: Multi-Step Plans

**Goal:** Plans can include multiple tool invocations

**Changes:**
- Extend `QueryPlan` → `AgentPlan` with steps
- Add step sequencing and dependencies
- Track partial execution state

**Files:**
- `fm_app/api/model.py` - Extend plan models
- `fm_app/workers/interactive_flow/query_planner.py` - Multi-step planning

### Phase 4: Tool Registry

**Goal:** Pluggable tool architecture

**Changes:**
- Define `AgentTool` protocol
- Wrap existing handlers as tools
- Implement tool selection logic

**Files:**
- `fm_app/workers/agent/tools/` - New tool implementations
- `fm_app/workers/agent/registry.py` - Tool registry

### Phase 5: Agent Orchestrator

**Goal:** Main agent loop with goal-oriented execution

**Changes:**
- Implement `AgentOrchestrator`
- Integrate with existing flow infrastructure
- Add verification and iteration logic

**Files:**
- `fm_app/workers/agent/orchestrator.py` - Main agent
- `fm_app/workers/interactive_flow/__init__.py` - Integration

### Phase 6: Result Verification

**Goal:** Agent checks if results match intent

**Changes:**
- Add result verification prompts
- Implement goal achievement detection
- Add "Did this help?" feedback loop

**Files:**
- `fm_app/workers/agent/verification.py` - Result checking
- Prompt templates for verification

---

## Example: Full Agent Flow

```
User: "Why did revenue drop last month?"

Agent (internal):
  - Goal: Understand revenue drop cause
  - Need clarification: Which segments? What timeframe?

Agent: "To analyze the revenue drop, I have a few questions:
        1. Which customer segment? (Enterprise, SMB, All)
        2. Compare to which period? (Previous month, Same month last year)"

User: "Enterprise, compare to previous month"

Agent (internal):
  - Goal clarified
  - Plan:
    Step 1: Query revenue by sub-segment (EMEA, APAC, Americas)
    Step 2: Identify largest drop
    Step 3: Drill into that segment

Agent: "Here's my plan:
        1. Get Enterprise revenue by region (last 2 months)
        2. Find the biggest decline
        3. Drill into contributing factors
        
        Proceed?"

User: "Yes"

Agent: [Executes Step 1 - InteractiveQuery]
       [Executes Step 2 - DataAnalysis]
       
       "Found it: Enterprise EMEA dropped 23%
        
        Top factors:
        - 3 large account churns ($2.1M impact)
        - 15% fewer new deals closed
        
        Want me to:
        A) Show details on churned accounts
        B) Analyze pipeline issues
        C) Both"

User: "A"

Agent: [Executes - InteractiveQuery for churn details]

       "Here are the churned accounts:
        - Acme Corp ($800K) - Switched to competitor
        - BigCo ($750K) - Budget cuts
        - MegaInc ($550K) - Consolidating vendors
        
        Would you like me to check if there are similar at-risk accounts?"

User: "Yes, that would be helpful"

Agent: [Continues toward goal...]
```

---

## Success Metrics

1. **Goal Achievement Rate**: % of sessions where user's goal is fully met
2. **Clarification Efficiency**: Average questions asked before successful execution
3. **Iteration Count**: Steps to reach goal (lower is better for simple goals)
4. **User Satisfaction**: Explicit feedback on results
5. **Tool Utilization**: Distribution of tools used (should match task complexity)

---

## Relationship to Other Plans

- **[DB-Meta Granular Schema Exploration](./db-meta-granular-schema-exploration.md)**: Provides enhanced MCP tools that the agent uses for schema discovery, validation, and deep table analysis
- **Query Planner**: Becomes one tool in the agent's toolkit, not the only path
- **Interactive Flow**: Infrastructure is reused, but orchestration changes

---

## Design Decisions

### 1. Goal Persistence: Per-Session

Goals persist within a session only. When session ends, goal state is cleared.

**Rationale:** Simpler implementation, natural boundary, users can start fresh sessions for new goals.

### 2. Plan Approval UX: TBD

Need to design how multi-step plans are presented. Options to explore:
- Tree/timeline view showing steps and dependencies
- Expandable cards with step details
- Simple numbered list with tool icons
- Progressive disclosure (show next step only)

### 3. Failure Recovery: Tiered Approach

| Step Type | On Failure | Threshold |
|-----------|------------|-----------|
| Internal (SQL generation, validation) | Self-correct | 3 attempts |
| Tool execution (query, analysis) | Self-correct | 2 attempts |
| After threshold exhausted | Re-plan and ask user | - |

**Example:**
```
Agent: "I tried to generate SQL but hit validation errors 3 times.
        The issue seems to be [X].
        
        Options:
        A) Let me try a different approach (simpler query)
        B) Show me the errors so you can help
        C) Skip this step and move on"
```

### 4. Cost Management: EXPLAIN-Based Metrics

Use SQL EXPLAIN metrics to guard against expensive operations:

```python
class CostGuard:
    # Thresholds (configurable)
    MAX_ESTIMATED_ROWS = 10_000_000_000  # 10B rows
    MAX_ESTIMATED_SIZE_GB = 100.0
    MAX_STEPS_PER_PLAN = 10
    MAX_QUERIES_PER_GOAL = 20
    
    async def check_step_cost(self, step: AgentStep) -> CostDecision:
        if step.tool == "interactive_query":
            explain = await self.db_meta.preflight_query(step.sql)
            
            if explain.estimated_rows > self.MAX_ESTIMATED_ROWS:
                return CostDecision(
                    allow=False,
                    reason=f"Query would scan {explain.estimated_rows:,} rows",
                    suggestion="Add filters or LIMIT clause"
                )
        
        return CostDecision(allow=True)
    
    def check_plan_cost(self, plan: AgentPlan) -> CostDecision:
        if len(plan.steps) > self.MAX_STEPS_PER_PLAN:
            return CostDecision(
                allow=False,
                reason=f"Plan has {len(plan.steps)} steps (max: {self.MAX_STEPS_PER_PLAN})",
                suggestion="Simplify the goal or break into smaller goals"
            )
        return CostDecision(allow=True)
```

### 5. Concurrent Goals: No

One active goal per session. If user starts a new goal, previous goal is marked as abandoned.

**Rationale:** 
- Simpler state management
- Clearer conversation flow
- User can start new session for parallel work
- Avoids confusion about which goal agent is working on

---

## Implementation Plan

**Key Principle:** Backward compatible. Existing flows continue to work unchanged. Agent capabilities are additive.

### Phase 1: Ask User Primitive (Foundation)

**Goal:** Agent can ask clarifying questions before or during execution.

**Backward Compatibility:** 
- Existing `IntentAnalysis` response type still works
- New `clarification_needed` field is optional
- Frontend gracefully handles new response type

#### 1.1 Model Changes (`fm_app/api/model.py`)

```python
# Add to IntentAnalysis - backward compatible (optional field)
class IntentAnalysis(BaseModel):
    request_type: InteractiveRequestType = InteractiveRequestType.interactive_query
    intent: Optional[str] = None
    summary: Optional[str] = None
    response: Optional[str] = None
    requires_plan_approval: bool = False
    
    # NEW: Clarification support
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    clarification_options: Optional[list[str]] = None  # Optional multiple choice


# Add new request type
class InteractiveRequestType(str, Enum):
    # ... existing types ...
    clarification_response = "clarification_response"  # User answering agent question
```

#### 1.2 Intent Analyzer Changes (`fm_app/workers/interactive_flow/intent_analyzer.py`)

```python
# Update planner prompt to allow clarification output
# Modify IntentAnalysis parsing to handle clarification fields

async def analyze_intent(ctx: FlowContext) -> IntentAnalysis:
    # ... existing code ...
    
    # LLM can now return clarification_needed=True with question
    intent = ai_model.get_structured(messages, IntentAnalysis)
    
    # If clarification needed, don't proceed to flow selection
    if intent.clarification_needed:
        return intent  # Orchestrator handles this
    
    return intent
```

#### 1.3 Orchestrator Changes (`fm_app/workers/interactive_flow/__init__.py`)

```python
async def interactive_flow(request, llm, db_wh, db):
    # ... existing setup ...
    
    intent = await analyze_intent(ctx)
    
    # NEW: Handle clarification
    if intent.clarification_needed:
        # Store pending state for when user responds
        await store_pending_clarification(ctx, intent)
        
        # Return clarification request to frontend
        request.status = RequestStatus.feedback_requested
        request.structured_response = StructuredResponse(
            type="clarification",
            question=intent.clarification_question,
            options=intent.clarification_options,
        )
        return request
    
    # ... existing flow routing (unchanged) ...
```

#### 1.4 Frontend Changes (`apps/web/`)

```typescript
// Handle new response type in chat/session components
if (response.type === "clarification") {
  // Render question with optional buttons for options
  // User response goes back as clarification_response request type
}
```

#### 1.5 Prompt Updates (`packages/resources/.../planner/prompt.md`)

```markdown
## Output Format

If the user's request is ambiguous or missing critical information, you may ask
a clarifying question instead of proceeding:

{
  "clarification_needed": true,
  "clarification_question": "Which time period should I analyze?",
  "clarification_options": ["Last 7 days", "Last 30 days", "Last quarter", "Custom range"]
}

Only ask clarification when truly necessary. Prefer making reasonable assumptions
when possible, stating them in the plan for user approval.
```

**Files to modify:**
- `fm_app/api/model.py` - Add clarification fields
- `fm_app/workers/interactive_flow/intent_analyzer.py` - Handle clarification output
- `fm_app/workers/interactive_flow/__init__.py` - Route clarification responses
- `packages/resources/.../planner/prompt.md` - Allow clarification output
- `apps/web/app/contexts/ChatSession/` - Render clarification UI

---

### Phase 2: Goal State Management

**Goal:** Track user's objective across multiple requests in a session.

**Backward Compatibility:**
- Goal tracking is transparent to existing flows
- Requests without explicit goals work as before
- Goal state is optional metadata, not required

#### 2.1 Goal Models (`fm_app/api/model.py`)

```python
class GoalStatus(str, Enum):
    active = "active"
    achieved = "achieved"
    abandoned = "abandoned"

class SessionGoal(BaseModel):
    """Tracks what the user is trying to achieve in this session."""
    goal_id: UUID
    session_id: UUID
    description: str  # "Understand why revenue dropped last month"
    success_criteria: list[str] = []  # Optional explicit criteria
    status: GoalStatus = GoalStatus.active
    created_at: datetime
    updated_at: datetime
    
    # Context accumulated during goal pursuit
    context: dict = {}  # Findings, intermediate results
    requests: list[UUID] = []  # Request IDs contributing to this goal
```

#### 2.2 Database Schema (`alembic/versions/xxx_add_session_goals.py`)

```python
def upgrade():
    op.create_table(
        'session_goals',
        sa.Column('goal_id', sa.UUID(), primary_key=True),
        sa.Column('session_id', sa.UUID(), sa.ForeignKey('sessions.session_id')),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('success_criteria', sa.JSON(), default=[]),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('context', sa.JSON(), default={}),
        sa.Column('created_at', sa.DateTime(), default=datetime.utcnow),
        sa.Column('updated_at', sa.DateTime(), onupdate=datetime.utcnow),
    )
    
    # Link requests to goals (optional FK)
    op.add_column('requests', 
        sa.Column('goal_id', sa.UUID(), sa.ForeignKey('session_goals.goal_id'), nullable=True)
    )
```

#### 2.3 Goal Extraction (`fm_app/workers/interactive_flow/goal_tracker.py`)

```python
async def extract_or_continue_goal(ctx: FlowContext, intent: IntentAnalysis) -> SessionGoal:
    """Extract goal from intent or continue existing goal."""
    
    # Check for active goal in session
    active_goal = await get_active_goal(ctx.db, ctx.req.session_id)
    
    if active_goal:
        # Determine if this request continues the goal or starts new one
        continues_goal = await llm_check_goal_continuity(
            active_goal, ctx.req.request, intent
        )
        
        if continues_goal:
            # Update goal context with new request
            await link_request_to_goal(ctx.db, ctx.req.request_id, active_goal.goal_id)
            return active_goal
        else:
            # Abandon old goal, create new one
            await abandon_goal(ctx.db, active_goal.goal_id)
    
    # Extract new goal from intent
    goal = await extract_goal_from_intent(ctx, intent)
    await save_goal(ctx.db, goal)
    await link_request_to_goal(ctx.db, ctx.req.request_id, goal.goal_id)
    
    return goal
```

#### 2.4 Integration with Orchestrator

```python
async def interactive_flow(request, llm, db_wh, db):
    # ... existing setup ...
    
    intent = await analyze_intent(ctx)
    
    # NEW: Goal tracking (transparent, doesn't change flow)
    goal = await extract_or_continue_goal(ctx, intent)
    ctx.current_goal = goal  # Available to handlers
    
    # ... existing flow routing (unchanged) ...
```

**Files to modify:**
- `fm_app/api/model.py` - Add goal models
- `fm_app/db/goal_db.py` - Goal CRUD operations
- `alembic/versions/` - Migration for goals table
- `fm_app/workers/interactive_flow/goal_tracker.py` - New file
- `fm_app/workers/interactive_flow/__init__.py` - Integrate goal tracking
- `fm_app/workers/interactive_flow/setup.py` - Add goal to FlowContext

---

### Phase 3: Multi-Step Plans

**Goal:** Plans can include multiple tool invocations with dependencies.

**Backward Compatibility:**
- Existing `QueryPlan` continues to work for single-query flows
- Multi-step plans are a superset, used when `plan.steps` is populated
- Single-step plans auto-convert to multi-step internally

#### 3.1 Extended Plan Models (`fm_app/api/model.py`)

```python
class PlanStepTool(str, Enum):
    interactive_query = "interactive_query"
    data_analysis = "data_analysis"
    schema_lookup = "schema_lookup"
    ask_user = "ask_user"

class PlanStep(BaseModel):
    """Single step in a multi-step plan."""
    step_id: str  # "step_1", "step_2", etc.
    tool: PlanStepTool
    description: str  # Human-readable: "Query revenue by segment"
    inputs: dict = {}  # Tool-specific inputs
    depends_on: list[str] = []  # Step IDs this depends on
    
    # Populated during execution
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    result: Optional[dict] = None
    error: Optional[str] = None

class MultiStepPlan(BaseModel):
    """Extended plan with multiple steps."""
    plan_id: UUID
    goal_id: Optional[UUID] = None
    
    # Overall plan description (shown to user)
    plan_summary: str
    
    # Steps to execute
    steps: list[PlanStep]
    
    # Execution state
    current_step_index: int = 0
    status: Literal["pending_approval", "executing", "completed", "failed"] = "pending_approval"
    
    # Legacy compatibility: single-query plan fields
    # These are populated for backward compat when steps has single interactive_query
    tables: list[str] = []
    columns_selected: list[str] = []
    filters: list[QueryPlanFilter] = []
    # ... other QueryPlan fields ...
    
    @classmethod
    def from_query_plan(cls, qp: QueryPlan) -> "MultiStepPlan":
        """Convert legacy QueryPlan to MultiStepPlan."""
        return cls(
            plan_id=uuid4(),
            plan_summary=qp.plan_summary,
            steps=[PlanStep(
                step_id="step_1",
                tool=PlanStepTool.interactive_query,
                description=qp.plan_summary,
                inputs={"query_plan": qp.model_dump()},
            )],
            # Copy legacy fields for backward compat
            tables=qp.tables,
            columns_selected=qp.columns_selected,
            filters=qp.filters,
            # ...
        )
```

#### 3.2 Multi-Step Planner (`fm_app/workers/interactive_flow/multi_step_planner.py`)

```python
async def generate_multi_step_plan(
    ctx: FlowContext,
    intent: IntentAnalysis,
    goal: SessionGoal,
) -> MultiStepPlan:
    """Generate a multi-step plan for complex goals."""
    
    # Check if this needs multi-step (complex goal) or single-step
    if not requires_multi_step(intent, goal):
        # Use existing query planner, wrap result
        query_plan = await generate_query_plan(ctx, intent.intent)
        return MultiStepPlan.from_query_plan(query_plan)
    
    # Generate multi-step plan via LLM
    planner_vars = await build_prompt_variables(ctx)
    planner_vars["goal"] = goal.description
    planner_vars["available_tools"] = get_available_tools_description()
    
    slot = await ctx.assembler.render_async(
        "multi_step_planner",  # New slot
        variables=planner_vars,
        req_ctx=mcp_ctx,
    )
    
    plan = ctx.ai_model.get_structured(messages, MultiStepPlan)
    
    # Validate plan
    await validate_multi_step_plan(ctx, plan)
    
    return plan
```

#### 3.3 Step Executor (`fm_app/workers/interactive_flow/step_executor.py`)

```python
async def execute_step(ctx: FlowContext, step: PlanStep) -> StepResult:
    """Execute a single plan step."""
    
    tool = get_tool(step.tool)
    
    # Check cost before execution
    cost_check = await ctx.cost_guard.check_step_cost(step)
    if not cost_check.allow:
        return StepResult(
            success=False,
            error=cost_check.reason,
            suggestion=cost_check.suggestion,
        )
    
    # Execute the tool
    try:
        result = await tool.execute(step.inputs, ctx)
        step.status = "completed"
        step.result = result
        return StepResult(success=True, data=result)
    except Exception as e:
        step.status = "failed"
        step.error = str(e)
        return StepResult(success=False, error=str(e))


async def execute_plan(ctx: FlowContext, plan: MultiStepPlan) -> PlanResult:
    """Execute all steps in a plan, respecting dependencies."""
    
    plan.status = "executing"
    
    while has_pending_steps(plan):
        # Get next executable steps (dependencies satisfied)
        ready_steps = get_ready_steps(plan)
        
        for step in ready_steps:
            # Handle ask_user specially - return to frontend
            if step.tool == PlanStepTool.ask_user:
                return PlanResult(
                    status="awaiting_user",
                    question=step.inputs["question"],
                    plan=plan,
                )
            
            result = await execute_step(ctx, step)
            
            if not result.success:
                # Attempt self-correction
                corrected = await attempt_correction(ctx, step, result)
                if not corrected:
                    # Threshold exhausted, need user help
                    return PlanResult(
                        status="needs_replan",
                        error=result.error,
                        plan=plan,
                    )
    
    plan.status = "completed"
    return PlanResult(status="completed", plan=plan)
```

**Files to modify:**
- `fm_app/api/model.py` - Add MultiStepPlan, PlanStep models
- `fm_app/workers/interactive_flow/multi_step_planner.py` - New file
- `fm_app/workers/interactive_flow/step_executor.py` - New file
- `fm_app/workers/interactive_flow/__init__.py` - Integrate multi-step execution
- `packages/resources/.../multi_step_planner/prompt.md` - New slot
- `fm_app/db/plan_db.py` - Store multi-step plans

---

### Phase 4: Tool Registry

**Goal:** Pluggable tool architecture for agent to select from.

**Backward Compatibility:**
- Existing handlers become tools
- Tool interface wraps existing implementation
- No changes to handler internals

#### 4.1 Tool Protocol (`fm_app/workers/agent/tools/base.py`)

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class AgentTool(Protocol):
    """Interface for agent-executable tools."""
    
    name: str
    description: str
    
    async def execute(self, inputs: dict, ctx: FlowContext) -> ToolResult:
        """Execute the tool with given inputs."""
        ...
    
    def get_input_schema(self) -> dict:
        """Return JSON schema for inputs."""
        ...


@dataclass
class ToolResult:
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
```

#### 4.2 Tool Implementations (`fm_app/workers/agent/tools/`)

```python
# interactive_query_tool.py
class InteractiveQueryTool:
    name = "interactive_query"
    description = "Generate and execute SQL queries against the data warehouse"
    
    async def execute(self, inputs: dict, ctx: FlowContext) -> ToolResult:
        # Wrap existing handle_interactive_query
        from fm_app.workers.interactive_flow.interactive_query import handle_interactive_query
        
        query_plan = QueryPlan(**inputs.get("query_plan", {}))
        result = await handle_interactive_query(ctx, intent=None, query_plan=query_plan)
        
        return ToolResult(
            success=result.success,
            data={"query_id": str(ctx.req.query.query_id)} if result.success else None,
            error=result.errors[0] if result.errors else None,
        )


# data_analysis_tool.py
class DataAnalysisTool:
    name = "data_analysis"
    description = "Analyze existing query results to find patterns and insights"
    
    async def execute(self, inputs: dict, ctx: FlowContext) -> ToolResult:
        from fm_app.workers.interactive_flow.data_analysis import handle_data_analysis
        await handle_data_analysis(ctx)
        return ToolResult(success=True, data={"response": ctx.req.response})


# schema_lookup_tool.py
class SchemaLookupTool:
    name = "schema_lookup"
    description = "Look up database schema, table details, and relationships"
    
    async def execute(self, inputs: dict, ctx: FlowContext) -> ToolResult:
        from fm_app.mcp_servers.db_meta import get_table_details_mcp
        
        details = await get_table_details_mcp(
            req=ctx.mcp_req,
            tables=inputs.get("tables", []),
            include=inputs.get("include", ["relationships", "cardinality"]),
            # ...
        )
        return ToolResult(success=True, data={"tables": details.tables})


# ask_user_tool.py
class AskUserTool:
    name = "ask_user"
    description = "Ask the user a clarifying question"
    
    async def execute(self, inputs: dict, ctx: FlowContext) -> ToolResult:
        # This tool doesn't "execute" - it signals to return control to user
        return ToolResult(
            success=True,
            data={
                "question": inputs["question"],
                "options": inputs.get("options"),
            },
            metadata={"awaits_user": True},
        )
```

#### 4.3 Tool Registry (`fm_app/workers/agent/registry.py`)

```python
class ToolRegistry:
    """Registry of available agent tools."""
    
    def __init__(self):
        self._tools: dict[str, AgentTool] = {}
    
    def register(self, tool: AgentTool) -> None:
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> AgentTool:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        return self._tools[name]
    
    def list_tools(self) -> list[dict]:
        """Return tool descriptions for LLM prompt."""
        return [
            {"name": t.name, "description": t.description, "inputs": t.get_input_schema()}
            for t in self._tools.values()
        ]


# Default registry with all tools
def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(InteractiveQueryTool())
    registry.register(DataAnalysisTool())
    registry.register(SchemaLookupTool())
    registry.register(AskUserTool())
    # ... more tools ...
    return registry
```

**Files to create:**
- `fm_app/workers/agent/` - New package
- `fm_app/workers/agent/tools/base.py` - Tool protocol
- `fm_app/workers/agent/tools/interactive_query.py`
- `fm_app/workers/agent/tools/data_analysis.py`
- `fm_app/workers/agent/tools/schema_lookup.py`
- `fm_app/workers/agent/tools/ask_user.py`
- `fm_app/workers/agent/registry.py` - Tool registry

---

### Phase 5: Agent Orchestrator

**Goal:** Main agent loop with goal-oriented execution.

**Backward Compatibility:**
- Agent orchestrator is opt-in via feature flag
- Without flag, existing `interactive_flow` runs unchanged
- Gradual migration path

#### 5.1 Orchestrator (`fm_app/workers/agent/orchestrator.py`)

```python
class AgentOrchestrator:
    """Main agent loop for goal-oriented execution."""
    
    def __init__(self, tool_registry: ToolRegistry, settings: Settings):
        self.tools = tool_registry
        self.settings = settings
        self.cost_guard = CostGuard(settings)
    
    async def process_request(
        self,
        request: WorkerRequest,
        ctx: FlowContext,
    ) -> AgentResponse:
        """Process a user request through the agent loop."""
        
        # 1. Analyze intent
        intent = await analyze_intent(ctx)
        
        # 2. Handle clarification if needed
        if intent.clarification_needed:
            return AgentResponse(
                type="clarification",
                question=intent.clarification_question,
                options=intent.clarification_options,
            )
        
        # 3. Get or continue goal
        goal = await extract_or_continue_goal(ctx, intent)
        ctx.current_goal = goal
        
        # 4. Generate or update plan
        plan = await self.generate_or_update_plan(ctx, intent, goal)
        
        # 5. Check if plan needs approval
        if plan.status == "pending_approval" and self.requires_approval(plan):
            await save_plan(ctx.db, plan)
            return AgentResponse(
                type="plan_approval",
                plan=plan,
                message=self.format_plan_for_approval(plan),
            )
        
        # 6. Execute plan
        result = await self.execute_plan(ctx, plan)
        
        # 7. Handle execution result
        if result.status == "awaiting_user":
            return AgentResponse(
                type="question",
                question=result.question,
                plan_id=plan.plan_id,
            )
        
        if result.status == "needs_replan":
            # Re-plan with error context
            new_plan = await self.replan_with_feedback(ctx, plan, result.error)
            return AgentResponse(
                type="replan",
                plan=new_plan,
                error=result.error,
                message="I hit an issue. Here's an alternative approach:",
            )
        
        # 8. Check goal achievement
        if await self.check_goal_achieved(goal, plan):
            await mark_goal_achieved(ctx.db, goal.goal_id)
            return AgentResponse(
                type="complete",
                result=self.compile_results(plan),
                message="Goal achieved!",
            )
        
        # 9. Ask if user wants to continue
        return AgentResponse(
            type="checkpoint",
            result=self.compile_results(plan),
            message="Here's what I found. Would you like me to dig deeper?",
        )
    
    async def execute_plan(self, ctx: FlowContext, plan: MultiStepPlan) -> PlanResult:
        """Execute plan steps with cost guards and error handling."""
        # ... implementation from Phase 3 ...
```

#### 5.2 Feature Flag Integration (`fm_app/workers/interactive_flow/__init__.py`)

```python
async def interactive_flow(request, llm, db_wh, db):
    """Main entry point - routes to agent or legacy flow."""
    
    ctx = await setup_flow_context(request, llm, db_wh, db)
    
    # Feature flag: use agent orchestrator
    if ctx.settings.enable_agent_orchestrator:
        orchestrator = AgentOrchestrator(
            tool_registry=create_default_registry(),
            settings=ctx.settings,
        )
        response = await orchestrator.process_request(request, ctx)
        return convert_agent_response_to_request(request, response)
    
    # Legacy flow (unchanged)
    intent = await analyze_intent(ctx)
    # ... existing routing ...
```

**Files to create/modify:**
- `fm_app/workers/agent/orchestrator.py` - Main agent
- `fm_app/workers/agent/cost_guard.py` - Cost management
- `fm_app/workers/interactive_flow/__init__.py` - Feature flag routing
- `fm_app/config.py` - Add `enable_agent_orchestrator` setting

---

### Phase 6: Result Verification & Iteration

**Goal:** Agent checks if results match intent and iterates if needed.

**Backward Compatibility:**
- Verification is optional enhancement
- Can be disabled via config
- Doesn't change result format

#### 6.1 Verification Module (`fm_app/workers/agent/verification.py`)

```python
class ResultVerifier:
    """Verify if results match the user's goal."""
    
    async def verify_goal_progress(
        self,
        goal: SessionGoal,
        plan: MultiStepPlan,
        ctx: FlowContext,
    ) -> VerificationResult:
        """Check if plan execution moved toward goal achievement."""
        
        # Compile evidence from completed steps
        evidence = self.compile_evidence(plan)
        
        # LLM-based verification
        verification_prompt = self.build_verification_prompt(goal, evidence)
        
        result = ctx.ai_model.get_structured(
            verification_prompt, 
            VerificationResult
        )
        
        return result


class VerificationResult(BaseModel):
    goal_achieved: bool
    confidence: float  # 0-1
    evidence: list[str]  # What supports this conclusion
    gaps: list[str]  # What's still missing
    suggested_next_steps: list[str]  # If not achieved
```

#### 6.2 Iteration Prompts (`packages/resources/.../verification/prompt.md`)

```markdown
## Goal Verification

Given the user's goal and the results obtained, determine if the goal has been achieved.

### User's Goal
{{ goal.description }}

### Success Criteria
{% for criterion in goal.success_criteria %}
- {{ criterion }}
{% endfor %}

### Results Obtained
{{ evidence }}

### Your Assessment

Respond with:
- goal_achieved: true/false
- confidence: 0-1 score
- evidence: list of facts supporting your conclusion
- gaps: what information is still missing
- suggested_next_steps: if not achieved, what should be done next
```

#### 6.3 Feedback Loop

```python
# In orchestrator, after plan execution:

async def handle_checkpoint(
    self,
    ctx: FlowContext,
    goal: SessionGoal,
    plan: MultiStepPlan,
) -> AgentResponse:
    """Handle checkpoint - verify results and potentially iterate."""
    
    verification = await self.verifier.verify_goal_progress(goal, plan, ctx)
    
    if verification.goal_achieved and verification.confidence > 0.8:
        return AgentResponse(
            type="complete",
            result=self.compile_results(plan),
            message="I believe this answers your question.",
            verification=verification,
        )
    
    if verification.gaps:
        # Offer to continue
        return AgentResponse(
            type="checkpoint",
            result=self.compile_results(plan),
            message=f"Here's what I found. {self.format_gaps(verification.gaps)}",
            suggested_actions=verification.suggested_next_steps,
        )
    
    # Low confidence - ask user
    return AgentResponse(
        type="verification",
        result=self.compile_results(plan),
        message="Does this answer your question?",
        options=["Yes, that's what I needed", "No, I need more detail", "Let me clarify what I meant"],
    )
```

**Files to create:**
- `fm_app/workers/agent/verification.py` - Result verification
- `packages/resources/.../verification/prompt.md` - Verification prompt

---

## Migration Path

### Step 1: Deploy Phase 1 (Ask User)
- Feature flag: `enable_agent_clarification=true`
- Monitor: clarification rate, user satisfaction

### Step 2: Deploy Phase 2 (Goals)
- Feature flag: `enable_goal_tracking=true`
- Monitor: goal achievement rate, session length

### Step 3: Deploy Phase 3-4 (Multi-Step + Tools)
- Feature flag: `enable_multi_step_plans=true`
- Monitor: plan complexity, execution success rate

### Step 4: Deploy Phase 5 (Full Agent)
- Feature flag: `enable_agent_orchestrator=true`
- A/B test against legacy flow
- Monitor: goal achievement, user satisfaction, cost

### Step 5: Deprecate Legacy Flow
- Once agent outperforms legacy on all metrics
- Keep legacy as fallback for edge cases

---

## Frontend & API Changes

### API Changes (fm-app)

#### Phase 1: Clarification Support

**Modified Response Model:**
```python
# StructuredResponse gains new optional fields
class StructuredResponse(BaseModel):
    # ... existing fields ...
    intent: Optional[str] = None
    description: Optional[str] = None
    intro: Optional[str] = None
    sql: Optional[str] = None
    metadata: Optional[dict] = None
    refs: Optional[Refs] = None
    
    # NEW: Clarification support
    type: Optional[str] = None  # "query", "clarification", "plan_approval", etc.
    clarification: Optional[ClarificationData] = None

class ClarificationData(BaseModel):
    question: str
    options: Optional[list[str]] = None  # Multiple choice options
    context: Optional[str] = None  # Why we're asking
```

**New Request Type:**
```python
# When user responds to clarification
class InteractiveRequestType(str, Enum):
    # ... existing ...
    clarification_response = "clarification_response"
```

**Backward Compatibility:**
- `type` field defaults to `None` (existing behavior)
- Frontend checks `type` field; if absent, treats as legacy response
- `clarification_response` requests are routed to continue previous flow

#### Phase 2-3: Goal & Plan Extensions

**New Endpoints:**
```python
# Goal management (optional, for debugging/admin)
@api_router.get("/session/{session_id}/goal")
async def get_session_goal(session_id: UUID) -> SessionGoal | None:
    """Get active goal for session."""

@api_router.post("/session/{session_id}/goal/abandon")
async def abandon_goal(session_id: UUID) -> dict:
    """Explicitly abandon current goal."""

# Plan inspection
@api_router.get("/plan/{plan_id}")
async def get_plan(plan_id: UUID) -> MultiStepPlan:
    """Get plan details including steps and status."""

@api_router.get("/plan/{plan_id}/steps")
async def get_plan_steps(plan_id: UUID) -> list[PlanStep]:
    """Get all steps with their execution status."""
```

**Extended Response Types:**
```python
class StructuredResponse(BaseModel):
    # ... existing + clarification fields ...
    
    # NEW: Multi-step plan support
    plan: Optional[MultiStepPlanResponse] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    
    # NEW: Checkpoint/iteration support
    suggested_actions: Optional[list[str]] = None
    verification: Optional[VerificationResult] = None

class MultiStepPlanResponse(BaseModel):
    """Plan data sent to frontend."""
    plan_id: UUID
    plan_summary: str
    steps: list[PlanStepResponse]
    status: str
    
class PlanStepResponse(BaseModel):
    """Step data for frontend display."""
    step_id: str
    tool: str
    description: str
    status: str  # pending, running, completed, failed
    depends_on: list[str]
```

#### Phase 5-6: Agent Response Types

**Unified Response Envelope:**
```python
class AgentResponseType(str, Enum):
    query = "query"  # Legacy: direct query result
    clarification = "clarification"  # Agent asking question
    plan_approval = "plan_approval"  # Multi-step plan for approval
    executing = "executing"  # Plan in progress
    checkpoint = "checkpoint"  # Results + "want to continue?"
    verification = "verification"  # "Did this answer your question?"
    complete = "complete"  # Goal achieved
    error = "error"  # Unrecoverable error

class StructuredResponse(BaseModel):
    type: AgentResponseType = AgentResponseType.query  # Default for backward compat
    
    # Type-specific payloads (only relevant one is populated)
    # query
    intent: Optional[str] = None
    sql: Optional[str] = None
    metadata: Optional[dict] = None
    
    # clarification
    clarification: Optional[ClarificationData] = None
    
    # plan_approval
    plan: Optional[MultiStepPlanResponse] = None
    
    # checkpoint / verification
    suggested_actions: Optional[list[str]] = None
    verification: Optional[VerificationResult] = None
    
    # All types can have a message
    message: Optional[str] = None
```

---

### Frontend Changes (apps/web)

#### Phase 1: Clarification UI

**New Component: `ClarificationPrompt.tsx`**
```typescript
interface ClarificationPromptProps {
  question: string;
  options?: string[];
  context?: string;
  onResponse: (response: string) => void;
  onSkip?: () => void;
}

const ClarificationPrompt: React.FC<ClarificationPromptProps> = ({
  question,
  options,
  context,
  onResponse,
  onSkip,
}) => {
  const [customResponse, setCustomResponse] = useState("");

  return (
    <Box className="clarification-prompt">
      {context && (
        <Typography variant="caption" color="text.secondary">
          {context}
        </Typography>
      )}
      
      <Typography variant="body1" sx={{ mb: 2 }}>
        {question}
      </Typography>

      {options ? (
        <Stack spacing={1}>
          {options.map((option) => (
            <Button
              key={option}
              variant="outlined"
              onClick={() => onResponse(option)}
            >
              {option}
            </Button>
          ))}
          <TextField
            placeholder="Or type your own response..."
            value={customResponse}
            onChange={(e) => setCustomResponse(e.target.value)}
            onKeyPress={(e) => e.key === "Enter" && onResponse(customResponse)}
          />
        </Stack>
      ) : (
        <TextField
          fullWidth
          placeholder="Your response..."
          value={customResponse}
          onChange={(e) => setCustomResponse(e.target.value)}
          onKeyPress={(e) => e.key === "Enter" && onResponse(customResponse)}
        />
      )}

      {onSkip && (
        <Button variant="text" onClick={onSkip} sx={{ mt: 1 }}>
          Skip and let agent decide
        </Button>
      )}
    </Box>
  );
};
```

**ChatSession Context Updates:**
```typescript
// In ChatSession context, handle clarification responses
const handleClarificationResponse = async (response: string) => {
  await sendRequest({
    request: response,
    request_type: "clarification_response",
    // Include reference to the clarification we're responding to
    refs: { clarification_id: currentClarification?.id },
  });
};

// In message rendering, detect clarification type
const renderMessage = (message: Message) => {
  if (message.structured_response?.type === "clarification") {
    return (
      <ClarificationPrompt
        question={message.structured_response.clarification.question}
        options={message.structured_response.clarification.options}
        onResponse={handleClarificationResponse}
      />
    );
  }
  // ... existing message rendering
};
```

#### Phase 2-3: Plan Visualization

**New Component: `MultiStepPlanCard.tsx`**
```typescript
interface MultiStepPlanCardProps {
  plan: MultiStepPlanResponse;
  onApprove: () => void;
  onReject: () => void;
  onModify: (feedback: string) => void;
}

const MultiStepPlanCard: React.FC<MultiStepPlanCardProps> = ({
  plan,
  onApprove,
  onReject,
  onModify,
}) => {
  return (
    <Card>
      <CardHeader title="Execution Plan" subheader={plan.plan_summary} />
      
      <CardContent>
        <Stepper orientation="vertical">
          {plan.steps.map((step, index) => (
            <Step key={step.step_id} completed={step.status === "completed"}>
              <StepLabel
                error={step.status === "failed"}
                icon={getStepIcon(step.tool, step.status)}
              >
                {step.description}
              </StepLabel>
              <StepContent>
                <Chip
                  size="small"
                  label={step.tool}
                  icon={<ToolIcon tool={step.tool} />}
                />
                {step.depends_on.length > 0 && (
                  <Typography variant="caption">
                    Depends on: {step.depends_on.join(", ")}
                  </Typography>
                )}
              </StepContent>
            </Step>
          ))}
        </Stepper>
      </CardContent>

      <CardActions>
        <Button color="primary" onClick={onApprove}>
          Approve & Execute
        </Button>
        <Button onClick={() => setShowModifyDialog(true)}>
          Suggest Changes
        </Button>
        <Button color="error" onClick={onReject}>
          Cancel
        </Button>
      </CardActions>
    </Card>
  );
};

// Helper to get icon based on tool type
const getStepIcon = (tool: string, status: string) => {
  const icons: Record<string, React.ReactNode> = {
    interactive_query: <StorageIcon />,
    data_analysis: <AnalyticsIcon />,
    schema_lookup: <SchemaIcon />,
    ask_user: <QuestionIcon />,
  };
  
  if (status === "running") return <CircularProgress size={20} />;
  if (status === "completed") return <CheckIcon color="success" />;
  if (status === "failed") return <ErrorIcon color="error" />;
  
  return icons[tool] || <PlayIcon />;
};
```

**Plan Progress Indicator:**
```typescript
// Show progress during multi-step execution
const PlanProgress: React.FC<{ currentStep: number; totalSteps: number }> = ({
  currentStep,
  totalSteps,
}) => (
  <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
    <LinearProgress
      variant="determinate"
      value={(currentStep / totalSteps) * 100}
      sx={{ flex: 1 }}
    />
    <Typography variant="caption">
      Step {currentStep} of {totalSteps}
    </Typography>
  </Box>
);
```

#### Phase 5-6: Checkpoint & Verification UI

**New Component: `CheckpointPrompt.tsx`**
```typescript
interface CheckpointPromptProps {
  message: string;
  suggestedActions?: string[];
  onContinue: (action: string) => void;
  onComplete: () => void;
  onClarify: () => void;
}

const CheckpointPrompt: React.FC<CheckpointPromptProps> = ({
  message,
  suggestedActions,
  onContinue,
  onComplete,
  onClarify,
}) => {
  return (
    <Box className="checkpoint-prompt">
      <Typography variant="body1">{message}</Typography>

      {suggestedActions && suggestedActions.length > 0 && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="subtitle2">Suggested next steps:</Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
            {suggestedActions.map((action) => (
              <Chip
                key={action}
                label={action}
                onClick={() => onContinue(action)}
                clickable
              />
            ))}
          </Stack>
        </Box>
      )}

      <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
        <Button variant="contained" onClick={onComplete}>
          This answers my question
        </Button>
        <Button variant="outlined" onClick={onClarify}>
          Let me clarify what I need
        </Button>
      </Stack>
    </Box>
  );
};
```

**Verification Dialog:**
```typescript
const VerificationDialog: React.FC<{
  open: boolean;
  verification: VerificationResult;
  onConfirm: () => void;
  onContinue: () => void;
  onClarify: () => void;
}> = ({ open, verification, onConfirm, onContinue, onClarify }) => {
  return (
    <Dialog open={open}>
      <DialogTitle>Did this answer your question?</DialogTitle>
      <DialogContent>
        {verification.evidence.length > 0 && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2">What I found:</Typography>
            <ul>
              {verification.evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </Box>
        )}

        {verification.gaps.length > 0 && (
          <Alert severity="info">
            <AlertTitle>Still unclear:</AlertTitle>
            {verification.gaps.join(", ")}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onConfirm} color="primary">
          Yes, I'm done
        </Button>
        <Button onClick={onContinue}>
          No, dig deeper
        </Button>
        <Button onClick={onClarify}>
          Let me rephrase
        </Button>
      </DialogActions>
    </Dialog>
  );
};
```

---

### Message Type Handling

**Updated Message Renderer:**
```typescript
// In ChatSession or GridSession message rendering
const renderStructuredResponse = (response: StructuredResponse) => {
  switch (response.type) {
    case "clarification":
      return (
        <ClarificationPrompt
          question={response.clarification!.question}
          options={response.clarification!.options}
          onResponse={handleClarificationResponse}
        />
      );

    case "plan_approval":
      return (
        <MultiStepPlanCard
          plan={response.plan!}
          onApprove={handlePlanApprove}
          onReject={handlePlanReject}
          onModify={handlePlanModify}
        />
      );

    case "executing":
      return (
        <Box>
          <PlanProgress
            currentStep={response.current_step!}
            totalSteps={response.total_steps!}
          />
          <Typography>Executing: {response.message}</Typography>
        </Box>
      );

    case "checkpoint":
      return (
        <CheckpointPrompt
          message={response.message!}
          suggestedActions={response.suggested_actions}
          onContinue={handleContinue}
          onComplete={handleComplete}
          onClarify={handleClarify}
        />
      );

    case "verification":
      return (
        <VerificationDialog
          open={true}
          verification={response.verification!}
          onConfirm={handleVerificationConfirm}
          onContinue={handleVerificationContinue}
          onClarify={handleVerificationClarify}
        />
      );

    case "complete":
      return (
        <Box>
          <Alert severity="success">
            <AlertTitle>Goal Achieved</AlertTitle>
            {response.message}
          </Alert>
          {/* Render final results */}
          {response.metadata && <QueryResultsTable data={response.metadata} />}
        </Box>
      );

    case "query":
    default:
      // Legacy behavior - render as before
      return <LegacyQueryResponse response={response} />;
  }
};
```

---

### OpenAPI Schema Updates

```yaml
# New schema additions for types.gen.ts generation

components:
  schemas:
    AgentResponseType:
      type: string
      enum:
        - query
        - clarification
        - plan_approval
        - executing
        - checkpoint
        - verification
        - complete
        - error

    ClarificationData:
      type: object
      required:
        - question
      properties:
        question:
          type: string
        options:
          type: array
          items:
            type: string
        context:
          type: string

    PlanStepResponse:
      type: object
      properties:
        step_id:
          type: string
        tool:
          type: string
        description:
          type: string
        status:
          type: string
          enum: [pending, running, completed, failed, skipped]
        depends_on:
          type: array
          items:
            type: string

    MultiStepPlanResponse:
      type: object
      properties:
        plan_id:
          type: string
          format: uuid
        plan_summary:
          type: string
        steps:
          type: array
          items:
            $ref: '#/components/schemas/PlanStepResponse'
        status:
          type: string

    VerificationResult:
      type: object
      properties:
        goal_achieved:
          type: boolean
        confidence:
          type: number
        evidence:
          type: array
          items:
            type: string
        gaps:
          type: array
          items:
            type: string
        suggested_next_steps:
          type: array
          items:
            type: string
```

---

### Frontend Files Summary

**New Files:**
```
apps/web/app/components/agent/
├── ClarificationPrompt.tsx
├── MultiStepPlanCard.tsx
├── PlanProgress.tsx
├── CheckpointPrompt.tsx
├── VerificationDialog.tsx
└── index.ts
```

**Modified Files:**
```
apps/web/app/contexts/ChatSession/index.tsx
apps/web/app/contexts/GridSession/index.tsx
apps/web/app/api/apegpt/types.gen.ts  (auto-generated)
apps/web/app/components/QueryPlanCard.tsx  (extend for multi-step)
```

---

## Files Summary

### New Files
```
fm_app/workers/agent/
├── __init__.py
├── orchestrator.py
├── cost_guard.py
├── verification.py
├── tools/
│   ├── __init__.py
│   ├── base.py
│   ├── interactive_query.py
│   ├── data_analysis.py
│   ├── schema_lookup.py
│   └── ask_user.py
└── registry.py

fm_app/workers/interactive_flow/
├── goal_tracker.py
├── multi_step_planner.py
└── step_executor.py

fm_app/db/
└── goal_db.py

packages/resources/.../
├── multi_step_planner/
│   └── prompt.md
└── verification/
    └── prompt.md

alembic/versions/
└── xxx_add_session_goals.py
```

### Modified Files
```
fm_app/api/model.py
fm_app/config.py
fm_app/workers/interactive_flow/__init__.py
fm_app/workers/interactive_flow/intent_analyzer.py
fm_app/workers/interactive_flow/setup.py
packages/resources/.../planner/prompt.md
apps/web/app/contexts/ChatSession/
```
