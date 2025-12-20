# Phase 1: Ask User Primitive - Implementation Plan

## Overview

Enable the agent to ask clarifying questions at any point in the flow, rather than making assumptions or failing silently.

**Goal:** Agent can ask clarifying questions before proceeding with query generation.

**Scope:** Minimal changes to enable clarification capability without restructuring existing flows.

---

## Current State

### Intent Analysis Flow
```
User Request → analyze_intent() → IntentAnalysis
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
            interactive_query    general_chat      disambiguation
                    │                  │                  │
                    ▼                  ▼                  ▼
             Query Planning      Direct Response    Direct Response
```

### Current IntentAnalysis Model
```python
class IntentAnalysis(BaseModel):
    request_type: InteractiveRequestType = InteractiveRequestType.interactive_query
    intent: Optional[str] = None
    summary: Optional[str] = None
    response: Optional[str] = None
    requires_plan_approval: bool = False
```

### Current Plan Approval Flow
```
Request → Intent Analysis → Query Planner → QueryPlan
                                               │
                                               ▼
                              status = "feedback_requested"
                              structured_response.query_plan = plan
                                               │
                                               ▼
                              Frontend renders QueryPlanCard
                              User clicks Approve/Reject
                                               │
                                               ▼
                              New request with request_type = "plan_approval"
```

### Limitations
1. The current `disambiguation` type returns a response but doesn't structure it as a question with options. The frontend renders it as plain text, not as an interactive prompt.
2. Plan approval and potential clarification both use `status = "feedback_requested"` but there's no discriminator field to tell the frontend which UI to render.

### Relationship: Plan Approval vs Clarification

| Aspect | Plan Approval | Clarification |
|--------|--------------|---------------|
| **When** | After planning, before SQL | Before planning, to understand intent |
| **What** | "Here's what I'll do, ok?" | "I need more info to proceed" |
| **User action** | Approve/Reject/Amend | Answer question |
| **Payload** | Complex QueryPlan | Simple question + options |
| **Frontend** | QueryPlanCard with accordions | ClarificationPrompt with chips |

**Decision:** Keep them as separate response types but introduce a unified `response_type` discriminator field. This:
- Preserves existing plan approval UX (no changes needed)
- Enables new clarification UX with different component
- Establishes pattern for future "ask user" scenarios (checkpoints, verification)

---

## Target State

### Enhanced Flow
```
User Request → analyze_intent() → IntentAnalysis
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
            interactive_query    clarification     general_chat
                    │                  │                  │
                    ▼                  ▼                  ▼
             Query Planning     Return Question     Direct Response
                                 + Options
                                       │
                                       ▼
                              User Responds
                                       │
                                       ▼
                              Continue Flow
```

---

## Implementation Steps

### Step 1: Model Changes (`fm_app/api/model.py`)

#### 1.1 Add `clarification` request type

```python
class InteractiveRequestType(str, Enum):
    tbd = "tbd"
    interactive_query = "interactive_query"
    data_analysis = "data_analysis"
    general_chat = "general_chat"
    disambiguation = "disambiguation"  # Keep for backward compat
    clarification = "clarification"  # NEW: Structured question
    clarification_response = "clarification_response"  # NEW: User's answer
    # ... existing types ...
```

#### 1.2 Add clarification fields to IntentAnalysis

```python
class IntentAnalysis(BaseModel):
    request_type: InteractiveRequestType = InteractiveRequestType.interactive_query
    intent: Optional[str] = None
    summary: Optional[str] = None
    response: Optional[str] = None
    requires_plan_approval: bool = False
    
    # NEW: Clarification support
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    clarification_options: Optional[list[str]] = None  # Multiple choice
    clarification_context: Optional[str] = None  # Why we're asking
```

#### 1.3 Add clarification to StructuredResponse

