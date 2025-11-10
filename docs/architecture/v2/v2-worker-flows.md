# V2 Worker Flows Architecture

## Overview

V2 workers represent a fundamental shift from v1's request-response model to a **message-based processing model**. This enables:
- Multiple responses per user message
- Progressive streaming updates
- Complex multi-step workflows
- Slash command support
- Agentic planning and approval

## V1 vs V2 Comparison

### V1 Architecture (Request-Response)
```
User Request → Worker → Single Structured Response → Update DB
```

**Characteristics:**
- 1:1 mapping (request → response)
- Synchronous processing
- Fixed response structure (StructuredResponse)
- Flow = "how to generate SQL and response"

### V2 Architecture (Message Processing)
```
User Message → Worker → [Message, Message, Message, ...] → Insert to DB
```

**Characteristics:**
- 1:N mapping (message → messages)
- Can stream progress updates
- Flexible message types (chat, query_result, chart, notification, etc.)
- Flow = "how to process and respond to messages"

## V2 Flow Types

V2 flows define **processing strategies**, not task types. They determine HOW messages are processed and what kinds of messages are emitted.

### Core Flows

#### 1. DIRECT
**Purpose:** Simple, single-turn interactions
**Use case:** Basic chat, quick questions, simple queries

```
User: "What is the total supply of USDC?"
  ↓
[DIRECT flow]
  ↓
Assistant: "The total supply of USDC is 32.5B tokens."
```

**Message emission:**
- 1 user message in
- 1 assistant message out
- Optional: 1 query_result message if SQL was executed

**Processing:**
1. Analyze user message
2. Generate response (with optional SQL)
3. Execute query if needed
4. Emit response message

---

#### 2. ITERATIVE
**Purpose:** Multi-turn refinement with validation loops
**Use case:** Complex queries needing clarification, SQL refinement

```
User: "Show me token transfers"
  ↓
[ITERATIVE flow]
  ↓
Assistant: "I need more details. Which token? What time range?"
  ↓
User: "USDC, last 24 hours"
  ↓
[ITERATIVE continues]
  ↓
Assistant: "Here are USDC transfers from the last 24 hours..."
```

**Message emission:**
- Multiple back-and-forth messages
- Can emit clarification messages
- Progressive refinement of SQL

**Processing:**
1. Analyze user message
2. Identify ambiguities/missing info
3. Emit clarification request (if needed)
4. Collect user response
5. Refine and execute
6. Emit result

---

#### 3. AGENTIC
**Purpose:** Plan-based execution with user approval
**Use case:** Complex multi-step analysis, data pipelines

```
User: "Analyze USDC liquidity across DEXs and create a report"
  ↓
[AGENTIC flow]
  ↓
Assistant: [execution_plan message]
  "I'll do this in 4 steps:
   1. Query USDC pools from major DEXs
   2. Calculate liquidity metrics
   3. Generate comparison charts
   4. Summarize findings
   Approve?"
  ↓
User: [plan_approval message] "Yes, proceed"
  ↓
[AGENTIC executes]
  ↓
Assistant: [plan_step message] "Step 1: Querying pools..." (transient)
Assistant: [query_result message] "Found 127 USDC pools"
Assistant: [plan_step message] "Step 2: Calculating metrics..." (transient)
Assistant: [table message] "Liquidity by DEX"
Assistant: [plan_step message] "Step 3: Generating charts..." (transient)
Assistant: [chart message] "Liquidity distribution"
Assistant: [chat message] "Analysis complete. Key findings: ..."
```

**Message emission:**
- 1 execution_plan (persistent)
- Multiple plan_step messages (transient, for UI progress)
- Multiple result messages (query_result, table, chart)
- Final summary message

**Processing:**
1. Decompose request into steps
2. Emit execution plan
3. Wait for approval
4. Execute steps sequentially
5. Emit progress updates (transient)
6. Emit results (persistent)
7. Emit summary

---

#### 4. STREAMING
**Purpose:** Progressive message emission for long-running tasks
**Use case:** Large queries, complex analysis, real-time feedback

