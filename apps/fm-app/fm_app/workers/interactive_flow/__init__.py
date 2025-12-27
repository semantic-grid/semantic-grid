"""Interactive flow orchestrator - main entry point."""

from typing import Type

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel
from fm_app.api.model import (
    IntentAnalysis,
    InteractiveRequestType,
    McpServerRequest,
    PlanningMode,
    QueryPlan,
    RequestStatus,
    StructuredResponse,
    WorkerRequest,
)
from fm_app.config import get_settings
from fm_app.db.db import update_request_status
from fm_app.mcp_servers.db_meta import (
    format_table_details_for_prompt,
    get_table_details_mcp,
)
from fm_app.workers.interactive_flow.clarification import (
    handle_clarification_request,
    handle_clarification_response,
)
from fm_app.workers.interactive_flow.data_analysis import handle_data_analysis
from fm_app.workers.interactive_flow.discovery import handle_discovery
from fm_app.workers.interactive_flow.general_response import handle_general_response
from fm_app.workers.interactive_flow.intent_analyzer import analyze_intent
from fm_app.workers.interactive_flow.interactive_query import (
    QueryResult,
    handle_interactive_query,
)
from fm_app.workers.interactive_flow.linked_query import handle_linked_query
from fm_app.workers.interactive_flow.manual_query import handle_manual_query
from fm_app.workers.interactive_flow.query_planner import generate_query_plan
from fm_app.workers.interactive_flow.setup import FlowContext, initialize_flow


async def _enrich_plan_with_schema(
    ctx: FlowContext,
    query_plan: QueryPlan,
) -> QueryPlan:
    """
    Fetch detailed schema for tables in the plan and populate relevant_schema.

    This is the key step that solves the RAG gap: the planner selects tables
    based on domain knowledge (even if they weren't in RAG top-k), and we
    fetch their full schema here for SQL generation.

    Args:
        ctx: Flow context
        query_plan: Query plan with tables selected by planner

    Returns:
        QueryPlan with relevant_schema populated
    """
    if not query_plan.tables:
        ctx.logger.info(
            "No tables in plan, skipping schema fetch",
            flow_stage="schema_fetch_skip",
        )
        return query_plan

    # Skip if schema already populated (e.g., from cache or previous run)
    if query_plan.relevant_schema:
        ctx.logger.info(
            "Plan already has relevant_schema, skipping fetch",
            flow_stage="schema_fetch_skip",
            tables=query_plan.tables,
        )
        return query_plan

    try:
        # Build MCP request context
        mcp_req = McpServerRequest(
            request_id=ctx.req.request_id,
            db=ctx.req.db,
            request=ctx.req.request,
            session_id=ctx.req.session_id,
            model=ctx.req.model,
            flow=ctx.req.flow,
        )

        ctx.logger.info(
            "Fetching detailed schema for plan tables",
            flow_stage="schema_fetch_start",
            tables=query_plan.tables,
        )

        # Fetch table details via MCP
        # Only request relationships - skip expensive stats (cardinality, ranges)
        table_details = await get_table_details_mcp(
            req=mcp_req,
            tables=query_plan.tables,
            flow_step_num=next(ctx.flow_step),
            settings=ctx.settings,
            logger=ctx.logger,
            include=["relationships"],  # Schema + PK/FK only, no expensive stats
            client=ctx.mcp_client,  # Reuse session
        )

        # Format for prompt
        schema_text = format_table_details_for_prompt(table_details)

        ctx.logger.info(
            "Schema fetched successfully",
            flow_stage="schema_fetch_complete",
            tables=query_plan.tables,
            schema_length=len(schema_text),
            tables_returned=len(table_details.tables) if table_details.tables else 0,
        )

        # Populate the plan's relevant_schema field
        query_plan.relevant_schema = schema_text

    except Exception as e:
        ctx.logger.warning(
            "Failed to fetch schema for plan tables, continuing without",
            flow_stage="schema_fetch_error",
            tables=query_plan.tables,
            error=str(e),
        )
        # Continue without schema - SQL generation will use whatever MCP provides

    return query_plan


