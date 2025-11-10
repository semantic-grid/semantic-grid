"""General response handler - chat and disambiguation."""

from fm_app.api.v1.model import (
    IntentAnalysis,
    InteractiveRequestType,
    RequestStatus,
    StructuredResponse,
)
from fm_app.db.db import update_request_status
from fm_app.workers.interactive_flow.setup import FlowContext


async def handle_general_response(ctx: FlowContext, intent: IntentAnalysis) -> None:
    """Handle general chat or disambiguation - return response from intent step."""
    req = ctx.req
    logger = ctx.logger
    db = ctx.db
    flow_step = ctx.flow_step
    request_session = ctx.request_session

    if intent.request_type == InteractiveRequestType.general_chat:
        logger.info(
            "Response to user",
            flow_stage="general_chat",
            flow_step_num=next(flow_step),
            ai_response=intent,
        )
    elif intent.request_type == InteractiveRequestType.disambiguation:
        logger.info(
            "Response to user",
            flow_stage="disambiguation",
            flow_step_num=next(flow_step),
            ai_response=intent,
        )
    else:
        logger.info(
            "Unsupported request type",
            flow_stage="unsupported_request_type",
            flow_step_num=next(flow_step),
            ai_response=intent,
        )

    await update_request_status(RequestStatus.done, None, db, req.request_id)

    req.response = (
        intent.response if hasattr(intent, "response") else "Unsupported request type"
    )
    req.structured_response = StructuredResponse(
        intent=intent.request_type if hasattr(intent, "request_type") else "unknown",
        intro=req.response,
        description=None,
        metadata=request_session.metadata,
        refs=req.refs,
    )
