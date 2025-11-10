"""Intent analyzer - determine user's intent and next action."""

from fm_app.api.v1.model import (
    IntentAnalysis,
    McpServerRequest,
    RequestStatus,
    UpdateRequestModel,
)
from fm_app.db.db import (
    get_history,
    get_query_history,
    update_request,
    update_request_status,
)
from fm_app.stopwatch import stopwatch
from fm_app.workers.interactive_flow.setup import FlowContext, build_prompt_variables


async def analyze_intent(ctx: FlowContext) -> IntentAnalysis:
    """Analyze user intent using planner slot."""
    req = ctx.req
    logger = ctx.logger
    ai_model = ctx.ai_model
    assembler = ctx.assembler
    db = ctx.db
    flow_step = ctx.flow_step

    planner_vars = await build_prompt_variables(ctx)

    db_meta_caps = {}
    mcp_ctx = {
        "req": McpServerRequest(
            request_id=req.request_id,
            db=req.db,
            request=req.request,
            session_id=req.session_id,
            model=req.model,
            flow=req.flow,
        ),
        "flow_step_num": next(flow_step),
    }

    slot = await assembler.render_async(
        "planner", variables=planner_vars, req_ctx=mcp_ctx, mcp_caps=db_meta_caps
    )

    intent_llm_system_prompt = slot.prompt_text

    # Use query-specific history if working on a specific query (via /for_query endpoint)
    # Otherwise use session history for new queries
    if req.query is not None:
        history = await get_query_history(
            db, req.query.query_id, include_responses=False
        )
        logger.info(
            "Using query-specific history for intent",
            flow_stage="query_history_intent",
            flow_step_num=next(flow_step),
            query_id=str(req.query.query_id),
            history_length=len(history),
        )
    else:
        history = await get_history(db, req.session_id, include_responses=False)
        logger.info(
            "Using session history for intent",
            flow_stage="session_history_intent",
            flow_step_num=next(flow_step),
            history_length=len(history),
        )

    if ai_model.get_name() != "gemini":
        messages = [{"role": "system", "content": intent_llm_system_prompt}]
        for item in history:
            if item.get("content") is not None:
                messages.append(item)
        messages.append({"role": "user", "content": req.request})
    else:
        messages = f"""
             {intent_llm_system_prompt}\n
             User input: {req.request}\n"""

    logger.info(
        "Prepared intent request",
        flow_stage="intent",
        flow_step_num=next(flow_step),
        ai_request=messages,
    )

    print(">>> PRE INTENT", stopwatch.lap())

    try:
        llm_response = ai_model.get_structured(
            messages, IntentAnalysis, "gpt-4.1-2025-04-14"
        )
    except Exception as e:
        logger.error(
            "Error getting LLM response",
            flow_stage="error_llm",
            flow_step_num=next(flow_step),
            error=str(e),
        )
        req.status = RequestStatus.error
        req.err = str(e)
        await update_request_status(RequestStatus.error, req.err, db, req.request_id)
        raise

    print(">>> POST INTENT", stopwatch.lap())

    if ai_model.get_name() != "gemini":
        messages.append({"role": "assistant", "content": llm_response})
    else:
        messages = f"""
         {messages}\n
         AI response: {llm_response}\n"""

    logger.info(
        "Got intent",
        flow_stage="llm_intent",
        flow_step_num=next(flow_step),
        ai_response=llm_response,
    )

    await update_request_status(RequestStatus.intent, None, db, req.request_id)

    if llm_response.intent:
        await update_request(
            update=UpdateRequestModel(
                request_id=req.request_id, intent=llm_response.intent
            ),
            db=db,
        )

    return llm_response
