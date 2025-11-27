"""Discovery handler - welcome user and show database overview."""

from datetime import datetime

from fm_app.api.model import (
    IntentAnalysis,
    McpServerRequest,
    RequestStatus,
    StructuredResponse,
)
from fm_app.db.db import (
    update_request_status,
)
from fm_app.mcp_servers.db_meta import get_db_meta_database_overview
from fm_app.workers.interactive_flow.setup import FlowContext


async def handle_discovery(ctx: FlowContext) -> None:
    """Handle discovery flow - welcome user and show database overview."""
    req = ctx.req
    logger = ctx.logger
    settings = ctx.settings
    ai_model = ctx.ai_model
    assembler = ctx.assembler
    db = ctx.db
    flow_step = ctx.flow_step

    intent_hint = f"Intent Hint: {req.request_type}"

    # Detect which command was used to determine mode
    request_text = req.request.strip().lower()
    mode = "new" if request_text.startswith("/new") else "help"

    await update_request_status(RequestStatus.new, None, db, req.request_id)

    # Call db-meta to get database overview
    mcp_ctx = {
        "req": McpServerRequest(
            request_id=req.request_id,
            db=req.db,
            request=f"{req.request}|mode={mode}",  # Pass mode in request
            session_id=req.session_id,
            model=req.model,
            flow=req.flow,
        ),
        "flow_step_num": next(flow_step),
    }

    # For /new: return deterministic response from db-meta without LLM
    if mode == "new":

        # Get database overview directly from MCP (skip slot rendering for speed)
        logger.info(
            "Fetching database overview for /new",
            flow_stage="discovery_mcp",
            flow_step_num=next(flow_step),
            mode=mode,
        )

        db_overview_text = await get_db_meta_database_overview(
            req=mcp_ctx["req"],
            flow_step_num=next(flow_step),
            settings=settings,
            logger=logger,
        )

        logger.info(
            "Using deterministic response for /new",
            flow_stage="discovery_deterministic",
            flow_step_num=next(flow_step),
            overview_length=len(db_overview_text),
        )

        response_text = db_overview_text
    else:
        # For /help: use LLM to generate enhanced response
        logger.info(
            "Fetching database overview for /help",
            flow_stage="discovery_mcp",
            flow_step_num=next(flow_step),
            mode=mode,
        )

        # The assembler will call get_database_overview MCP tool when rendering the slot
        discovery_vars = {
            "client_id": settings.client_id,
            "intent_hint": intent_hint,
            "db_overview": "",  # Will be populated by MCP tool
            "current_datetime": datetime.now(),
        }

        slot = await assembler.render_async(
            "discovery", variables=discovery_vars, req_ctx=mcp_ctx, mcp_caps=None
        )

        discovery_llm_system_prompt = slot.prompt_text

        if ai_model.get_name() != "gemini":
            messages = [{"role": "system", "content": discovery_llm_system_prompt}]
            messages.append({"role": "user", "content": req.request})
        else:
            messages = f"""
                 {discovery_llm_system_prompt}\n
                 User input: {req.request}\n"""

        logger.info(
            "Prepared discovery request for /help",
            flow_stage="discovery",
            flow_step_num=next(flow_step),
            ai_request=messages,
        )

        await update_request_status(RequestStatus.intent, None, db, req.request_id)

        try:
            llm_response = ai_model.get_structured(
                messages, IntentAnalysis, "gpt-4o-mini"
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
            await update_request_status(
                RequestStatus.error, req.err, db, req.request_id
            )
            return

        await update_request_status(RequestStatus.finalizing, None, db, req.request_id)

        response_text = llm_response.intent

    logger.info(
        "Flow complete",
        flow_stage="end",
        flow_step_num=next(flow_step),
        flow=req.flow,
        intent=response_text,
        mode=mode,
    )

    await update_request_status(RequestStatus.done, None, db, req.request_id)

    req.status = RequestStatus.done
    req.response = response_text
    req.structured_response = StructuredResponse(
        intent=response_text,
        description=response_text,
        intro=None,
        sql=None,
        metadata=None,
        refs=None,
    )