```
User: "Generate a comprehensive DeFi market report"
  ↓
[STREAMING flow]
  ↓
Assistant: [notification] "Starting analysis..." (transient)
Assistant: [chat] "Analyzing TVL trends..."
Assistant: [chart] "TVL by Protocol"
Assistant: [chat] "Analyzing user activity..."
Assistant: [table] "Top 10 Protocols by Active Users"
Assistant: [chat] "Analyzing transaction volumes..."
...
Assistant: [chat] "Report complete. Summary: ..."
```

**Message emission:**
- Multiple messages emitted as they're ready
- Notifications for progress (transient)
- Results as they complete (persistent)

**Processing:**
1. Break task into chunks
2. Emit notification of start
3. Process chunks independently
4. Emit each result as it completes
5. Emit final summary

---

### Specialized Flows

#### 5. SLASH_COMMAND
**Purpose:** Handle special commands
**Use case:** `/help`, `/new`, `/analyze`, `/export`

```
User: "/help query syntax"
  ↓
[SLASH_COMMAND flow]
  ↓
Assistant: "SQL Query Syntax Help:
  - Use SELECT ... FROM ... WHERE ...
  - Available functions: SUM, AVG, COUNT...
  ..."
```

**Message emission:**
- 1 command interpretation
- 1 or more response messages
- May emit discovery/notification messages

**Processing:**
1. Parse slash command
2. Route to command handler
3. Execute command logic
4. Emit response

**Supported commands:**
- `/help [topic]` - Get help
- `/new` - Start new conversation
- `/analyze <query_id>` - Deep analysis of query
- `/discover [schema]` - Explore database schema
- `/export <format>` - Export results

---

#### 6. QUERY_BUILDER
**Purpose:** Robust SQL generation with validation
**Use case:** Complex queries needing validation, optimization

```
User: "Show top 100 wallets by USDC balance"
  ↓
[QUERY_BUILDER flow]
  ↓
[Generates SQL, validates, optimizes]
  ↓
Assistant: [chat] "I'll query wallet balances..."
Assistant: [query_result] "Query returned 100 rows"
Assistant: [table] [Data grid with results]
```

**Message emission:**
- Optional: SQL preview (if user requested)
- query_result message with execution metadata
- table message with data

**Processing:**
1. Generate SQL from natural language
2. Validate with db-meta (EXPLAIN ANALYZE)
3. Optimize if needed
4. Execute query
5. Emit results with metadata

---

#### 7. DATA_ANALYSIS
**Purpose:** Query + analysis + visualization
**Use case:** Analytical questions requiring insights

```
User: "What's the trend in USDC transfers?"
  ↓
[DATA_ANALYSIS flow]
  ↓
Assistant: [chat] "Analyzing USDC transfer trends..."
Assistant: [query_result] "Queried 1.2M transfers"
Assistant: [chart] "Transfer Volume Over Time"
Assistant: [chat] "Key insights:
  - 15% increase in daily volume
  - Peak activity on weekends
  - Top destination: Uniswap V3"
```

**Message emission:**
- Query result
- Visualization (chart/table)
- Analysis summary

**Processing:**
1. Generate analytical SQL
2. Execute query
3. Analyze results (with LLM)
4. Generate visualizations
5. Emit insights

---

#### 8. DISCOVERY
**Purpose:** Schema exploration and suggestions
**Use case:** Users exploring available data

```
User: "What data do you have about Uniswap?"
  ↓
[DISCOVERY flow]
  ↓
Assistant: [discovery message]
  "I have these Uniswap-related tables:
  - uniswap_v3_swaps (10M rows)
  - uniswap_v3_pools (5K rows)
  - uniswap_v3_positions (50K rows)
  
  Example queries:
  - Show recent swaps
  - Top pools by volume
  - Active liquidity providers"
```

**Message emission:**
- Discovery results
- Example queries
- Schema descriptions

**Processing:**
1. Search schema metadata
2. Find relevant tables/columns
3. Generate example queries
4. Emit structured discovery response

