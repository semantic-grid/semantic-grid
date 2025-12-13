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
        # Get the approved plan from the previous FeedbackRequested request
        from fm_app.db.db import get_previous_request_with_plan

        prev_request = await get_previous_request_with_plan(req.session_id, ctx.db)
        query_plan = None

        if prev_request and prev_request.query_plan:
            query_plan = prev_request.query_plan
            ctx.logger.info(
                "Retrieved query plan from previous request",
                flow_stage="plan_approval_retrieve",
                previous_request_id=str(prev_request.request_id),
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
            # Create intent using the original intent from the plan request
            intent = IntentAnalysis(
                intent=prev_request.intent if prev_request else req.request,
                request_type=InteractiveRequestType.plan_approval,
                requires_plan_approval=False,
            )
            await handle_interactive_query(ctx, intent, query_plan=query_plan)
        return req

    elif req.request_type == InteractiveRequestType.plan_amendment:
        # User requested changes to the plan - re-run planning with their feedback
        from fm_app.db.db import get_previous_request_with_plan

        prev_request = await get_previous_request_with_plan(req.session_id, ctx.db)

        # Build combined intent: original intent + user's amendment request
        original_intent = prev_request.intent if prev_request else ""
        amendment_request = req.request

        combined_intent = f"{original_intent}\n\nUser feedback: {amendment_request}"

        ctx.logger.info(
            "Processing plan amendment",
            flow_stage="plan_amendment",
            original_intent=original_intent,
            amendment_request=amendment_request,
        )

        # Re-run query planning with the combined intent
        try:
            query_plan = await generate_query_plan(ctx, combined_intent)
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
            # Determine if planning step should run based on planning_mode setting
            settings = get_settings()
            planning_mode = PlanningMode(settings.planning_mode)

            should_run_planning = False
            if planning_mode == PlanningMode.always:
                should_run_planning = True
            elif planning_mode == PlanningMode.intent_based:
                should_run_planning = intent.requires_plan_approval
            # planning_mode == PlanningMode.never: should_run_planning stays False

            ctx.logger.info(
                "Planning decision",
                flow_stage="planning_decision",
                planning_mode=str(planning_mode),
                requires_plan_approval=intent.requires_plan_approval,
                should_run_planning=should_run_planning,
            )

            if should_run_planning:
                try:
                    query_plan = await generate_query_plan(ctx, intent.intent)
                except Exception as e:
                    # Log the exception for debugging
                    ctx.logger.error(
                        "Query planning failed",
                        flow_stage="error_query_plan",
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    return req

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

            # Simple query - proceed directly to SQL generation
            await handle_interactive_query(ctx, intent)
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