async def _handle_replan_on_failure(
    ctx,
    req: WorkerRequest,
    intent: IntentAnalysis,
    query_result: QueryResult,
    original_plan_id=None,
) -> WorkerRequest:
    """
    Handle re-planning when query generation fails after max retries.

    This function generates a new plan with error context and returns it
    to the user for approval. The user must explicitly approve the new plan.

    Args:
        ctx: Flow context
        req: Worker request
        intent: Original intent analysis
        query_result: Result from failed query generation (contains errors)
        original_plan_id: ID of the plan that led to failure (for lineage)

    Returns:
        WorkerRequest with new plan for user approval
    """
    # Build error context for the new plan
    error_context = ""
    if query_result.errors:
        error_msgs = [
            f"- {e.get('type', 'error')}: {e.get('error', 'unknown')}"
            for e in query_result.errors
        ]
        error_context = (
            "\n\nPrevious SQL generation failed with errors:\n"
            + "\n".join(error_msgs)
            + "\n\nPlease create a revised plan that avoids these issues."
        )

    # Combine original intent with error feedback
    combined_intent = f"{intent.intent}{error_context}"

    ctx.logger.info(
        "Re-planning after query failure",
        flow_stage="replan_on_failure",
        original_plan_id=str(original_plan_id) if original_plan_id else None,
        error_count=len(query_result.errors) if query_result.errors else 0,
    )

    try:
        new_plan, new_plan_id = await generate_query_plan(
            ctx,
            combined_intent,
            parent_plan_id=original_plan_id,
            amendment_feedback="Query generation failed - revised plan needed",
        )
    except Exception as e:
        ctx.logger.error(
            "Re-planning also failed",
            flow_stage="error_replan",
            error=str(e),
        )
        # Keep the error status from query generation
        return req

    # Return new plan for user approval (always require approval for re-plans)
    if req.structured_response is None:
        req.structured_response = StructuredResponse()
    req.structured_response.query_plan = new_plan
    req.structured_response.intent = intent.intent
    req.structured_response.response_type = "plan_approval"
    req.structured_response.replan_reason = (
        "The previous plan could not be executed successfully. "
        "Please review the revised plan."
    )
    req.status = RequestStatus.feedback_requested
    await update_request_status(
        RequestStatus.feedback_requested, None, ctx.db, req.request_id
    )

    ctx.logger.info(
        "Re-plan generated, awaiting user approval",
        flow_stage="replan_awaiting_approval",
        new_plan_id=str(new_plan_id) if new_plan_id else None,
        plan_summary=new_plan.plan_summary[:100] if new_plan else None,
    )

    return req


