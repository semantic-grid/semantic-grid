"""Data analysis handler - analyze existing data without SQL generation."""

from fm_app.api.v1.model import (
    McpServerRequest,
    RequestStatus,
    StructuredResponse,
)
from fm_app.db.db import (
    get_history,
    update_request_status,
)
from fm_app.workers.interactive_flow.setup import FlowContext, build_prompt_variables


async def handle_data_analysis(ctx: FlowContext) -> None:
    """Handle data analysis flow - analyze data without generating SQL."""
    req = ctx.req
    logger = ctx.logger
    ai_model = ctx.ai_model
    assembler = ctx.assembler
    db = ctx.db
    flow_step = ctx.flow_step
    request_session = ctx.request_session

    data_analysis_vars = await build_prompt_variables(ctx)

    db_meta_caps = {}
    mcp_ctx = {
        "req": McpServerRequest(
            request_id=req.request_id,
            session_id=req.session_id,
            db=req.db,
            request=req.request,
            model=req.model,
            flow=req.flow,
        ),
        "flow_step_num": next(flow_step),
    }

    slot = await assembler.render_async(
        "data_analysis",
        variables=data_analysis_vars,
        req_ctx=mcp_ctx,
        mcp_caps=db_meta_caps,
    )

    analysis_llm_system_prompt = slot.prompt_text

    history = await get_history(db, req.session_id, include_responses=False)

    if ai_model.get_name() != "gemini":
        messages = [{"role": "system", "content": analysis_llm_system_prompt}]
        for item in history:
            if item.get("content") is not None:
                messages.append(item)
        messages.append({"role": "user", "content": req.request})
    else:
        messages = f"""
                 {analysis_llm_system_prompt}\n
                 User input: {req.request}\n"""

    await update_request_status(RequestStatus.finalizing, None, db, req.request_id)

    logger.info(
        "Prepared analysis request",
        flow_stage="analysis",
        flow_step_num=next(flow_step),
        ai_request=messages,
    )

    try:
        llm_response = ai_model.get_response(messages)
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

    if ai_model.get_name() != "gemini":
        messages.append({"role": "assistant", "content": llm_response})
    else:
        messages = f"""
             {messages}\n
             AI response: {llm_response}\n"""

    logger.info(
        "Response to user",
        flow_stage="data_analysis",
        flow_step_num=next(flow_step),
        ai_response=llm_response,
    )

    await update_request_status(RequestStatus.done, None, db, req.request_id)

    req.response = llm_response
    req.structured_response = StructuredResponse(
        intro=llm_response,
        metadata=request_session.metadata,
        refs=req.refs,
    )
