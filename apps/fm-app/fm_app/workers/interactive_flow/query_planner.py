"""Query planner - generate human-readable query plan before SQL generation."""

from fm_app.api.model import (
    McpServerRequest,
    QueryPlan,
    RequestStatus,
)
from fm_app.db.db import (
    get_history,
    get_query_history,
    update_request_status,
)
from fm_app.tracing import TracingTimer
from fm_app.workers.interactive_flow.setup import FlowContext, build_prompt_variables


async def generate_query_plan(ctx: FlowContext, intent: str) -> QueryPlan:
    """
    Generate a human-readable query plan for user approval.

    This step occurs after intent analysis determines the query is complex enough
    to warrant a planning step (requires_plan_approval=True).

    The plan describes what the query will do in human terms, including:
    - Tables and joins involved
    - Filters and conditions
    - Aggregations and grouping
    - Assumptions being made
    - Default parameters applied

    The user can approve the plan or provide feedback to modify it.
    """
    req = ctx.req
    logger = ctx.logger
    ai_model = ctx.ai_model
    assembler = ctx.assembler
    db = ctx.db
    flow_step = ctx.flow_step
    tracer = ctx.tracer

    # Build prompt variables (includes db schema, examples, etc.)
    planner_vars = await build_prompt_variables(ctx)

    # Add intent to variables for the query_planner slot
    planner_vars["intent"] = intent
    planner_vars["user_request"] = req.request

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

    # Render the query_planner slot
    with TracingTimer() as prompt_timer:
        slot = await assembler.render_async(
            "query_planner", variables=planner_vars, req_ctx=mcp_ctx, mcp_caps={}
        )

    planner_system_prompt = slot.prompt_text

    # Trace prompt assembly
    if tracer:
        await tracer.trace_prompt_assembly(
            slot_name="query_planner",
            prompt_hash=slot.lineage.get("content_hash", "")[:16]
            if slot.lineage
            else "",
            duration_ms=prompt_timer.duration_ms,
            metadata={
                "slot_lineage": slot.lineage,
                "mcp_requirements": slot.lineage.get("mcp_lineage")
                if slot.lineage
                else None,
                "intent": intent,
            },
        )

    # Use query-specific history if working on a specific query
    # Otherwise use session history for new queries
    if req.query is not None:
        history = await get_query_history(
            db, req.query.query_id, include_responses=False
        )
        logger.info(
            "Using query-specific history for planning",
            flow_stage="query_history_plan",
            flow_step_num=next(flow_step),
            query_id=str(req.query.query_id),
            history_length=len(history),
        )
    else:
        history = await get_history(db, req.session_id, include_responses=False)
        logger.info(
            "Using session history for planning",
            flow_stage="session_history_plan",
            flow_step_num=next(flow_step),
            history_length=len(history),
        )

    # Build messages for LLM
    if ai_model.get_name() != "gemini":
        messages = [{"role": "system", "content": planner_system_prompt}]
        for item in history:
            if item.get("content") is not None:
                messages.append(item)
        messages.append({"role": "user", "content": req.request})
    else:
        messages = f"""
             {planner_system_prompt}\n
             User input: {req.request}\n"""

    logger.info(
        "Prepared query plan request",
        flow_stage="query_plan",
        flow_step_num=next(flow_step),
        intent=intent,
    )

    # Set transient Planning status while LLM generates plan
    await update_request_status(RequestStatus.planning, None, db, req.request_id)

    try:
        with TracingTimer() as llm_timer:
            llm_response = ai_model.get_structured(
                messages, QueryPlan, "gpt-4.1-2025-04-14"
            )

        # Trace LLM call
        if tracer:
            await tracer.trace_llm_call(
                model=ai_model.get_name(),
                input_messages=messages,
                output_raw=llm_response.model_dump_json(),
                output_parsed=llm_response.model_dump(),
                tokens_in=None,  # TODO: get from model response if available
                tokens_out=None,
                duration_ms=llm_timer.duration_ms,
                metadata={
                    "step": "query_planner",
                    "tables": llm_response.tables,
                    "complexity": llm_response.estimated_complexity,
                },
            )
    except Exception as e:
        logger.error(
            "Error generating query plan",
            flow_stage="error_query_plan",
            flow_step_num=next(flow_step),
            error=str(e),
        )
        # Trace error
        if tracer:
            await tracer.trace_error(
                error_message=str(e),
                error_type="query_plan_generation_failed",
                metadata={"intent": intent},
            )
        req.status = RequestStatus.error
        req.err = str(e)
        await update_request_status(RequestStatus.error, req.err, db, req.request_id)
        raise

    logger.info(
        "Generated query plan",
        flow_stage="llm_query_plan",
        flow_step_num=next(flow_step),
        plan_summary=llm_response.plan_summary,
        tables=llm_response.tables,
        complexity=llm_response.estimated_complexity,
    )

    # Note: FeedbackRequested status is set by the orchestrator after this returns

    return llm_response
