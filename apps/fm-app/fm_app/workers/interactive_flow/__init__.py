"""Interactive flow orchestrator - main entry point."""

from typing import Type

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel
from fm_app.api.model import (
    IntentAnalysis,
    InteractiveRequestType,
    PlanningMode,
    RequestStatus,
    StructuredResponse,
    WorkerRequest,
)
from fm_app.config import get_settings
from fm_app.db.db import update_request_status
from fm_app.workers.interactive_flow.data_analysis import handle_data_analysis
from fm_app.workers.interactive_flow.discovery import handle_discovery
from fm_app.workers.interactive_flow.general_response import handle_general_response
from fm_app.workers.interactive_flow.intent_analyzer import analyze_intent
from fm_app.workers.interactive_flow.interactive_query import handle_interactive_query
from fm_app.workers.interactive_flow.linked_query import handle_linked_query
from fm_app.workers.interactive_flow.manual_query import handle_manual_query
from fm_app.workers.interactive_flow.query_planner import generate_query_plan
from fm_app.workers.interactive_flow.setup import initialize_flow


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
            await handle_interactive_query(ctx, intent)
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
            # Pass plan_id so the query can be linked to the plan after creation
            await handle_interactive_query(
                ctx, intent, query_plan=query_plan, plan_id=plan_id
            )
        return req

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
                await handle_interactive_query(ctx, intent)
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
            await handle_interactive_query(
                ctx, intent, query_plan=query_plan, plan_id=plan_id
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
