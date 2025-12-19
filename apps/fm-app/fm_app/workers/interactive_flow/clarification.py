"""Clarification handling for interactive flow.

This module handles the clarification request/response cycle:
1. When intent analysis determines clarification is needed, we return a structured
   question to the user with optional multiple-choice options.
2. When the user responds, we combine their answer with the original context
   and re-run intent analysis with the clarified information.
"""

from fm_app.api.model import (
    ClarificationData,
    IntentAnalysis,
    RequestStatus,
    StructuredResponse,
    WorkerRequest,
)
from fm_app.db.db import update_request_status
from fm_app.workers.interactive_flow.setup import FlowContext


async def handle_clarification_request(
    ctx: FlowContext,
    intent: IntentAnalysis,
) -> WorkerRequest:
    """
    Handle a clarification request from intent analysis.

    This is called when the LLM determines it needs more information
    before proceeding with query generation.

    Args:
        ctx: Flow context with request, logger, db connections
        intent: Intent analysis result with clarification fields populated

    Returns:
        WorkerRequest with status=feedback_requested and clarification data
    """
    req = ctx.req

    # Build clarification response
    clarification = ClarificationData(
        question=intent.clarification_question or "Could you provide more details?",
        options=intent.clarification_options,
        context=intent.clarification_context,
        allow_freeform=True,
    )

    if req.structured_response is None:
        req.structured_response = StructuredResponse()

    req.structured_response.response_type = "clarification"
    req.structured_response.clarification = clarification
    req.structured_response.intent = intent.intent

    # Set status to await user response
    req.status = RequestStatus.feedback_requested
    await update_request_status(
        RequestStatus.feedback_requested, None, ctx.db, req.request_id
    )

    ctx.logger.info(
        "Clarification requested",
        flow_stage="clarification_request",
        question=clarification.question,
        options=clarification.options,
        context=clarification.context,
    )

    return req


async def handle_clarification_response(ctx: FlowContext) -> WorkerRequest:
    """
    Handle user's response to a clarification question.

    This is called when the user responds to a clarification request.
    We combine their answer with the original context and re-run intent analysis.

    Args:
        ctx: Flow context with request, logger, db connections

    Returns:
        WorkerRequest - processing continues based on new intent analysis
    """
    req = ctx.req

    # Get the previous request that asked the clarification
    from fm_app.db.db import get_previous_request

    prev_request = await get_previous_request(ctx.db, req.session_id, req.request_id)

    original_intent = ""
    if prev_request:
        # Use the intent from the previous request as context
        original_intent = prev_request.intent or prev_request.request or ""

    clarification_answer = req.request

    # Combine original intent with user's clarification for re-analysis
    if original_intent:
        combined_context = (
            f"{original_intent}\n\nUser clarification: {clarification_answer}"
        )
    else:
        combined_context = clarification_answer

    # Update the request text to include the clarified context
    req.request = combined_context

    ctx.logger.info(
        "Processing clarification response",
        flow_stage="clarification_response",
        original_intent=original_intent[:200] if original_intent else None,
        clarification=clarification_answer[:200] if clarification_answer else None,
    )

    # Re-run intent analysis with the clarified context
    from fm_app.workers.interactive_flow.intent_analyzer import analyze_intent

    try:
        intent = await analyze_intent(ctx)
    except Exception as e:
        ctx.logger.error(
            "Intent analysis failed after clarification",
            flow_stage="error_clarification_intent",
            error=str(e),
        )
        return req

    # Route based on the new intent (import here to avoid circular dependency)
    from fm_app.workers.interactive_flow import _route_by_intent

    return await _route_by_intent(ctx, intent)
