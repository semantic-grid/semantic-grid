"""Query planner - generate human-readable query plan before SQL generation."""

from typing import Optional
from uuid import UUID

from fm_app.api.model import (
    CreateQueryPlanModel,
    McpServerRequest,
    QueryPlan,
    RequestStatus,
)
from fm_app.db.db import (
    get_history,
    get_query_history,
    update_request_status,
)
from fm_app.db.query_plan_db import create_query_plan
from fm_app.mcp_servers.db_meta import validate_query_plan
from fm_app.tracing import TracingTimer
from fm_app.workers.interactive_flow.setup import FlowContext, build_prompt_variables

# Maximum number of plan generation attempts before giving up
MAX_PLAN_ATTEMPTS = 3


async def generate_query_plan(
    ctx: FlowContext,
    intent: str,
    parent_plan_id: Optional[UUID] = None,
    amendment_feedback: Optional[str] = None,
) -> tuple[QueryPlan, UUID]:
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

    Args:
        ctx: Flow context with DB session, logger, etc.
        intent: The user's intent (original or combined with amendments)
        parent_plan_id: ID of the previous plan if this is an amendment
        amendment_feedback: User's feedback that triggered this plan iteration

    Returns:
        Tuple of (QueryPlan, plan_id) where plan_id is the UUID of the saved plan
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
            prompt_content=planner_system_prompt,
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

    # Plan generation loop with validation
    llm_response = None
    validation_feedback = ""
    attempt = 0

    while attempt < MAX_PLAN_ATTEMPTS:
        attempt += 1

        # Build messages with optional validation feedback from previous attempt
        current_messages = messages.copy() if isinstance(messages, list) else messages
        if validation_feedback and isinstance(current_messages, list):
            # Add validation errors as system feedback for retry
            current_messages = messages.copy()
            current_messages.append(
                {
                    "role": "assistant",
                    "content": (
                        f"[Previous plan had validation errors: {validation_feedback}]"
                    ),
                }
            )
            current_messages.append(
                {
                    "role": "user",
                    "content": (
                        "Please regenerate the plan using only valid table "
                        "and column names from the schema."
                    ),
                }
            )

        try:
            with TracingTimer() as llm_timer:
                llm_response = ai_model.get_structured(
                    current_messages, QueryPlan, "gpt-4.1-2025-04-14"
                )

            # Trace LLM call
            if tracer:
                await tracer.trace_llm_call(
                    model=ai_model.get_name(),
                    input_messages=current_messages,
                    output_raw=llm_response.model_dump_json(),
                    output_parsed=llm_response.model_dump(),
                    tokens_in=None,
                    tokens_out=None,
                    duration_ms=llm_timer.duration_ms,
                    metadata={
                        "step": "query_planner",
                        "tables": llm_response.tables,
                        "complexity": llm_response.estimated_complexity,
                        "attempt": attempt,
                    },
                )

        except Exception as e:
            logger.error(
                "Error generating query plan",
                flow_stage="error_query_plan",
                flow_step_num=next(flow_step),
                error=str(e),
                attempt=attempt,
            )
            if tracer:
                await tracer.trace_error(
                    error_message=str(e),
                    error_type="query_plan_generation_failed",
                    metadata={"intent": intent, "attempt": attempt},
                )
            req.status = RequestStatus.error
            req.err = str(e)
            await update_request_status(
                RequestStatus.error, req.err, db, req.request_id
            )
            raise

        logger.info(
            "Generated query plan",
            flow_stage="llm_query_plan",
            flow_step_num=next(flow_step),
            plan_summary=llm_response.plan_summary,
            tables=llm_response.tables,
            columns_referenced=llm_response.columns_referenced,
            complexity=llm_response.estimated_complexity,
            attempt=attempt,
        )

        # Validate plan against schema
        try:
            validation_result = await validate_query_plan(
                req=mcp_ctx["req"],
                tables=llm_response.tables,
                columns_referenced=llm_response.columns_referenced,
                flow_step_num=next(flow_step),
                settings=ctx.settings,
                logger=logger,
                client=ctx.mcp_client,  # Reuse session
            )

            if validation_result.valid:
                logger.info(
                    "Plan validation passed",
                    flow_stage="plan_validation_success",
                    flow_step_num=next(flow_step),
                    attempt=attempt,
                )
                break  # Valid plan, exit loop

            # Plan is invalid - build feedback for next attempt
            error_msgs = []
            for err in validation_result.errors:
                if err.suggestion:
                    error_msgs.append(
                        f"{err.error_type}: '{err.name}' not found, "
                        f"did you mean '{err.suggestion}'?"
                    )
                else:
                    error_msgs.append(
                        f"{err.error_type}: '{err.name}' does not exist in schema"
                    )
            validation_feedback = "; ".join(error_msgs)

            logger.warning(
                "Plan validation failed",
                flow_stage="plan_validation_failed",
                flow_step_num=next(flow_step),
                attempt=attempt,
                errors=validation_feedback,
            )

            if attempt >= MAX_PLAN_ATTEMPTS:
                # Max attempts reached, proceed with invalid plan
                # User will see it and can amend
                logger.warning(
                    "Max plan attempts reached, proceeding with invalid plan",
                    flow_stage="plan_validation_max_attempts",
                    attempt=attempt,
                )
                break

        except Exception as e:
            # Validation call failed - log but proceed with the plan
            logger.warning(
                "Plan validation call failed, proceeding without validation",
                flow_stage="plan_validation_error",
                flow_step_num=next(flow_step),
                error=str(e),
            )
            break  # Proceed with plan even if validation fails

    # Save plan to query_plan table
    # Extract original intent (before any "User feedback:" additions)
    original_intent = intent.split("\n\nUser feedback:")[0] if intent else ""

    plan_db_model = CreateQueryPlanModel.from_query_plan(
        plan=llm_response,
        session_id=req.session_id,
        request_id=req.request_id,
        original_intent=original_intent,
        parent_id=parent_plan_id,
        amendment_feedback=amendment_feedback,
    )

    try:
        saved_plan = await create_query_plan(db, plan_db_model)
        plan_id = saved_plan.plan_id

        logger.info(
            "Saved query plan to database",
            flow_stage="save_query_plan",
            flow_step_num=next(flow_step),
            plan_id=str(plan_id),
            parent_plan_id=str(parent_plan_id) if parent_plan_id else None,
        )
    except Exception as e:
        logger.error(
            "Failed to save query plan to database",
            flow_stage="error_save_query_plan",
            error=str(e),
        )
        # Continue without failing - the plan still works, just not persisted
        plan_id = None

    # Note: FeedbackRequested status is set by the orchestrator after this returns

    return llm_response, plan_id