async def _route_by_intent(ctx: FlowContext, intent: IntentAnalysis) -> WorkerRequest:
    """
    Route request based on analyzed intent.

    This helper is used both by the main interactive_flow and by
    handle_clarification_response after re-analyzing intent.

    Args:
        ctx: Flow context
        intent: Analyzed intent

    Returns:
        WorkerRequest with appropriate status and response
    """
    req = ctx.req
    db = ctx.db

    # Handle clarification requests
    if (
        intent.clarification_needed
        or intent.request_type == InteractiveRequestType.clarification
    ):
        return await handle_clarification_request(ctx, intent)

    # Route based on analyzed intent
    if intent.request_type in (
        InteractiveRequestType.linked_session,
        InteractiveRequestType.interactive_query,
    ):
        # Always generate a plan for lineage/analytics
        # Then decide whether to wait for user approval or auto-approve
        settings = get_settings()
        planning_mode = PlanningMode(settings.planning_mode)

        # Generate plan for every query (ensures plan_id lineage)
        try:
            query_plan, plan_id = await generate_query_plan(ctx, intent.intent)
        except Exception as e:
            ctx.logger.error(
                "Query planning failed",
                flow_stage="error_query_plan",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Fall back to query without plan on planning failure
            _ = await handle_interactive_query(ctx, intent)
            return req

        # Determine if we need user approval or can auto-approve
        requires_user_approval = False
        if planning_mode == PlanningMode.always:
            requires_user_approval = True
        elif planning_mode == PlanningMode.intent_based:
            is_simple = (
                not intent.requires_plan_approval
                or query_plan.estimated_complexity == "simple"
            )
            requires_user_approval = not is_simple

        ctx.logger.info(
            "Planning decision",
            flow_stage="planning_decision",
            planning_mode=str(planning_mode),
            intent_requires_approval=intent.requires_plan_approval,
            plan_complexity=query_plan.estimated_complexity,
            requires_user_approval=requires_user_approval,
            plan_id=str(plan_id) if plan_id else None,
        )

        if requires_user_approval:
            if req.structured_response is None:
                req.structured_response = StructuredResponse()
            req.structured_response.query_plan = query_plan
            req.structured_response.intent = intent.intent
            req.structured_response.response_type = "plan_approval"
            req.status = RequestStatus.feedback_requested
            await update_request_status(
                RequestStatus.feedback_requested, None, db, req.request_id
            )
            return req

        # Auto-approve: proceed directly to SQL generation
        ctx.logger.info(
            "Auto-approving plan",
            flow_stage="plan_auto_approve",
            plan_id=str(plan_id) if plan_id else None,
            plan_summary=query_plan.plan_summary[:100] if query_plan else None,
        )

        # Fetch detailed schema for tables in the plan (Phase 3: Plan-Driven Schema)
        query_plan = await _enrich_plan_with_schema(ctx, query_plan)

        query_result = await handle_interactive_query(
            ctx, intent, query_plan=query_plan, plan_id=plan_id
        )

        if query_result.needs_replan:
            return await _handle_replan_on_failure(
                ctx, req, intent, query_result, original_plan_id=plan_id
            )
        return req

    elif intent.request_type == InteractiveRequestType.data_analysis:
        await handle_data_analysis(ctx)
        return req

    elif intent.request_type in (
        InteractiveRequestType.general_chat,
        InteractiveRequestType.disambiguation,
    ):
        await handle_general_response(ctx, intent)
        return req

    else:
        # Unsupported request type
        await handle_general_response(ctx, intent)
        return req


async def interactive_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
) -> WorkerRequest:
    """
    Main orchestrator for interactive flow.

    Routes requests to appropriate handlers based on request type:
    - manual_query: User provides SQL, extract metadata
    - linked_query: Summarize existing query for new session
    - Other types: Analyze intent first, then route to specific handler
    """

    # Initialize shared context
    ctx = await initialize_flow(req, ai_model, db_wh, db)

    await update_request_status(RequestStatus.in_process, None, db, req.request_id)

    # Use MCP client session for the entire flow to reuse connection
    async with ctx.mcp_client:
        return await _execute_flow(ctx, req)


