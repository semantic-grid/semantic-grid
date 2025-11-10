# V2 Agent Architecture

## Overview

V2 introduces a **ReAct-based agentic architecture** using the OpenAI Agents SDK, replacing V1's deterministic multi-step flows with autonomous reasoning and tool use.

## Key Architectural Shift

### V1: Deterministic Flows
- Explicit step-by-step orchestration
- Custom `AIModel` implementations
- LangChain/LangGraph for flow control
- Pre-fetched MCP resources injected into prompts
- Predictable, controlled execution path

### V2: ReAct Agent Pattern
- **Autonomous reasoning** using OpenAI Agents SDK
- **Dynamic tool discovery** and execution
- **Thought → Action → Observation** cycles
- MCP servers exposed as tools (not pre-fetched)
- Agent decides when and how to use tools

## Architecture Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Request                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    V2 API (/api/v2/...)                         │
│  - Message-based sessions                                       │
│  - SSE for real-time updates                                    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│               Celery Worker (wrk_process_message_v2)            │
│  - Initializes OpenAI Agent with MCP tools                      │
│  - Runs Runner.run(agent, message)                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   OpenAI Agent (ReAct Loop)                     │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 1. THOUGHT: Classify intent, plan tool usage           │  │
│  └─────────────────────┬───────────────────────────────────┘  │
│                        │                                       │
│  ┌─────────────────────▼───────────────────────────────────┐  │
│  │ 2. ACTION: Call MCP tools (get_prompt_bundle,          │  │
│  │            execute_query, explain_analyze)              │  │
│  └─────────────────────┬───────────────────────────────────┘  │
│                        │                                       │
│  ┌─────────────────────▼───────────────────────────────────┐  │
│  │ 3. OBSERVATION: Process tool results                    │  │
│  └─────────────────────┬───────────────────────────────────┘  │
│                        │                                       │
│                        │ ← Loop until complete                │
│                        │                                       │
│  ┌─────────────────────▼───────────────────────────────────┐  │
│  │ 4. FINAL ANSWER: Respond to user                        │  │
│  └─────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                       MCP Servers                               │
│  - db-meta: Schema info, validation, query analysis            │
│  - db-ref: Entity reference data (optional)                    │
└─────────────────────────────────────────────────────────────────┘
```

## ReAct Pattern Implementation

### What is ReAct?

**ReAct = Reasoning + Acting**

A paradigm where the agent:
1. **Reasons** about what to do (explicit thinking)
2. **Acts** by calling tools
3. **Observes** the results
4. **Repeats** until it has enough information to answer

### Example Flow

```
User: "Can you answer questions about copy-trading on Solana?"

Agent Reasoning Loop:
┌─────────────────────────────────────────────────────────┐
│ THOUGHT: This is a capabilities question. I need to     │
│          check if we have relevant data.                │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│ ACTION: get_prompt_bundle(profile="wh_v2")              │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│ OBSERVATION: Found enriched_trades table with P&L data  │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│ FINAL ANSWER: "Yes! We have copy-trading data..."       │
└─────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Prompt Pack System

**Location**: `packages/resources/fm_app/system-pack/v2.0.0/`

**Structure**:
```
v2.0.0/
├── manifest.yaml          # Defines slots and MCP requirements
└── slots/
    └── agent_v2/
        └── prompt.md      # ReAct-style agent instructions
```

**Manifest** (`manifest.yaml`):
- Defines the `agent_v2` slot
- Specifies required MCP servers (db-meta)
- Lists inputs/outputs (for documentation)

**Prompt** (`slots/agent_v2/prompt.md`):
- Contains ReAct framework instructions
- Provides example reasoning flows
- Defines available MCP tools
- Sets behavioral guidelines

### 2. Worker (V2AgentWorker)

**Location**: `apps/fm-app/fm_app/workers/v2/worker_v2.py`

**Responsibilities**:
- Load agent instructions from prompt pack
- Initialize MCP server connections
- Create OpenAI Agent with tools
- Run agent via `Runner.run()`
- Parse agent output into messages
- Save results to database

**Key Methods**:
- `initialize()` - Load prompt, connect MCP servers, create agent
- `process_message()` - Execute agent reasoning loop
- `_parse_agent_output()` - Extract results from agent response

### 3. OpenAI Agents SDK Integration

**Package**: `openai-agents>=0.0.14`

**Core Classes**:
- `Agent` - Represents the AI agent with instructions and tools
- `Runner` - Executes the agent's reasoning loop
- `MCPServerSse` - MCP server connection for tool use