```python
class ClarificationData(BaseModel):
    """Structured clarification question for frontend."""
    question: str
    options: Optional[list[str]] = None
    context: Optional[str] = None
    allow_freeform: bool = True  # Allow typed response vs only options


class StructuredResponse(BaseModel):
    # ... existing fields ...
    
    # NEW: Response type discriminator (unifies all "ask user" patterns)
    response_type: Optional[str] = None
    # Values:
    #   None / "query" - legacy query response (default)
    #   "plan_approval" - existing plan approval flow
    #   "clarification" - new clarification flow
    #   Future: "checkpoint", "verification", etc.
    
    # NEW: Clarification data
    clarification: Optional[ClarificationData] = None
    
    # EXISTING: query_plan field (already present, now documented as plan_approval payload)
    query_plan: Optional[QueryPlan] = None
```

**File:** `apps/fm-app/fm_app/api/model.py`

**Backward Compatibility:**
- All new fields are optional with defaults
- Existing responses work unchanged (response_type defaults to None)
- Frontend checks response_type; if absent, uses legacy rendering
- Existing plan approval continues to work (we'll set `response_type="plan_approval"` when populating query_plan)

---

### Step 1.4: Update existing plan approval to set response_type

When setting `query_plan` on `StructuredResponse`, also set `response_type="plan_approval"`.

**File:** `apps/fm-app/fm_app/workers/interactive_flow/__init__.py`

Find all places where `structured_response.query_plan = ...` is set and add:

```python
# Existing code:
req.structured_response.query_plan = query_plan
req.structured_response.intent = intent.intent

# Add this line:
req.structured_response.response_type = "plan_approval"
```

Locations to update:
- `_handle_replan_on_failure()` (~line 104)
- `interactive_flow()` plan amendment handling (~line 281)
- `interactive_flow()` requires_user_approval block (~line 351)

This ensures the frontend can use `response_type` as a reliable discriminator going forward.

---

### Step 2: Planner Prompt Update

#### 2.1 Add clarification option to planner prompt

Update the planner prompt to allow the LLM to output clarification requests.

**File:** `packages/resources/fm_app/system-pack/v1.2.0/slots/planner/prompt.md`

Add new section after existing choices:

```markdown
### clarification

Choose **clarification** if the user's request is ambiguous or missing critical 
information that you need before proceeding. Unlike **disambiguation**, this 
returns a structured question that the user can answer.

Use clarification when:
- Multiple valid interpretations exist and you cannot make a reasonable assumption
- A key parameter is missing (time range, entity type, threshold value)
- The scope is unclear ("all" vs "recent" vs "top N")

Do NOT use clarification for:
- Minor ambiguities where a reasonable default exists
- Questions you can answer by stating assumptions in the plan
- Simple yes/no confirmations (let the plan approval handle those)

When clarification_needed is true, provide:
- **clarification_question**: Clear, specific question
- **clarification_options**: 2-5 concrete choices (when applicable)
- **clarification_context**: Brief explanation of why you're asking

Example:
```json
{
  "request_type": "clarification",
  "clarification_needed": true,
  "clarification_question": "Which time period should I analyze?",
  "clarification_options": ["Last 7 days", "Last 30 days", "Last quarter", "Year to date"],
  "clarification_context": "The query involves trends, and the time window significantly affects the results."
}
```

**Important:** Only ask clarifying questions when truly necessary. Prefer making 
reasonable assumptions and documenting them in the plan for user review.
```

Update the response schema section:

```markdown
## Response Format

If **clarification** is needed:
- Set **request_type** to "clarification"
- Set **clarification_needed** to true
- Provide **clarification_question**, **clarification_options** (if applicable), and **clarification_context**

If proceeding with a query:
- Set **request_type** to "interactive_query" or other appropriate type
- Set **intent** to your understanding of the request
- Set **requires_plan_approval** based on complexity assessment
```

---

### Step 3: Intent Analyzer Update

#### 3.1 Handle clarification in analyze_intent

**File:** `apps/fm-app/fm_app/workers/interactive_flow/intent_analyzer.py`

The current implementation already returns `IntentAnalysis` from the LLM. With the model changes, the LLM can now return `clarification_needed=True`. No code changes needed in the analyzer itself - it will pass through the new fields.

---

### Step 4: Orchestrator Update

#### 4.1 Route clarification responses

**File:** `apps/fm-app/fm_app/workers/interactive_flow/__init__.py`

Add handling for clarification:

```python
async def interactive_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
) -> WorkerRequest:
    """Main orchestrator for interactive flow."""
    
    ctx = await initialize_flow(req, ai_model, db_wh, db)
    await update_request_status(RequestStatus.in_process, None, db, req.request_id)

    # Route based on initial request type
    if req.request_type == InteractiveRequestType.manual_query:
        await handle_manual_query(ctx)
        return req
    
    # ... existing routing ...
    
    # NEW: Handle clarification responses
    elif req.request_type == InteractiveRequestType.clarification_response:
        # User responded to a clarification question
        # Re-run intent analysis with the clarified context
        return await handle_clarification_response(ctx)
    
    else:
        # For all other types, analyze intent first
        try:
            intent = await analyze_intent(ctx)
        except Exception:
            return req

        # NEW: Handle clarification requests
        if intent.clarification_needed or intent.request_type == InteractiveRequestType.clarification:
            return await handle_clarification_request(ctx, intent)
        
        # ... existing routing based on intent.request_type ...
```

#### 4.2 Add clarification handlers

**File:** `apps/fm-app/fm_app/workers/interactive_flow/clarification.py` (NEW)

```python
"""Clarification handling for interactive flow."""

from fm_app.api.model import (
    ClarificationData,
    IntentAnalysis,
    RequestStatus,
    StructuredResponse,
)
from fm_app.db.db import update_request_status, get_previous_request
from fm_app.workers.interactive_flow.setup import FlowContext


async def handle_clarification_request(
    ctx: FlowContext,
    intent: IntentAnalysis,
) -> None:
    """Handle a clarification request from intent analysis."""
    req = ctx.req
    
    # Build clarification response
    clarification = ClarificationData(
        question=intent.clarification_question or "Could you provide more details?",
        options=intent.clarification_options,
        context=intent.clarification_context,
        allow_freeform=True,
    )
    
    if req.structured_response is None:
        req.structured_response = StructuredResponse()
    
    req.structured_response.response_type = "clarification"
    req.structured_response.clarification = clarification
    req.structured_response.intent = intent.intent
    
    # Set status to await user response
    req.status = RequestStatus.feedback_requested
    await update_request_status(
        RequestStatus.feedback_requested, None, ctx.db, req.request_id
    )
    
    ctx.logger.info(
        "Clarification requested",
        flow_stage="clarification_request",
        question=clarification.question,
        options=clarification.options,
    )


async def handle_clarification_response(ctx: FlowContext) -> None:
    """Handle user's response to a clarification question."""
    req = ctx.req
    
    # Get the previous request that asked the clarification
    prev_request = await get_previous_request(ctx.db, req.session_id, req.request_id)
    
    if prev_request and prev_request.intent:
        # Combine original intent with user's clarification
        original_intent = prev_request.intent
        clarification_answer = req.request
        
        # Update the request to include context
        combined_context = f"{original_intent}\n\nUser clarification: {clarification_answer}"
        req.request = combined_context
        
        ctx.logger.info(
            "Processing clarification response",
            flow_stage="clarification_response",
            original_intent=original_intent[:100] if original_intent else None,
            clarification=clarification_answer,
        )
    
    # Re-run intent analysis with the clarified context
    # Import here to avoid circular dependency
    from fm_app.workers.interactive_flow.intent_analyzer import analyze_intent
    from fm_app.workers.interactive_flow import _route_by_intent
    
    intent = await analyze_intent(ctx)
    
    # Route based on the new intent (should now have enough info)
    return await _route_by_intent(ctx, intent)
```

#### 4.3 Refactor orchestrator for reusability

Extract intent routing to a helper function:

```python
async def _route_by_intent(ctx: FlowContext, intent: IntentAnalysis) -> WorkerRequest:
    """Route request based on analyzed intent."""
    req = ctx.req
    
    # Handle clarification
    if intent.clarification_needed or intent.request_type == InteractiveRequestType.clarification:
        await handle_clarification_request(ctx, intent)
        return req
    
    # Existing routing logic...
    if intent.request_type in (
        InteractiveRequestType.linked_session,
        InteractiveRequestType.interactive_query,
    ):
        # ... existing query handling ...
    
    elif intent.request_type == InteractiveRequestType.data_analysis:
        await handle_data_analysis(ctx)
        return req
    
    # ... etc ...
```

---

### Step 5: Database Helper

#### 5.1 Add function to get previous request

**File:** `apps/fm-app/fm_app/db/db.py`

```python
async def get_previous_request(
    db: AsyncSession,
    session_id: UUID,
    current_request_id: UUID,
) -> Optional[GetRequestModel]:
    """Get the request immediately before the current one in the session."""
    from fm_app.db.request import Request
    
    # Get sequence number of current request
    current = await db.execute(
        select(Request.sequence_number)
        .where(Request.request_id == current_request_id)
    )
    current_seq = current.scalar_one_or_none()
    
    if current_seq is None or current_seq <= 1:
        return None
    
    # Get previous request
    result = await db.execute(
        select(Request)
        .where(Request.session_id == session_id)
        .where(Request.sequence_number == current_seq - 1)
    )
    prev = result.scalar_one_or_none()
    
    if prev is None:
        return None
    
    return GetRequestModel.model_validate(prev)
```

---

### Step 6: Frontend Changes

#### 6.1 Add ClarificationPrompt component

**File:** `apps/web/app/components/ClarificationPrompt.tsx` (NEW)

```typescript
import { Box, Button, Stack, TextField, Typography, Chip } from "@mui/material";
import { useState } from "react";

interface ClarificationPromptProps {
  question: string;
  options?: string[];
  context?: string;
  allowFreeform?: boolean;
  onResponse: (response: string) => void;
  disabled?: boolean;
}

export const ClarificationPrompt: React.FC<ClarificationPromptProps> = ({
  question,
  options,
  context,
  allowFreeform = true,
  onResponse,
  disabled = false,
}) => {
  const [customResponse, setCustomResponse] = useState("");

  const handleOptionClick = (option: string) => {
    if (!disabled) {
      onResponse(option);
    }
  };

  const handleCustomSubmit = () => {
    if (!disabled && customResponse.trim()) {
      onResponse(customResponse.trim());
      setCustomResponse("");
    }
  };

  return (
    <Box sx={{ p: 2, bgcolor: "action.hover", borderRadius: 1, my: 1 }}>
      {context && (
        <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
          {context}
        </Typography>
      )}
      
      <Typography variant="body1" sx={{ mb: 2, fontWeight: 500 }}>
        {question}
      </Typography>

      {options && options.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: "wrap", gap: 1 }}>
          {options.map((option) => (
            <Chip
              key={option}
              label={option}
              onClick={() => handleOptionClick(option)}
              clickable={!disabled}
              color="primary"
              variant="outlined"
              sx={{ cursor: disabled ? "default" : "pointer" }}
            />
          ))}
        </Stack>
      )}

      {allowFreeform && (
        <Stack direction="row" spacing={1}>
          <TextField
            size="small"
            fullWidth
            placeholder={options ? "Or type your own response..." : "Type your response..."}
            value={customResponse}
            onChange={(e) => setCustomResponse(e.target.value)}
            onKeyPress={(e) => e.key === "Enter" && handleCustomSubmit()}
            disabled={disabled}
          />
          <Button 
            variant="contained" 
            onClick={handleCustomSubmit}
            disabled={disabled || !customResponse.trim()}
          >
            Send
          </Button>
        </Stack>
      )}
    </Box>
  );
};

export default ClarificationPrompt;
```

#### 6.2 Update ChatSession to handle clarification

**File:** `apps/web/app/contexts/ChatSession/index.tsx`

Add handler for clarification responses and use unified switch pattern:

```typescript
// Add to the context or component
const handleClarificationResponse = async (response: string) => {
  await sendRequest({
    request: response,
    request_type: "clarification_response",
  });
};

// Unified rendering based on response_type
const renderStructuredResponse = (message: Message) => {
  const sr = message.structured_response;
  if (!sr) return null;
  
  const isLatestMessage = /* check if this is the latest message */;
  const isDisabled = !isLatestMessage || isLoading;
  
  // Use response_type as discriminator
  switch (sr.response_type) {
    case "plan_approval":
      // Existing QueryPlanCard rendering (already implemented)
      return sr.query_plan ? (
        <QueryPlanCard
          plan={sr.query_plan}
          onApprove={handlePlanApprove}
          onReject={handlePlanReject}
          disabled={isDisabled}
        />
      ) : null;
    
    case "clarification":
      // New clarification rendering
      return sr.clarification ? (
        <ClarificationPrompt
          question={sr.clarification.question}
          options={sr.clarification.options}
          context={sr.clarification.context}
          allowFreeform={sr.clarification.allow_freeform ?? true}
          onResponse={handleClarificationResponse}
          disabled={isDisabled}
        />
      ) : null;
    
    // Future: case "checkpoint": ...
    // Future: case "verification": ...
    
    default:
      // Legacy rendering - check for query_plan without response_type (backward compat)
      if (sr.query_plan) {
        return (
          <QueryPlanCard
            plan={sr.query_plan}
            onApprove={handlePlanApprove}
            onReject={handlePlanReject}
            disabled={isDisabled}
          />
        );
      }
      // Regular response rendering
      return null;
  }
};
```

This unified switch pattern:
- Uses `response_type` as the primary discriminator
- Falls back to checking `query_plan` presence for backward compatibility
- Easily extensible for future response types (checkpoint, verification)

#### 6.3 Update API types

**File:** Run `npm run generate` after API changes to update types

Or manually add to `apps/web/app/api/apegpt/types.gen.ts`:

```typescript
export interface ClarificationData {
  question: string;
  options?: string[];
  context?: string;
  allow_freeform?: boolean;
}

// Update StructuredResponse
export interface StructuredResponse {
  // ... existing fields
  response_type?: string;
  clarification?: ClarificationData;
}
```

---

## Files to Modify

### Backend (fm-app)

| File | Changes |
|------|---------|
| `fm_app/api/model.py` | Add `clarification`, `clarification_response` to enum; add `ClarificationData` model; extend `IntentAnalysis` and `StructuredResponse` |
| `fm_app/workers/interactive_flow/__init__.py` | Add routing for `clarification` and `clarification_response` request types |
| `fm_app/workers/interactive_flow/clarification.py` | NEW: Handlers for clarification requests and responses |
| `fm_app/db/db.py` | Add `get_previous_request()` helper |

### Prompts (resources)

| File | Changes |
|------|---------|
| `packages/resources/fm_app/system-pack/v1.2.0/slots/planner/prompt.md` | Add `clarification` as a routing option with examples |

### Frontend (web)

| File | Changes |
|------|---------|
| `apps/web/app/components/ClarificationPrompt.tsx` | NEW: Clarification UI component |
| `apps/web/app/contexts/ChatSession/index.tsx` | Handle clarification responses and rendering |
| `apps/web/app/api/apegpt/types.gen.ts` | Regenerate from OpenAPI or add types manually |

---

## Testing Plan

### Unit Tests

1. **Model tests** (`tests/test_models.py`)
   - Verify `IntentAnalysis` with clarification fields serializes correctly
   - Verify backward compatibility (old responses without clarification work)

2. **Orchestrator tests** (`tests/test_interactive_flow.py`)
   - Test routing to `handle_clarification_request` when `clarification_needed=True`
   - Test `clarification_response` handling combines context correctly

### Integration Tests

1. **End-to-end clarification flow**
   - Send ambiguous request → receive clarification question
   - Respond to clarification → receive query plan or result

2. **Backward compatibility**
   - Existing disambiguation requests still work
   - Old clients without clarification support see fallback

### Manual Testing

1. Test prompts that should trigger clarification:
   - "Show me the top wallets" (top by what metric?)
   - "Analyze recent activity" (how recent? which activity?)
   - "Compare performance" (of what? over what period?)

2. Test prompts that should NOT trigger clarification:
   - "Show me the top 10 wallets by volume in the last 7 days"
   - "List all tokens"

---

## Rollout Plan

### Phase 1a: Backend Only (No Frontend)
1. Deploy model changes
2. Deploy orchestrator changes
3. Clarifications render as text (fallback to `response` field)

### Phase 1b: Frontend Support
1. Deploy ClarificationPrompt component
2. Update ChatSession to detect and render clarifications
3. Full interactive flow working

### Monitoring

- Track clarification rate: `clarification_requests / total_requests`
- Track clarification → success rate: requests that proceed after clarification
- Track abandonment: users who don't respond to clarifications

---

## Backward Compatibility Guarantees

1. **New fields are optional**: All clarification-related fields default to `None`/`False`
2. **Existing enum values preserved**: `disambiguation` still works
3. **Frontend fallback**: If `response_type` is missing, render as before
4. **API contract unchanged**: Existing request/response shapes work

---

## Open Questions

1. **Clarification history**: Should we store which clarifications were asked and answered?
   - Recommendation: Yes, via the existing request chain (parent request has the question, child has the answer)

2. **Max clarifications**: Should we limit how many times the agent can ask before proceeding?
   - Recommendation: Start with no limit; monitor and add if needed

3. **Clarification timeout**: What if user doesn't respond?
   - Recommendation: Status stays `feedback_requested`; user can continue later or start new request

---

## Future Extension: Full "Ask User" Taxonomy

Phase 1 establishes the `response_type` pattern for clarification. This section documents the full taxonomy of "ask user" scenarios we anticipate, to inform the design.

### Categories of "Ask User" Interactions

#### 1. Pre-Execution (Before work begins)

| Type | Purpose | Example | Options Style |
|------|---------|---------|---------------|
| `clarification` | Need more info | "Which time period?" | Multiple choice / freeform |
| `plan_approval` | Approve before proceeding | "Here's my plan - ok?" | Approve / Reject / Amend |
| `cost_warning` | Expensive operation | "This will scan 10B rows" | Proceed / Cancel / Add filters |
| `destructive_confirm` | Dangerous action | "This will delete 500 records" | Confirm / Cancel |

#### 2. Mid-Execution (During multi-step work)

| Type | Purpose | Example | Options Style |
|------|---------|---------|---------------|
| `checkpoint` | Intermediate results | "Found 3 anomalies - dig deeper?" | Continue / Done / Pivot |
| `branch_selection` | Choose path | "EMEA or APAC dropped - which to investigate?" | Select branch |
| `progress_check` | Long-running status | "Still analyzing... been 2 min" | Wait / Cancel / Background |

#### 3. Post-Execution (After results)

| Type | Purpose | Example | Options Style |
|------|---------|---------|---------------|
| `verification` | Goal check | "Does this answer your question?" | Yes / No / Partially |
| `satisfaction` | Anything else? | "Is there anything else you need?" | Done / Follow-up |

#### 4. Error Recovery (On failure)

| Type | Purpose | Example | Options Style |
|------|---------|---------|---------------|
| `error_recovery` | Something failed | "Query timed out - retry with smaller scope?" | Retry / Modify / Cancel |
| `alternative_approach` | Can't proceed as planned | "Can't join these tables - try different approach?" | Select alternative |

#### 5. Learning (Feedback)

| Type | Purpose | Example | Options Style |
|------|---------|---------|---------------|
| `feedback` | Rate/improve | "How accurate was this result?" | 1-5 stars + comment |
| `preference` | Learn user style | "Which format do you prefer?" | A / B choice |

### Unified Model (Future State)

As more types are added, we may evolve toward a unified model:

```python
class AskUserType(str, Enum):
    # Pre-execution
    clarification = "clarification"
    plan_approval = "plan_approval"
    cost_warning = "cost_warning"
    destructive_confirm = "destructive_confirm"
    
    # Mid-execution
    checkpoint = "checkpoint"
    branch_selection = "branch_selection"
    progress_check = "progress_check"
    
    # Post-execution
    verification = "verification"
    satisfaction = "satisfaction"
    
    # Error recovery
    error_recovery = "error_recovery"
    alternative_approach = "alternative_approach"
    
    # Learning
    feedback = "feedback"
    preference = "preference"


class AskUserOption(BaseModel):
    """Single option for user to choose."""
    id: str                    # Machine-readable ID
    label: str                 # Display text
    description: Optional[str] = None
    icon: Optional[str] = None
    style: Literal["primary", "secondary", "danger", "success"] = "secondary"


class AskUserData(BaseModel):
    """Unified model for all 'ask user' interactions."""
    
    ask_type: AskUserType
    
    # Content
    message: str
    context: Optional[str] = None
    
    # Response options
    options: Optional[list[AskUserOption]] = None
    allow_freeform: bool = True
    default_option: Optional[str] = None
    
    # Type-specific payloads
    query_plan: Optional[QueryPlan] = None           # plan_approval
    multi_step_plan: Optional[MultiStepPlan] = None  # multi-step approval
    intermediate_result: Optional[dict] = None       # checkpoint
    error_details: Optional[ErrorDetails] = None     # error_recovery
    cost_estimate: Optional[CostEstimate] = None     # cost_warning
    
    # Behavior hints
    urgency: Literal["low", "normal", "high"] = "normal"
    timeout_seconds: Optional[int] = None
    timeout_action: Optional[str] = None  # What to do on timeout
    skippable: bool = False
    skip_action: Optional[str] = None
```

### Frontend Component Hierarchy (Future State)

```
AskUserPrompt (unified wrapper)
├── ClarificationPrompt      # Phase 1
├── PlanApprovalCard         # Existing (plan_approval)
├── MultiStepPlanCard        # Phase 3
├── CostWarningDialog        # When cost guards added
├── CheckpointPrompt         # Phase 6
├── BranchSelector           # Phase 5
├── VerificationPrompt       # Phase 6
├── ErrorRecoveryDialog      # Phase 5
└── FeedbackPrompt           # Future
```

### Migration Path

| Phase | Types Added | Notes |
|-------|-------------|-------|
| Current | `plan_approval` (implicit) | Uses `query_plan` presence, no `response_type` |
| Phase 1 | `clarification` | Adds `response_type` discriminator |
| Phase 3 | `multi_step_plan_approval` | Extends plan approval for multi-step |
| Phase 5 | `error_recovery`, `branch_selection` | Agent orchestrator error handling |
| Phase 6 | `checkpoint`, `verification` | Result verification and iteration |
| Future | `cost_warning`, `feedback`, etc. | As features require |

### Design Principles

1. **Discriminator-based**: Use `response_type` string to identify the ask type
2. **Type-specific payloads**: Each type can have specialized data structures
3. **Common fields**: `message`, `options`, `context` work across all types
4. **Backward compatible**: Missing `response_type` falls back to legacy behavior
5. **Frontend delegation**: Unified wrapper component delegates to specialized renderers
6. **Gradual adoption**: Add types incrementally as features require them

---

## Clarification Strategy: When to Ask vs When to Assume

The key challenge is balancing between asking too many questions (inert) and making too many assumptions (risky). This section defines a structured approach based on QueryPlan fields.

### QueryPlan Field → Clarification Mapping

| QueryPlan Field | Required? | Clarification Trigger | Example Question |
|-----------------|-----------|----------------------|------------------|
| `primary_table` | **MUST** | Can't identify which table | "Which data do you want to see: hotspots, sessions, or subscribers?" |
| `tables` | **MUST** | Multiple valid interpretations | "Should I include related data from [X] as well?" |
| `columns_selected` | CAN assume | Only if user says "specific columns" but doesn't specify | (rare - usually assume all relevant) |
| `filters` | CAN assume | Ambiguous filter value | "Filter by which status: active, inactive, or all?" |
| `aggregations` | CAN assume | "analyze/compare" but unclear metric | "Compare by what metric: count, revenue, or duration?" |
| `group_by` | CAN assume | "breakdown" but unclear dimension | "Group by: day, week, or month?" |
| `time_range` | CAN assume | Default to reasonable window | (don't ask - assume last 30 days) |
| `order_by` | CAN assume | Just pick sensible default | (never ask) |

### Assumption Risk Classification

**High Risk Assumptions** (prefer clarification):
- Wrong table = wasted query, confusing results
- Wrong entity type = completely wrong data
- Ambiguous filter with no schema match = query will fail

**Medium Risk Assumptions** (prefer plan approval with stated assumption):
- Time range = can refine after seeing results
- Aggregation type = user can see and adjust
- Grouping dimension = visible in output

**Low Risk Assumptions** (just do it):
- Sort order = trivial to change
- Column selection = can add/remove later
- Limit = pagination handles it

### Decision Matrix

```
                    Schema Match
                    High        Medium      Low/None
                ┌───────────┬───────────┬───────────┐
         Clear  │ interactive│ plan_     │ clarific- │
Intent          │ _query     │ approval  │ ation     │
                │ (just do)  │ (assume)  │ (ask)     │
                ├───────────┼───────────┼───────────┤
         Vague  │ plan_     │ clarific- │ clarific- │
                │ approval  │ ation     │ ation     │
                │ (assume)  │ (ask)     │ (ask)     │
                └───────────┴───────────┴───────────┘
```

### Confidence-Based Routing Logic

```python
class QueryPlanAssessment(BaseModel):
    """Assessment of whether a query plan can be built."""
    can_build_plan: bool
    confidence: float  # 0.0 to 1.0
    missing_required: list[str]  # ["primary_table", "filter_value"]
    assumptions: list[str]       # Low-risk assumptions made
    high_risk_assumptions: list[str]  # Assumptions that could waste user's time
    
    # Clarification details (if needed)
    clarification_needed: bool
    clarification_field: str | None  # Which field needs clarification
    clarification_question: str | None
    clarification_options: list[str] | None

# Routing logic
def route_request(assessment: QueryPlanAssessment) -> str:
    if assessment.missing_required:
        # Can't proceed without required fields
        return "clarification"
    
    if assessment.high_risk_assumptions:
        # Has risky assumptions - ask first
        return "clarification"
    
    if assessment.confidence > 0.8:
        # High confidence - just do it
        return "interactive_query"
    
    if assessment.confidence > 0.5:
        # Medium confidence - show plan with assumptions
        return "plan_approval"
    
    # Low confidence - ask
    return "clarification"
```

### One Question Rule

When clarification is needed:
1. **Ask only ONE question** per clarification turn
2. **Prioritize by impact**: Ask about highest-risk ambiguity first
3. **Batch related choices**: If asking about entity, include all entity options
4. **Provide context**: Explain why the question matters

Priority order for clarification:
1. `primary_table` - Which data/entity
2. `filters` with high-risk ambiguity - Which specific values
3. `aggregations` - Which metric (only if explicitly requested analysis)

### Examples

**Scenario 1: "show me user activity"**
- `primary_table`: Could be sessions, events, logins → HIGH RISK
- Action: `clarification` - "Which user activity: login sessions, page views, or API calls?"

**Scenario 2: "filter by status"**
- `primary_table`: Unknown → HIGH RISK
- `filters`: "status" mentioned but no column match → HIGH RISK
- Action: `clarification` - "Which data would you like to filter: hotspots, sessions, or subscribers?"

**Scenario 3: "show wifi sessions from last week"**
- `primary_table`: wifi_sessions → CLEAR MATCH
- `time_range`: "last week" → CLEAR
- Action: `interactive_query` (high confidence, just do it)

**Scenario 4: "analyze top performers"**
- `primary_table`: Could be hotspots, users → MEDIUM RISK
- `aggregations`: "top" by what metric? → MEDIUM RISK
- `time_range`: Not specified → LOW RISK (assume last 30 days)
- Action: `plan_approval` with assumptions stated

### Implementation in Planner Prompt

The planner should output a `plan_confidence` assessment:

```json
{
  "request_type": "interactive_query",
  "requires_plan_approval": true,
  "plan_confidence": {
    "score": 0.6,
    "missing_required": [],
    "assumptions": [
      "Assuming 'top' means by session count",
      "Assuming time range is last 30 days"
    ],
    "high_risk_assumptions": [
      "Assuming 'performers' refers to hotspots, not users"
    ]
  }
}
```

If `high_risk_assumptions` is non-empty and `score < 0.7`, route to clarification instead of plan approval.
