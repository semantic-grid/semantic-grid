"""
Interactive Query Flow - Structured SQL generation with validation and repair loop.

This flow handles interactive query requests through a structured, iterative approach:

1. **Prompt Assembly**: Builds system prompt using the "interactive_query" slot with MCP context
2. **Conversation Context**: Includes session history to maintain conversational continuity
3. **Structured LLM Response**: Requests QueryMetadata (summary, description, SQL, columns, result)
4. **Validation Loop** (up to 3 attempts):
   - Validates QueryMetadata consistency (SQL columns match metadata column_name values)
   - Validates SQL via db-meta MCP server (explain_analyze)
   - On validation errors: adds feedback to conversation and retries
   - On SQL errors: extracts DB exception, provides repair instructions, retries
5. **Query Storage**: Persists validated query with metadata, lineage (parent_id), and explanation
6. **Session Management**: Updates session name with query summary for context
7. **Response**: Returns structured response with intent, description, SQL, and metadata

Key features:
- Retry loop handles both metadata validation errors and SQL execution errors
- Maintains query lineage through parent_id relationships
- Stores rich metadata including columns, explanations, and row counts
- Supports conversational queries that reference previous queries in the session
- Validates that metadata columns exactly match SQL result columns

This flow is optimized for interactive data exploration where users iteratively
refine queries and build on previous results.
"""

import re

from fm_app.api.v1.model import (
    CreateQueryModel,
    IntentAnalysis,
    McpServerRequest,
    QueryMetadata,
    RequestStatus,
    StructuredResponse,
    UpdateRequestModel,
)
from fm_app.db.db import (
    count_wh_request,
    create_query,
    get_all_requests,
    get_history,
    get_query_history,
    update_query_metadata,
    update_request,
    update_request_status,
    update_session_name,
)
from fm_app.mcp_servers.db_meta import db_meta_mcp_analyze_query
from fm_app.stopwatch import stopwatch
from fm_app.validators import MetadataValidator
from fm_app.workers.interactive_flow.setup import FlowContext, build_prompt_variables


