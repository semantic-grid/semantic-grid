"""Manual query handler - user provides raw SQL."""

from datetime import datetime

from fm_app.api.model import (
    CreateQueryModel,
    McpServerRequest,
    QueryMetadata,
    RequestStatus,
    StructuredResponse,
    UpdateRequestModel,
)
from fm_app.db.db import (
    create_query,
    get_all_requests,
    update_query_metadata,
    update_request,
    update_request_status,
)
from fm_app.mcp_servers.db_meta import db_meta_mcp_analyze_query
from fm_app.validators import MetadataValidator
from fm_app.workers.interactive_flow.setup import FlowContext


async def handle_manual_query(ctx: FlowContext) -> None:
    """Handle manual query flow - extract metadata from user-provided SQL."""
    req = ctx.req
    logger = ctx.logger
    settings = ctx.settings
    ai_model = ctx.ai_model
    assembler = ctx.assembler
    db = ctx.db
    warehouse_dialect = ctx.warehouse_dialect
    flow_step = ctx.flow_step

    manual_query_vars = {
        "client_id": settings.client_id,
        "request": req.request,
        "current_datetime": datetime.now().replace(microsecond=0),
    }

    await update_request_status(RequestStatus.new, None, db, req.request_id)

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

    slot = await assembler.render_async(
        "manual_query", variables=manual_query_vars, req_ctx=mcp_ctx, mcp_caps=None
    )

    manual_query_llm_system_prompt = slot.prompt_text

    if ai_model.get_name() != "gemini":
        messages = [{"role": "system", "content": manual_query_llm_system_prompt}]
        messages.append({"role": "user", "content": req.request})
    else:
        messages = f"""
                     {manual_query_llm_system_prompt}\n
                     User input: {req.request}\n"""

    logger.info(
        "Prepared manual_query request",
        flow_stage="manual_query",
        flow_step_num=next(flow_step),
        ai_request=messages,
    )

    await update_request_status(RequestStatus.sql, None, db, req.request_id)

    try:
        llm_response = ai_model.get_structured(
            messages, QueryMetadata, "gpt-4.1-mini-2025-04-14"
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
        await update_request_status(RequestStatus.error, req.err, db, req.request_id)
        return

    await update_request_status(RequestStatus.finalizing, None, db, req.request_id)

    if ai_model.get_name() != "gemini":
        messages.append({"role": "assistant", "content": llm_response})
    else:
        messages = f"""
                         {messages}\n
                         AI response: {llm_response}\n"""

    # Validate QueryMetadata consistency
    validation_result = MetadataValidator.validate_metadata(
        llm_response, dialect=warehouse_dialect
    )
    if not validation_result["valid"]:
        logger.warning(
            "QueryMetadata validation failed (manual_query)",
            flow_stage="metadata_validation",
            flow_step_num=next(flow_step),
            errors=validation_result["errors"],
            warnings=validation_result["warnings"],
            sql_columns=validation_result["sql_columns"],
            metadata_columns=validation_result["metadata_columns"],
        )
    else:
        logger.info(
            "QueryMetadata validation passed (manual_query)",
            flow_stage="metadata_validation",
            flow_step_num=next(flow_step),
        )

    new_metadata = llm_response.model_dump()

    if new_metadata.get("sql") is not None:
        extracted_sql = new_metadata.get("sql")
        logger.info(
            "Extracted SQL",
            flow_stage="extracted_sql",
            flow_step_num=next(flow_step),
            extracted_sql=extracted_sql,
        )

        analyzed = await db_meta_mcp_analyze_query(
            req, extracted_sql, 5, settings, logger
        )

        if analyzed.get("explanation"):
            explain_output = analyzed.get("explanation")[0]

            # Build explanation object with EXPLAIN output and performance metrics
            explanation = {
                "explain": explain_output,
            }

            # Add performance metrics if available
            estimated_rows = analyzed.get("estimated_rows")
            estimated_size_gb = analyzed.get("estimated_output_size_gb")

            if estimated_rows is not None:
                explanation["estimated_rows"] = estimated_rows
            if estimated_size_gb is not None:
                explanation["estimated_size_gb"] = estimated_size_gb

            new_metadata.update({"explanation": explanation})
        elif analyzed.get("error"):
            err = analyzed.get("error")
            await update_request_status(RequestStatus.error, err, db, req.request_id)
            logger.info(
                "Error analyzing SQL",
                flow_stage="analyze_sql_error",
                flow_step_num=next(flow_step),
                error=err,
            )
            req.err = analyzed.get("error")
            return

        # Row count commented out - keep for future use
        # print(">>> PRE ROW COUNT", stopwatch.lap())
        # try:
        #     row_count = count_wh_request(extracted_sql, db_wh)
        #     new_metadata.update({"row_count": row_count})
        #     print(">>> POST ROW COUNT", stopwatch.lap())
        # except Exception as e:
        #     await update_request_status(
        #         RequestStatus.error, str(e), db, req.request_id
        #     )
        #     logger.info(
        #         "Error counting rows",
        #         flow_stage="count_rows_error",
        #         flow_step_num=next(flow_step),
        #         error=str(e),
        #     )

        await update_query_metadata(
            session_id=req.session_id,
            user_owner=req.user,
            metadata=new_metadata,
            db=db,
        )

        requests_for_session = await get_all_requests(
            session_id=req.session_id, db=db, user_owner=req.user
        )

        # Find latest query_id to use as parent
        parent_id = None
        for request in requests_for_session:
            if request.query is not None:
                parent_id = request.query.query_id if request.query.query_id else None
                break

        new_query = CreateQueryModel(
            request=req.request,
            intent=new_metadata.get("intent"),
            summary=new_metadata.get("summary"),
            description=new_metadata.get("description"),
            sql=extracted_sql,
            row_count=new_metadata.get("row_count"),
            columns=new_metadata.get("columns"),
            ai_generated=True,
            ai_context=None,
            data_source=req.db,
            db_dialect=warehouse_dialect,
            explanation=new_metadata.get("explanation"),
            parent_id=(req.query.query_id if req.query is not None else parent_id),
        )

        new_query_stored = await create_query(db=db, init=new_query)
        await update_request(
            db=db,
            update=UpdateRequestModel(
                request_id=req.request_id,
                query_id=new_query_stored.query_id,
            ),
        )

        req.response = llm_response.result
        req.structured_response = StructuredResponse(
            intent=llm_response.summary,
            description=llm_response.description,
            intro=llm_response.result,
            sql=llm_response.sql,
            metadata=new_metadata,
            refs=req.refs,
        )
