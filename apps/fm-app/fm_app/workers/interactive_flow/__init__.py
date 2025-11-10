"""Interactive flow orchestrator - main entry point."""

from typing import Type

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel
from fm_app.api.v1.model import InteractiveRequestType, RequestStatus, WorkerRequest
from fm_app.db.db import update_request_status
from fm_app.stopwatch import stopwatch
from fm_app.workers.interactive_flow.data_analysis import handle_data_analysis
from fm_app.workers.interactive_flow.discovery import handle_discovery
from fm_app.workers.interactive_flow.general_response import handle_general_response
from fm_app.workers.interactive_flow.intent_analyzer import analyze_intent
from fm_app.workers.interactive_flow.interactive_query import handle_interactive_query
from fm_app.workers.interactive_flow.linked_query import handle_linked_query
from fm_app.workers.interactive_flow.manual_query import handle_manual_query
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
    print(">>> FLOW START", stopwatch.lap())

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