async def handle_interactive_query(ctx: FlowContext, intent: IntentAnalysis) -> None:
    """Handle interactive query flow with SQL generation and repair loop."""
    req = ctx.req
    logger = ctx.logger
    settings = ctx.settings
    ai_model = ctx.ai_model
    assembler = ctx.assembler
    db = ctx.db
    db_wh = ctx.db_wh
    warehouse_dialect = ctx.warehouse_dialect
    flow_step = ctx.flow_step
    request_session = ctx.request_session

    # Use query-specific history if working on a specific query (via /for_query endpoint)
    # Otherwise use session history for new queries
    if req.query is not None:
        history = await get_query_history(
            db, req.query.query_id, include_responses=False
        )
        logger.info(
            "Using query-specific history",
            flow_stage="query_history",
            flow_step_num=next(flow_step),
            query_id=str(req.query.query_id),
            history_length=len(history),
        )
    else:
        history = await get_history(db, req.session_id, include_responses=False)
        logger.info(
            "Using session history",
            flow_stage="session_history",
            flow_step_num=next(flow_step),
            history_length=len(history),
        )

    interactive_query_vars = await build_prompt_variables(ctx)

    db_meta_caps = {}
    mcp_ctx = {
        "req": McpServerRequest(
            request_id=req.request_id,
            session_id=req.session_id,
            db=req.db,
            request=req.request,
            model=req.model,
            flow=req.flow,
        ),
        "flow_step_num": next(flow_step),
    }

    print(">>> PRE MCP", stopwatch.lap())

    slot = await assembler.render_async(
        "interactive_query",
        variables=interactive_query_vars,
        req_ctx=mcp_ctx,
        mcp_caps=db_meta_caps,
    )

    print(">>> POST MCP", stopwatch.lap())

    query_llm_system_prompt = slot.prompt_text

    if ai_model.get_name() != "gemini":
        messages = [{"role": "system", "content": query_llm_system_prompt}]
        for item in history:
            if item.get("content") is not None:
                messages.append(item)
        messages.append({"role": "user", "content": req.request})
    else:
        messages = f"""
            {query_llm_system_prompt}\n
            User input: {req.request}\n"""

    # Do at most 3 attempts to generate valid SQL
    attempt = 1
    while attempt <= 3:
        await update_request_status(RequestStatus.sql, None, db, req.request_id)
        logger.info(
            "Prepared ai_request",
            flow_stage="ask_llm",
            flow_step_num=next(flow_step),
            ai_request=messages,
        )

        print(">>> PRE QUERY", stopwatch.lap())

        try:
            llm_response = ai_model.get_structured(messages, QueryMetadata)
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

        print(">>> POST QUERY", stopwatch.lap())

        if ai_model.get_name() != "gemini":
            messages.append(
                {"role": "assistant", "content": llm_response.model_dump_json()}
            )
        else:
            messages = f"""
             {messages}\n
             AI response: {llm_response.model_dump_json()}\n"""

        logger.info(
            "Got response",
            flow_stage="llm_resp",
            flow_step_num=next(flow_step),
            ai_response=llm_response,
        )

        # Validate QueryMetadata consistency
        validation_result = MetadataValidator.validate_metadata(
            llm_response, dialect=warehouse_dialect
        )
        if not validation_result["valid"]:
            logger.warning(
                "QueryMetadata validation failed",
                flow_stage="metadata_validation",
                flow_step_num=next(flow_step),
                errors=validation_result["errors"],
                warnings=validation_result["warnings"],
                sql_columns=validation_result["sql_columns"],
                metadata_columns=validation_result["metadata_columns"],
            )
            # Add validation errors to the repair loop
            if attempt < 3:
                errors_list = "\n".join(
                    f"  - {err}" for err in validation_result["errors"]
                )
                validation_error_msg = (
                    "QueryMetadata validation errors detected:\n"
                    f"{errors_list}\n\n"
                    f"SQL result columns: {validation_result['sql_columns']}\n"
                    f"Metadata column_name values: "
                    f"{validation_result['metadata_columns']}\n\n"
                    "Please fix the column_name values in the Column objects.\n"
                    "Remember: column_name must be the alias "
                    "(the name after AS), not the expression.\n"
                    "For example: 'DATE(block_time) AS trade_date' -> "
                    "column_name should be 'trade_date'"
                )

                messages.append(
                    {
                        "role": "system",
                        "content": validation_error_msg,
                    }
                )

                logger.info(
                    "Added validation errors to repair loop",
                    flow_stage="metadata_repair",
                    flow_step_num=next(flow_step),
                )
                attempt += 1
                continue
        else:
            logger.info(
                "QueryMetadata validation passed",
                flow_stage="metadata_validation",
                flow_step_num=next(flow_step),
            )

        await update_session_name(req.session_id, req.user, llm_response.summary, db)

        if (request_session.parent is not None) and (
            request_session.parent not in llm_response.parents
        ):
            llm_response.parents.append(request_session.parent)

        new_metadata = llm_response.model_dump()

        await update_request_status(RequestStatus.finalizing, None, db, req.request_id)

        if new_metadata.get("sql") is not None:
            extracted_sql = new_metadata.get("sql")
            logger.info(
                "Extracted SQL",
                flow_stage="extracted_sql",
                flow_step_num=next(flow_step),
                extracted_sql=extracted_sql,
            )

            print(">>> PRE ANALYZE", stopwatch.lap())

            analyzed = await db_meta_mcp_analyze_query(
                req, extracted_sql, 5, settings, logger
            )

            print(">>> POST ANALYZE", stopwatch.lap())

            if analyzed.get("explanation"):
                explanation = analyzed.get("explanation")[0]
                new_metadata.update({"explanation": explanation})
            elif analyzed.get("error"):
                err = analyzed.get("error")
                await update_request_status(
                    RequestStatus.error, err, db, req.request_id
                )
                logger.info(
                    "Error analyzing SQL",
                    flow_stage="analyze_sql_error",
                    flow_step_num=next(flow_step),
                    error=err,
                )
                req.status = RequestStatus.retry
                # Instead of returning, increment attempt and keep going
                attempt += 1
                error_pattern = r"(DB::Exception.*?)Stack trace"
                error_match = re.search(error_pattern, str(err), re.DOTALL)
                error_message = error_match.group(1) if error_match else str(err)

                messages.append(
                    {
                        "role": "system",
                        "content": f"""
                            We have got DB exception: {error_message}\n.
                            Please regenerate SQL to fix the issue.
                            Remember instructions from original prompt!.
                        """,
                    }
                )
                continue

            # Row count commented out - keep for future use
            print(">>> PRE ROW COUNT", stopwatch.lap())
            try:
                row_count = count_wh_request(extracted_sql, db_wh)
                new_metadata.update({"row_count": row_count})
                print(">>> POST ROW COUNT", stopwatch.lap())

            except Exception as e:
                await update_request_status(
                    RequestStatus.error, str(e), db, req.request_id
                )
                logger.info(
                    "Error counting rows",
                    flow_stage="count_rows_error",
                    flow_step_num=next(flow_step),
                    error=str(e),
                )

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
                    parent_id = (
                        request.query.query_id if request.query.query_id else None
                    )
                    break

            new_query = CreateQueryModel(
                request=req.request,
                intent=intent.intent if intent else None,
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

        elif new_metadata.get("result") is not None:
            req.response = new_metadata.get("result")

            logger.info(
                "Response without SQL",
                flow_stage="response_without_sql",
                flow_step_num=next(flow_step),
            )

            await update_query_metadata(
                session_id=req.session_id,
                user_owner=req.user,
                metadata=new_metadata,
                db=db,
            )

        else:
            await update_request_status(
                RequestStatus.error, "No SQL", db, req.request_id
            )
            logger.info(
                "Can't extract SQL to get the data",
                flow_stage="no_sql",
                flow_step_num=next(flow_step),
            )
            return

        # Complete the flow
        logger.info(
            "Flow complete",
            flow_stage="end",
            flow_step_num=next(flow_step),
            flow=req.flow,
            metadata=new_metadata,
        )

        await update_request_status(RequestStatus.done, None, db, req.request_id)

        req.response = llm_response.result
        req.structured_response = StructuredResponse(
            intent=llm_response.summary,
            description=llm_response.description,
            intro=llm_response.result,
            sql=llm_response.sql,
            metadata=new_metadata,
            refs=req.refs,
        )

        print(">>> DONE INTERACTIVE QUERY", stopwatch.lap())
        return

    # If we reach here, exhausted all attempts
    await update_request_status(
        RequestStatus.error,
        "Failed to generate valid SQL after 3 attempts",
        db,
        req.request_id,
    )
    logger.info(
        "Failed to generate valid SQL after 3 attempts",
        flow_stage="failed_sql_generation",
        flow_step_num=next(flow_step),
    )
    req.status = RequestStatus.error
    req.err = "Failed to generate valid SQL after 3 attempts"
