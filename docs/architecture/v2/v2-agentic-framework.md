# V2 Agentic Framework Design

## Philosophy: Tool-Calling Agents Over Rigid Flows

V2 abandons rigid flow structures in favor of **flexible, tool-equipped agents** that dynamically determine their own execution paths. Instead of pre-defined flows like "simple", "multistep", "interactive", we give agents:

1. **Tools** (MCP servers, SQL execution, visualization generators)
2. **Instructions** (what they can do, how to behave)
3. **Context** (conversation history, schema, previous results)
4. **Freedom** (let the LLM decide the best approach)

## Recommended Frameworks

### Option 1: Anthropic Agents SDK ⭐ (Recommended)
**Pros:**
- ✅ You're already using it (`agent.py`)
- ✅ Built by Anthropic, optimized for Claude
- ✅ Native MCP support
- ✅ Typed outputs (Pydantic models)
- ✅ Streaming support
- ✅ Simple, lightweight

**Architecture:**
```python
from agents import Agent, ModelSettings
from agents.mcp import MCPServerSse

agent = Agent[Message](  # Typed to emit Message objects
    name="Semantic Grid Assistant",
    instructions="""You are a data analysis assistant...
                    Use tools to query databases, generate charts...""",
    model="claude-3-7-sonnet-20250219",
    mcp_servers=[dbmeta_mcp, dbref_mcp],
    output_type=Message,  # Returns v2 Message objects!
)

# Process user message
response = await agent.run(user_message)
```

**Why this wins:**
- Already integrated
- Natural fit for v2 Message architecture
- Claude excels at tool use and structured outputs
- MCP servers already built

---

### Option 2: LangGraph (Current Experiment)
**Pros:**
- ✅ You're experimenting with it (`langgraph_flow.py`)
- ✅ Explicit graph structure
- ✅ State management
- ✅ Persistence and checkpointing
- ✅ Human-in-the-loop approval

**Cons:**
- ⚠️ More complex
- ⚠️ Requires explicit graph definition
- ⚠️ Heavier framework

**Use case:** Best for complex, **multi-agent** scenarios or when you need **explicit control flow** (e.g., approval gates, parallel execution branches)

---

### Option 3: OpenAI Assistants API
**Pros:**
- ✅ Fully managed (no infrastructure)
- ✅ Built-in thread management
- ✅ Code interpreter included

**Cons:**
- ⚠️ Vendor lock-in (OpenAI only)
- ⚠️ Less control over execution
- ⚠️ Pricing model

---

### Option 4: Langchain Agents (Legacy)
**Not recommended** - Being replaced by LangGraph

---

## Recommended: Anthropic Agents SDK + MCP

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                  V2 Worker                          │
│                                                     │
│  ┌──────────────────────────────────────────────┐ │
│  │         Anthropic Agent                      │ │
│  │  - Instructions (persona, capabilities)      │ │
│  │  - Model: Claude Sonnet 3.7                  │ │
│  │  - Output Type: List[Message]                │ │
│  └──────────────┬───────────────────────────────┘ │
│                 │                                   │
│                 │ has access to                     │
│                 ▼                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │          MCP Tools                           │ │
│  │  • db-meta (schema, validation)              │ │
│  │  • db-ref (examples, references)             │ │
│  │  • solana-db (query execution)               │ │
│  │  • chart-generator (visualizations)          │ │
│  │  • data-analyzer (insights)                  │ │
│  └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Implementation