---

### Hybrid Flows

#### 9. INTERACTIVE
**Purpose:** Smart routing based on intent analysis
**Use case:** General-purpose conversational interface

```
User: "hello"
  ↓
[INTERACTIVE → routes to DIRECT flow]
  ↓
Assistant: "Hi! How can I help you explore crypto data?"

User: "/help"
  ↓
[INTERACTIVE → routes to SLASH_COMMAND flow]
  ↓
Assistant: "Here's what I can do: ..."

User: "Show USDC transfers"
  ↓
[INTERACTIVE → routes to QUERY_BUILDER flow]
  ↓
Assistant: [Results]

User: "Analyze the trend"
  ↓
[INTERACTIVE → routes to DATA_ANALYSIS flow]
  ↓
Assistant: [Analysis + Charts]
```

**Message emission:**
- Depends on sub-flow

**Processing:**
1. Analyze intent (LLM or pattern match)
2. Route to appropriate specialized flow
3. Delegate processing
4. Return results

**Intent categories:**
- `greeting` → DIRECT
- `help_request` → DISCOVERY or DIRECT
- `slash_command` → SLASH_COMMAND
- `query_request` → QUERY_BUILDER
- `analysis_request` → DATA_ANALYSIS
- `complex_task` → AGENTIC

---

#### 10. CONVERSATIONAL
**Purpose:** Multi-turn dialogue with full context
**Use case:** Back-and-forth refinement, follow-ups

```
User: "Show me DeFi TVL"
  ↓
Assistant: [Results for all DeFi protocols]
  ↓
User: "Just Ethereum"
  ↓
[CONVERSATIONAL - understands "just Ethereum" refers to previous query]
  ↓
Assistant: [Filtered results for Ethereum DeFi]
  ↓
User: "Compare to last month"
  ↓
[CONVERSATIONAL - adds time comparison]
  ↓
Assistant: [Comparison chart]
```

**Message emission:**
- Builds on previous messages
- Can emit multiple types

**Processing:**
1. Load recent message history
2. Understand references to previous messages
3. Build on previous context
4. Route to appropriate sub-flow
5. Emit contextual response

---

## Flow Selection Strategy

### How to Choose Flow Type?

The v2 worker uses a **strategy** to determine which flow to use:

#### 1. KIND_DISPATCH (Simple routing)
```python
if message.kind == MessageKind.SLASH_COMMAND:
    flow = FlowTypeV2.SLASH_COMMAND
elif message.kind == MessageKind.CHAT:
    flow = FlowTypeV2.DIRECT  # default
```

#### 2. PATTERN_MATCH (Regex-based)
```python
if message.content.startswith("/"):
    flow = FlowTypeV2.SLASH_COMMAND
elif "analyze" in message.content.lower():
    flow = FlowTypeV2.DATA_ANALYSIS
```

#### 3. INTENT_BASED (LLM analysis)
```python
intent = await analyze_intent(message.content)
if intent == "complex_multi_step":
    flow = FlowTypeV2.AGENTIC
elif intent == "analytical_question":
    flow = FlowTypeV2.DATA_ANALYSIS
elif intent == "simple_query":
    flow = FlowTypeV2.QUERY_BUILDER
```

#### 4. SMART_ROUTING (Combination)
```python
# 1. Check for slash command
if message.content.startswith("/"):
    return FlowTypeV2.SLASH_COMMAND

# 2. Analyze intent
intent = await analyze_intent(message.content, context=recent_messages)

# 3. Route based on intent + complexity
if intent.requires_approval:
    return FlowTypeV2.AGENTIC
elif intent.requires_analysis:
    return FlowTypeV2.DATA_ANALYSIS
elif intent.requires_refinement:
    return FlowTypeV2.ITERATIVE
else:
    return FlowTypeV2.DIRECT
```

---

## Implementation Architecture

### Worker Structure