**Agent Configuration**:
```python
agent = Agent[dict](
    name="Semantic Grid Assistant",
    instructions=<loaded from prompt pack>,
    model="gpt-4o",
    mcp_servers=[dbmeta_mcp_server],
    model_settings=ModelSettings(
        temperature=0,
        parallel_tool_calls=True,
        max_tokens=4096
    )
)
```

**Execution**:
```python
result = await Runner.run(
    agent,
    user_message,
    context=conversation_history
)
```

### 4. MCP Tools

**Available to Agent**:

1. **`get_prompt_bundle(profile, resources)`**
   - Gets database schema information
   - Returns table structures, column info
   - Provides query examples

2. **`execute_query(sql, profile)`**
   - Executes SQL against the database
   - Returns query results
   - Limited to 100 rows by default

3. **`explain_analyze(sql, profile)`**
   - Validates SQL syntax
   - Estimates query complexity
   - Returns execution plan

## Message Flow

### 1. User Sends Message
```http
POST /api/v2/sessions/{session_id}/messages
{
  "role": "user",
  "kind": "chat",
  "content": "list all tables in the database"
}
```

### 2. Worker Processes Message
- Creates `WorkerMessageRequest`
- Dispatches to Celery: `wrk_process_message_v2`

### 3. Agent Executes ReAct Loop
```
Agent thinks: "This is a data query. I need schema info."
Agent calls: get_prompt_bundle(profile="wh_v2")
Agent observes: [schema information]
Agent thinks: "Now I'll query for tables."
Agent calls: execute_query(sql="SHOW TABLES")
Agent observes: [table list]
Agent responds: "Here are all tables: ..."
```

### 4. Results Saved & Streamed
- Assistant message saved to database
- SSE events streamed to frontend:
  - `message_update` (status changes)
  - `agent_status` (tool calls, thinking steps)

### 5. Frontend Updates
- React contexts receive SSE events
- Messages displayed in notebook UI
- Query results shown in data grid (if applicable)

## Comparison: V1 vs V2

| Aspect | V1 | V2 |
|--------|----|----|
| **Control** | Explicit orchestration | Autonomous agent |
| **Flow** | Deterministic steps | Dynamic reasoning |
| **Tools** | Pre-fetched resources | On-demand tool calls |
| **Framework** | Custom AIModel + LangChain | OpenAI Agents SDK |
| **Prompting** | Per-step templates | Single ReAct prompt |
| **Flexibility** | Fixed flow paths | Agent adapts to context |
| **Debuggability** | Clear step boundaries | Agent's internal reasoning |
| **MCP Usage** | PromptAssembler fetches | Agent calls as tools |

## Benefits of V2 Approach

1. **More Natural Conversations**
   - Agent can handle varied question types
   - Adapts its approach based on context
   - Multi-turn reasoning within single request

2. **Reduced Code Complexity**
   - No manual flow orchestration
   - SDK handles tool loop
   - Single prompt vs. multiple templates

3. **Better Scalability**
   - Easy to add new MCP tools
   - Agent learns to use them from descriptions
   - No code changes for new tool types

4. **Explicit Reasoning**
   - Agent shows its thinking
   - Users see the decision process
   - Easier to understand behavior

## Trade-offs

1. **Less Predictable**
   - Agent might skip steps
   - Reasoning can vary
   - Harder to guarantee specific behavior

2. **Prompt-Dependent**
   - System behavior driven by prompt quality
   - Requires careful prompt engineering
   - Less explicit error handling

3. **Cost**
   - Multiple LLM calls per request
   - Reasoning tokens add cost
   - Need to balance thoroughness vs. efficiency

## Future Enhancements

1. **Multi-Agent Collaboration**
   - Specialized agents for different tasks
   - Planner agent + executor agents
   - Agent handoffs for complex queries

2. **Memory & Learning**
   - Conversation context across sessions
   - User preference learning
   - Query pattern recognition

3. **Enhanced Observability**
   - Detailed reasoning traces
   - Tool call analytics
   - Performance metrics per step

4. **Guardrails**
   - Query complexity limits
   - Automatic query optimization
   - Safety checks before execution

## References

- [ReAct Paper](https://arxiv.org/abs/2210.03629)
- [OpenAI Agents SDK Documentation](https://openai.github.io/openai-agents-python/)
- [MCP Protocol Specification](https://spec.modelcontextprotocol.io/)
