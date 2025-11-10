"""Linked query handler - start session from existing query."""

import uuid

from fm_app.api.v1.model import (
    IntentAnalysis,
    McpServerRequest,
    QueryMetadata,
    RequestStatus,
    StructuredResponse,
)
from fm_app.db.db import (
    update_query_metadata,
    update_request_status,
)
from fm_app.stopwatch import stopwatch
from fm_app.workers.interactive_flow.setup import FlowContext


async def handle_linked_query(ctx: FlowContext) -> None:
    """Handle linked query flow - summarize existing query for user."""
    req = ctx.req
    logger = ctx.logger
    settings = ctx.settings
    ai_model = ctx.ai_model
    assembler = ctx.assembler
    db = ctx.db
    flow_step = ctx.flow_step

    query_metadata_instruction = (
        f"Current QueryMetadata: {req.query.model_dump_json()}"
        if req.query is not None
        else ""
    )

    intent_hint = f"Intent Hint: {req.request_type}"

    linked_query_vars = {
        "client_id": settings.client_id,
        "intent_hint": intent_hint,
        "query_metadata": query_metadata_instruction,
        "current_datetime": req.created_at or req.updated_at,
    }

    await update_request_status(RequestStatus.new, None, db, req.request_id)

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
        "linked_query", variables=linked_query_vars, req_ctx=mcp_ctx, mcp_caps=None
    )

    linked_query_llm_system_prompt = slot.prompt_text

    if ai_model.get_name() != "gemini":
        messages = [{"role": "system", "content": linked_query_llm_system_prompt}]
        messages.append({"role": "user", "content": req.request})
    else:
        messages = f"""
             {linked_query_llm_system_prompt}\n
             User input: {req.request}\n"""

    logger.info(
        "Prepared linked_query request",
        flow_stage="linked_query",
        flow_step_num=next(flow_step),
        ai_request=messages,
    )

    print(">>> PRE LINKED QUERY", stopwatch.lap())
    await update_request_status(RequestStatus.intent, None, db, req.request_id)

    try:
        llm_response = ai_model.get_structured(
            messages, IntentAnalysis, "gpt-4.1-mini-2025-04-14"
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
        return

    print(">>> POST LINKED QUERY", stopwatch.lap())
    await update_request_status(RequestStatus.finalizing, None, db, req.request_id)

    if ai_model.get_name() != "gemini":
        messages.append({"role": "assistant", "content": llm_response})
    else:
        messages = f"""
                 {messages}\n
                 AI response: {llm_response}\n"""

    new_metadata_dict = {
        "id": str(uuid.uuid4()),
        "summary": llm_response.intent,
        "description": llm_response.intent,
        "sql": req.query.sql,
        "columns": [c.model_dump() for c in req.query.columns],
        "row_count": req.query.row_count,
    }

    logger.info(
        "Flow complete",
        flow_stage="end",
        flow_step_num=next(flow_step),
        flow=req.flow,
        intent=llm_response.intent,
    )

    await update_query_metadata(
        session_id=req.session_id,
        user_owner=req.user,
        metadata=new_metadata_dict,
        db=db,
    )

    await update_request_status(RequestStatus.done, None, db, req.request_id)

    req.response = llm_response.intent
    req.structured_response = StructuredResponse(
        intent=llm_response.intent,
        description=llm_response.intent,
        intro=None,
        sql=req.query.sql,
        metadata=QueryMetadata(**new_metadata_dict),
        refs=None,
    )

    print(">>> DONE LINKED QUERY", stopwatch.lap())