```
workers/
├── v1/                              # Existing workers (unchanged)
│   ├── legacy/
│   ├── experimental/
│   └── interactive_flow/
│
├── v2/                              # New message-based workers
│   ├── model.py                     # V2 models (WorkerMessageRequest, etc.)
│   ├── worker_v2.py                 # Main v2 task dispatcher
│   ├── base_flow.py                 # Base class for all flows
│   │
│   ├── flows/                       # Flow implementations
│   │   ├── direct_flow.py
│   │   ├── iterative_flow.py
│   │   ├── agentic_flow.py
│   │   ├── streaming_flow.py
│   │   ├── query_builder_flow.py
│   │   ├── data_analysis_flow.py
│   │   ├── discovery_flow.py
│   │   ├── slash_command_flow.py
│   │   ├── interactive_flow.py
│   │   └── conversational_flow.py
│   │
│   ├── handlers/                    # Message kind handlers
│   │   ├── chat_handler.py
│   │   ├── command_handler.py
│   │   └── query_handler.py
│   │
│   └── utils/                       # Shared utilities
│       ├── intent_analyzer.py
│       ├── message_builder.py
│       └── context_manager.py
│
└── worker.py                        # Main dispatcher (both v1 and v2)
```

### Base Flow Class

```python
class BaseFlowV2(ABC):
    """Base class for all v2 flows."""
    
    def __init__(self, llm, db_wh, db):
        self.llm = llm
        self.db_wh = db_wh
        self.db = db
    
    @abstractmethod
    async def process(
        self, request: WorkerMessageRequest
    ) -> WorkerMessageResponse:
        """Process a message and emit responses."""
        pass
    
    async def emit_message(
        self, content, kind: MessageKind, **kwargs
    ) -> Message:
        """Helper to create a message."""
        pass
    
    async def execute_query(
        self, sql: str, profile: str
    ) -> MessageQuery:
        """Helper to execute and track SQL."""
        pass
```

### Task Dispatcher

```python
@app.task(name="wrk_process_message_v2")
def wrk_process_message_v2(args):
    return asyncio.get_event_loop().run_until_complete(
        _wrk_process_message_v2(args)
    )

async def _wrk_process_message_v2(args):
    request = WorkerMessageRequest(**args)
    
    # Initialize LLM
    llm = get_llm(request.model)
    
    # Get flow instance
    flow_class = FLOW_REGISTRY[request.flow]
    flow = flow_class(llm, db_wh, db)
    
    # Process message
    response = await flow.process(request)
    
    # Save messages to DB
    for message in response.messages:
        await create_message(
            session_id=request.session_id,
            user_owner=request.user,
            msg_request=message,
            db=db
        )
    
    # Save queries
    for query in response.queries:
        await create_message_query(query=query, db=db)
    
    return response
```

---

## Migration Strategy

### Phase 1: Create V2 Foundation
- ✅ Create v2 models (`model.py`)
- ✅ Create base flow class
- ✅ Implement DIRECT flow (simplest)
- ✅ Test with v2 API

### Phase 2: Add Specialized Flows
- Implement QUERY_BUILDER (mirrors v1 simple flow)
- Implement SLASH_COMMAND
- Implement DISCOVERY
- Test each independently

### Phase 3: Add Advanced Flows
- Implement ITERATIVE
- Implement DATA_ANALYSIS
- Implement AGENTIC
- Implement STREAMING

### Phase 4: Hybrid & Intelligence
- Implement INTERACTIVE (with routing)
- Implement CONVERSATIONAL
- Add intent analysis
- Add smart routing

### Phase 5: V1 Coexistence
- Keep v1 workers running
- Gradually migrate v1 sessions to v2
- Deprecate v1 when ready

---

## Summary

V2 flows represent a **paradigm shift** from monolithic request processing to **flexible message processing**. This enables:

✅ **Multiple responses** per user message
✅ **Progressive updates** via streaming
✅ **Complex workflows** with approval steps
✅ **Slash commands** as first-class citizens
✅ **Rich message types** (charts, tables, plans)
✅ **Transient messages** for UI feedback without DB bloat

The architecture is designed to be **extensible** - new flows and message types can be added without changing existing code.