async def _execute_flow(ctx: FlowContext, req: WorkerRequest) -> WorkerRequest:
    """Execute the flow logic within the MCP client session context."""
    db = ctx.db

    # Route based on initial request type
    if req.request_type == InteractiveRequestType.manual_query:
        await handle_manual_query(ctx)
        return req

    elif req.request_type == InteractiveRequestType.linked_query:
        await handle_linked_query(ctx)
        return req

    elif req.request_type == InteractiveRequestType.discovery:
        await handle_discovery(ctx)
        return req

    elif req.request_type == InteractiveRequestType.plan_approval:
        # User approved a plan - skip intent analysis and proceed directly
        # Get the approved plan from the query_plan table (first-class entity)
        from fm_app.db.db import get_previous_request_with_plan
        from fm_app.db.query_plan_db import get_latest_plan_for_session

        prev_request = await get_previous_request_with_plan(req.session_id, ctx.db)

        # Get the plan from DB (primary source)
        plan_record = await get_latest_plan_for_session(ctx.db, req.session_id)
        plan_id = plan_record.plan_id if plan_record else None

        # Convert DB record to QueryPlan for the handler
        query_plan = plan_record.to_query_plan() if plan_record else None

        # Fallback to JSONB if DB record not found (backward compatibility)
        if query_plan is None and prev_request and prev_request.query_plan:
            query_plan = prev_request.query_plan
            ctx.logger.info(
                "Falling back to JSONB query_plan",
                flow_stage="plan_approval_fallback",
                previous_request_id=str(prev_request.request_id),
            )

        ctx.logger.info(
            "Processing plan_approval request",
            flow_stage="plan_approval_start",
            has_prev_request=prev_request is not None,
            prev_request_id=str(prev_request.request_id) if prev_request else None,
            plan_id=str(plan_id) if plan_id else None,
            has_query_plan=query_plan is not None,
        )

        if query_plan is None:
            ctx.logger.warning(
                "No query plan found for plan_approval",
                flow_stage="plan_approval_error",
            )
            # Create a minimal intent for interactive query fallback
            intent = IntentAnalysis(
                intent=prev_request.intent if prev_request else req.request,
                request_type=InteractiveRequestType.interactive_query,
                requires_plan_approval=False,
            )
            query_result = await handle_interactive_query(ctx, intent)
            # No re-planning for fallback case (no plan to re-plan from)
        else:
            # IMPORTANT: Override req.request with the original intent so the LLM
            # generates SQL for the original query, not for "Approved - proceed..."
            original_intent = (
                plan_record.original_intent
                if plan_record
                else (prev_request.intent if prev_request else req.request)
            )
            req.request = original_intent

            ctx.logger.info(
                "Using original intent for SQL generation",
                flow_stage="plan_approval_intent_override",
                original_intent=original_intent[:200] if original_intent else None,
                plan_id=str(plan_id) if plan_id else None,
            )

            # Create intent using the original intent from the plan request
            intent = IntentAnalysis(
                intent=original_intent,
                request_type=InteractiveRequestType.plan_approval,
                requires_plan_approval=False,
            )

            # Fetch detailed schema for tables in the plan (Phase 3: Plan-Driven Schema)
            query_plan = await _enrich_plan_with_schema(ctx, query_plan)

            # Pass plan_id so the query can be linked to the plan after creation
            query_result = await handle_interactive_query(
                ctx, intent, query_plan=query_plan, plan_id=plan_id
            )

            # Handle re-planning if query generation failed after max retries
            if query_result.needs_replan:
                return await _handle_replan_on_failure(
                    ctx, req, intent, query_result, original_plan_id=plan_id
                )
        return req

    elif req.request_type == InteractiveRequestType.clarification_response:
        # User responded to a clarification question
        return await handle_clarification_response(ctx)

    elif req.request_type == InteractiveRequestType.plan_amendment:
        # User requested changes to the plan - re-run planning with their feedback
        from fm_app.db.db import get_previous_request_with_plan
        from fm_app.db.query_plan_db import get_latest_plan_for_session

        prev_request = await get_previous_request_with_plan(req.session_id, ctx.db)

        # Get the previous plan from DB (first-class entity)
        prev_plan = await get_latest_plan_for_session(ctx.db, req.session_id)
        parent_plan_id = prev_plan.plan_id if prev_plan else None

        # Build combined intent: original intent + user's amendment request
        original_intent = (
            prev_plan.original_intent
            if prev_plan
            else (prev_request.intent if prev_request else "")
        )
        amendment_request = req.request

        combined_intent = f"{original_intent}\n\nUser feedback: {amendment_request}"

        ctx.logger.info(
            "Processing plan amendment",
            flow_stage="plan_amendment",
            original_intent=original_intent,
            amendment_request=amendment_request,
            parent_plan_id=str(parent_plan_id) if parent_plan_id else None,
        )

        # Re-run query planning with the combined intent and parent plan reference
        try:
            query_plan, plan_id = await generate_query_plan(
                ctx,
                combined_intent,
                parent_plan_id=parent_plan_id,
                amendment_feedback=amendment_request,
            )
        except Exception as e:
            ctx.logger.error(
                "Query planning failed during amendment",
                flow_stage="error_plan_amendment",
                error=str(e),
                error_type=type(e).__name__,
            )
            return req

        # Store updated plan and return for user approval again
        if req.structured_response is None:
            req.structured_response = StructuredResponse()
        req.structured_response.query_plan = query_plan
        req.structured_response.intent = combined_intent
        req.structured_response.response_type = "plan_approval"
        req.status = RequestStatus.feedback_requested
        await update_request_status(
            RequestStatus.feedback_requested, None, ctx.db, req.request_id
        )
        return req

    else:
        # For all other types, analyze intent first
        try:
            intent = await analyze_intent(ctx)
        except Exception:
            # Error already logged and status updated in analyze_intent
            return req

        # Handle clarification requests from intent analysis
        if (
            intent.clarification_needed
            or intent.request_type == InteractiveRequestType.clarification
        ):
            return await handle_clarification_request(ctx, intent)

        # Route based on analyzed intent
        if intent.request_type in (
            InteractiveRequestType.linked_session,
            InteractiveRequestType.interactive_query,
        ):
            # Always generate a plan for lineage/analytics
            # Then decide whether to wait for user approval or auto-approve
            settings = get_settings()
            planning_mode = PlanningMode(settings.planning_mode)

            # Generate plan for every query (ensures plan_id lineage)
            try:
                query_plan, plan_id = await generate_query_plan(ctx, intent.intent)
            except Exception as e:
                ctx.logger.error(
                    "Query planning failed",
                    flow_stage="error_query_plan",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Fall back to query without plan on planning failure
                # No re-planning for this case (planning itself failed)
                _ = await handle_interactive_query(ctx, intent)
                return req

            # Determine if we need user approval or can auto-approve
            requires_user_approval = False
            if planning_mode == PlanningMode.always:
                # Always require approval regardless of complexity
                requires_user_approval = True
            elif planning_mode == PlanningMode.intent_based:
                # Require approval based on intent analysis AND plan complexity
                # Auto-approve if: intent says simple OR plan complexity is "simple"
                is_simple = (
                    not intent.requires_plan_approval
                    or query_plan.estimated_complexity == "simple"
                )
                requires_user_approval = not is_simple
            # planning_mode == PlanningMode.never: requires_user_approval stays False

            ctx.logger.info(
                "Planning decision",
                flow_stage="planning_decision",
                planning_mode=str(planning_mode),
                intent_requires_approval=intent.requires_plan_approval,
                plan_complexity=query_plan.estimated_complexity,
                requires_user_approval=requires_user_approval,
                plan_id=str(plan_id) if plan_id else None,
            )

            if requires_user_approval:
                # Store plan in structured response and return for user approval
                if req.structured_response is None:
                    req.structured_response = StructuredResponse()
                req.structured_response.query_plan = query_plan
                req.structured_response.intent = intent.intent
                req.structured_response.response_type = "plan_approval"
                req.status = RequestStatus.feedback_requested
                await update_request_status(
                    RequestStatus.feedback_requested, None, db, req.request_id
                )
                return req

            # Auto-approve: proceed directly to SQL generation with plan context
            ctx.logger.info(
                "Auto-approving plan",
                flow_stage="plan_auto_approve",
                plan_id=str(plan_id) if plan_id else None,
                plan_summary=query_plan.plan_summary[:100] if query_plan else None,
            )

            # Fetch detailed schema for tables in the plan (Phase 3: Plan-Driven Schema)
            query_plan = await _enrich_plan_with_schema(ctx, query_plan)

            query_result = await handle_interactive_query(
                ctx, intent, query_plan=query_plan, plan_id=plan_id
            )

            # Handle re-planning if query generation failed after max retries
            if query_result.needs_replan:
                return await _handle_replan_on_failure(
                    ctx, req, intent, query_result, original_plan_id=plan_id
                )
            return req

        elif intent.request_type == InteractiveRequestType.data_analysis:
            await handle_data_analysis(ctx)
            return req

        elif intent.request_type in (
            InteractiveRequestType.general_chat,
            InteractiveRequestType.disambiguation,
        ):
            await handle_general_response(ctx, intent)
            return req

        else:
            # Unsupported request type
            await handle_general_response(ctx, intent)
            return req