```python
# v2/worker_v2.py

from agents import Agent, ModelSettings
from agents.mcp import MCPServerSse
from fm_app.api.v2.model import Message, MessageKind, MessageRole

class V2AgentWorker:
    """V2 worker using Anthropic Agents SDK."""
    
    def __init__(self):
        self.dbmeta_mcp = None
        self.dbref_mcp = None
        self.agent = None
    
    async def initialize(self):
        """Initialize MCP servers and agent."""
        
        # Connect to MCP servers
        self.dbmeta_mcp = MCPServerSse(
            name="DB Metadata",
            params={"url": f"{settings.dbmeta}sse"},
            cache_tools_list=True
        )
        await self.dbmeta_mcp.connect()
        
        self.dbref_mcp = MCPServerSse(
            name="DB Reference Data",
            params={"url": f"{settings.dbref}sse"},
            cache_tools_list=True
        )
        await self.dbref_mcp.connect()
        
        # Create agent with v2 instructions
        self.agent = Agent[dict](  # Returns dict we convert to Messages
            name="Semantic Grid Assistant",
            instructions=await self._load_instructions(),
            model=settings.anthropic_llm_name,
            model_settings=ModelSettings(
                temperature=0,
                parallel_tool_calls=True
            ),
            mcp_servers=[self.dbmeta_mcp, self.dbref_mcp]
        )
    
    async def _load_instructions(self) -> str:
        """Load agent instructions from prompt packs."""
        # Use PromptAssembler to load v2 instructions
        assembler = PromptAssembler(
            slot_name="agent_v2",
            client="default",
            env="prod"
        )
        return await assembler.assemble()
    
    async def process_message(
        self, 
        request: WorkerMessageRequest
    ) -> WorkerMessageResponse:
        """Process a user message and return assistant messages."""
        
        # Build context for agent
        context = self._build_context(request)
        
        # Run agent
        result = await self.agent.run(
            message=request.content,
            context=context
        )
        
        # Convert agent output to Messages
        messages = self._parse_agent_output(result, request)
        
        return WorkerMessageResponse(
            messages=messages,
            success=True
        )
    
    def _build_context(self, request: WorkerMessageRequest) -> dict:
        """Build context from recent messages."""
        return {
            "session_id": str(request.session_id),
            "user_id": request.user,
            "recent_messages": [
                {
                    "role": msg.role.value,
                    "content": msg.content
                }
                for msg in request.recent_messages[-10:]  # Last 10 messages
            ],
            "database_profile": request.db.value,
        }
    
    def _parse_agent_output(
        self, 
        result, 
        request: WorkerMessageRequest
    ) -> List[Message]:
        """
        Parse agent output into v2 Message objects.
        
        The agent may:
        - Return text → single chat message
        - Use tools → query_result messages
        - Generate charts → chart messages
        - Create tables → table messages
        """
        messages = []
        
        # Main response text
        if result.content:
            messages.append(Message.create_text(
                text=result.content,
                session_id=request.session_id,
                role=MessageRole.ASSISTANT,
                kind=MessageKind.CHAT
            ))
        
        # Tool results (SQL queries, charts, etc.)
        for tool_result in result.tool_results or []:
            if tool_result.tool_name == "execute_query":
                # Create query_result message
                messages.append(Message(
                    session_id=request.session_id,
                    role=MessageRole.ASSISTANT,
                    kind=MessageKind.QUERY_RESULT,
                    content=tool_result.output,
                    metadata={
                        "sql": tool_result.input.get("sql"),
                        "row_count": len(tool_result.output.get("rows", []))
                    }
                ))
            
            elif tool_result.tool_name == "generate_chart":
                # Create chart message
                messages.append(Message.create_chart(
                    chart_data=tool_result.output,
                    session_id=request.session_id,
                    role=MessageRole.ASSISTANT
                ))
        
        return messages
```

---

## Agent Instructions Structure

Instead of rigid flows, we define **capabilities** in instructions:

```yaml
# packages/resources/fm_app/system-pack/v2.0.0/slots/agent_v2/prompt.md

You are a data analysis assistant for crypto and blockchain data.

## Capabilities

You have access to these tools via MCP:

### Query Tools
- `describe_provider`: Get database schema information
- `get_prompt_bundle`: Get examples and documentation
- `execute_query`: Run SQL queries on the warehouse
- `explain_analyze`: Validate SQL before execution

### Analysis Tools
- `analyze_data`: Generate insights from query results
- `generate_chart`: Create visualizations (bar, line, pie)
- `export_data`: Export results (CSV, JSON)

### Discovery Tools
- `search_schema`: Find relevant tables/columns
- `get_examples`: Get example queries for a topic

## Behavior

1. **Understand Intent**: Always clarify ambiguous requests
2. **Validate SQL**: Use `explain_analyze` before executing queries
3. **Progressive Disclosure**: For complex tasks, break into steps
4. **Rich Responses**: Use appropriate message types:
   - Text for explanations
   - query_result for data
   - charts for visualizations
   - tables for structured data

5. **Error Handling**: If a query fails, explain why and suggest fixes

## Response Format

You should emit responses that will become Messages:

**Simple queries:**
```json
{
  "text": "Here are the top 10 tokens by volume:",
  "query": {
    "sql": "SELECT ...",
    "rows": [...]
  }
}
```

**Complex analysis:**
```json
{
  "steps": [
    {"text": "First, I'll query the top tokens..."},
    {"query": {"sql": "...", "rows": [...]}},
    {"text": "Now analyzing the trends..."},
    {"chart": {"type": "line", "data": ...}},
    {"text": "Key insights: ..."}
  ]
}
```

## Multi-Step Tasks

For complex requests requiring approval:

1. Generate a plan
2. Present it to the user
3. Wait for approval
4. Execute steps
5. Report progress
6. Summarize results

Example:
```
User: "Analyze DeFi TVL trends and create a report"

Agent Response:
"I'll create a comprehensive DeFi TVL analysis report. Here's my plan:

1. Query TVL data across major protocols
2. Calculate trend statistics
3. Generate comparison charts
4. Identify key insights
5. Create summary report

Approve?"
```

Wait for user approval, then execute.
```

---

## Slash Commands as Tool Calls

Slash commands become **special instructions** the agent recognizes:

```python
# Agent recognizes these patterns automatically

/help → Use `get_documentation` tool
/discover → Use `search_schema` tool
/analyze <query_id> → Use `deep_analyze_query` tool
/export csv → Use `export_data` tool with format=csv
```

No special command parsing needed - the agent figures it out!

---

## Multi-Agent Scenarios (Optional - LangGraph)

For truly complex workflows requiring **multiple specialized agents**:

```
┌────────────────────────────────────────────────┐
│           Orchestrator Agent                   │
│  (Routes to specialist agents)                 │
└────────────┬───────────────────────────────────┘
             │
             ├──────────────┬──────────────┬───────────────┐
             ▼              ▼              ▼               ▼
      ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
      │  Query   │   │ Analysis │   │   Chart  │   │ Discovery│
      │  Agent   │   │  Agent   │   │  Agent   │   │  Agent   │
      └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

Use LangGraph for this advanced scenario with state management.

---

## Implementation Roadmap

### Phase 1: Single Agent (Anthropic SDK)
✅ **Week 1**: Setup
- Create v2 worker structure
- Initialize Anthropic Agent with MCP servers
- Load instructions from prompt packs
- Wire up to v2 API

✅ **Week 2**: Basic Functionality
- Process user messages
- Execute SQL queries via MCP
- Return chat + query_result messages
- Test end-to-end

✅ **Week 3**: Rich Messages
- Add chart generation
- Add table formatting
- Add slash command recognition
- Add multi-turn context

### Phase 2: Advanced Features
✅ **Week 4**: Progressive Execution
- Implement plan → approval → execute pattern
- Add progress notifications (transient messages)
- Stream intermediate results

✅ **Week 5**: Intelligence
- Improve intent recognition
- Add query optimization
- Add error recovery
- Better context awareness

### Phase 3: Multi-Agent (LangGraph) - Optional
✅ **Week 6+**: Specialist Agents
- Query specialist
- Analysis specialist
- Visualization specialist
- Orchestrator routing

---

## Code Structure

```
workers/
├── v1/                              # Existing (moved from root)
│   ├── legacy/
│   ├── experimental/
│   └── interactive_flow/
│
├── v2/                              # New agentic architecture
│   ├── __init__.py
│   ├── model.py                     # WorkerMessageRequest, WorkerMessageResponse
│   ├── worker_v2.py                 # Main v2 agent worker
│   ├── agent_factory.py             # Creates/configures agents
│   ├── message_parser.py            # Converts agent output → Messages
│   │
│   ├── tools/                       # Custom MCP tools (if needed)
│   │   ├── chart_tool.py
│   │   └── export_tool.py
│   │
│   └── instructions/                # Agent instruction templates
│       ├── base_instructions.md
│       ├── query_specialist.md
│       └── analysis_specialist.md
│
└── worker.py                        # Dispatcher (both v1 and v2)
```

---

## Comparison: V1 vs V2

| Aspect | V1 (Rigid Flows) | V2 (Agentic) |
|--------|------------------|--------------|
| **Architecture** | Pre-defined flows | Agent + Tools |
| **Control Flow** | Explicit (if/else) | Emergent (LLM decides) |
| **Adding Features** | New flow type | New tool/instruction |
| **Complexity** | High (many flows) | Low (one agent) |
| **Flexibility** | Limited | High |
| **Multi-step** | Hard-coded | Natural |
| **Slash Commands** | Special parsing | Agent figures it out |
| **Context** | Manual passing | Automatic |
| **Maintenance** | Many files | Few files |

---

## Decision: Start with Anthropic Agents SDK

**Recommendation:** Begin v2 with **Anthropic Agents SDK** because:

1. ✅ Already integrated (`agent.py`)
2. ✅ Simpler than LangGraph
3. ✅ Native MCP support (you have servers ready)
4. ✅ Perfect fit for Message-based architecture
5. ✅ Can add LangGraph later if needed for multi-agent

**Simple, powerful, and gets us 90% of the way there.**

Later, if you need:
- Explicit state machines → Add LangGraph
- Multi-agent routing → Add LangGraph orchestrator
- Human-in-the-loop approvals → LangGraph checkpoints

But start simple with a single, powerful agent.

---

## Next Steps

1. **Restructure workers**:
   - Move current workers to `v1/`
   - Create `v2/` directory

2. **Create v2 agent worker**:
   - Port `agent.py` concepts to v2
   - Make it emit Message objects
   - Wire to v2 API

3. **Write agent instructions**:
   - Create comprehensive prompt pack
   - Define capabilities clearly
   - Include examples

4. **Test**:
   - Simple query
   - Complex analysis
   - Slash commands
   - Multi-turn conversation

Want to start implementing?