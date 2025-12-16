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
- On max retries: signals orchestrator to re-plan (requires user approval)

This flow is optimized for interactive data exploration where users iteratively
refine queries and build on previous results.
"""

import re
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fm_app.api.model import (
    CreateQueryModel,
    IntentAnalysis,
    McpServerRequest,
    QueryMetadata,
    QueryPlan,
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
from fm_app.db.query_plan_db import update_query_plan_id
from fm_app.mcp_servers.db_meta import db_meta_mcp_analyze_query
from fm_app.tracing import TracingTimer
from fm_app.validators import MetadataValidator
from fm_app.workers.interactive_flow.setup import FlowContext, build_prompt_variables


@dataclass
class QueryResult:
    """Result of interactive query generation."""

    success: bool
    needs_replan: bool = False
    errors: Optional[list[dict]] = None


async def handle_interactive_query(
    ctx: FlowContext,
    intent: IntentAnalysis,
    query_plan: Optional[QueryPlan] = None,
    plan_id: Optional[UUID] = None,
) -> QueryResult:
    """
    Handle interactive query flow with SQL generation and repair loop.

    Args:
        ctx: Flow context with shared state
        intent: Intent analysis result
        query_plan: Optional approved query plan (if multistep flow)
        plan_id: Optional plan ID to link the resulting query to

    Returns:
        QueryResult with success status and optional re-plan signal
    """
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

    # Trace request context (refs, linked queries, history)
    tracer = ctx.tracer
    if tracer:
        # Build linked query info if available
        linked_query_info = None
        if req.query is not None:
            linked_query_info = {
                "query_id": str(req.query.query_id),
                "summary": req.query.summary,
                "sql": req.query.sql,
            }

        # Extract refs as dict if available
        refs_dict = None
        if req.refs is not None:
            refs_dict = {
                "cols": req.refs.cols,
                "rows": req.refs.rows,
                "parent": str(req.refs.parent) if req.refs.parent else None,
            }

        await tracer.trace_request_context(
            user_request=req.request,
            session_id=str(req.session_id),
            linked_query=linked_query_info,
            parent_query_id=str(req.refs.parent)
            if req.refs and req.refs.parent
            else None,
            refs=refs_dict,
            history_length=len(history),
            intent=intent.intent if intent else None,
            metadata={
                "request_type": str(req.request_type) if req.request_type else None,
                "flow": str(req.flow) if req.flow else None,
                "model": str(req.model) if req.model else None,
            },
        )

    interactive_query_vars = await build_prompt_variables(ctx)

    # Add query plan context if provided (from multistep flow)
    if query_plan is not None:
        # Pass individual plan fields for human-readable template rendering
        interactive_query_vars["query_plan"] = True  # Flag for conditional template
        interactive_query_vars["plan_summary"] = query_plan.plan_summary
        interactive_query_vars["query_plan_tables"] = query_plan.tables or []
        interactive_query_vars["query_plan_columns_selected"] = (
            query_plan.columns_selected or []
        )
        interactive_query_vars["query_plan_filters"] = query_plan.filters or []
        interactive_query_vars["query_plan_aggregations"] = (
            query_plan.aggregations or []
        )
        interactive_query_vars["query_plan_group_by"] = query_plan.group_by or []
        interactive_query_vars["query_plan_order_by"] = query_plan.order_by or []
        interactive_query_vars["query_plan_assumptions"] = query_plan.assumptions or []
        # Use relevant_schema from plan instead of full MCP context
        if query_plan.relevant_schema:
            interactive_query_vars["relevant_schema"] = query_plan.relevant_schema
        logger.info(
            "Using approved query plan",
            flow_stage="query_plan_context",
            flow_step_num=next(flow_step),
            plan_summary=query_plan.plan_summary,
            tables=query_plan.tables,
            has_relevant_schema=bool(query_plan.relevant_schema),
        )

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
        # Signal to MCP provider to skip schema fetch if plan provides it
        "has_query_plan": query_plan is not None and bool(query_plan.relevant_schema),
    }

    with TracingTimer() as prompt_timer:
        slot = await assembler.render_async(
            "interactive_query",
            variables=interactive_query_vars,
            req_ctx=mcp_ctx,
            mcp_caps=db_meta_caps,
        )

    query_llm_system_prompt = slot.prompt_text

    # Trace prompt assembly
    if tracer:
        await tracer.trace_prompt_assembly(
            slot_name="interactive_query",
            prompt_hash=slot.lineage.get("content_hash", "")[:16]
            if slot.lineage
            else "",
            duration_ms=prompt_timer.duration_ms,
            metadata={
                "slot_lineage": slot.lineage,
                "mcp_requirements": slot.lineage.get("mcp_lineage")
                if slot.lineage
                else None,
            },
            prompt_content=query_llm_system_prompt,
        )

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
    # Preserve original result from first LLM response through retries
    # This prevents the result field from being overwritten with "fix" descriptions
    original_result = None
    # Capture all errors encountered during retries for better error reporting
    retry_errors: list[dict] = []
    while attempt <= 3:
        await update_request_status(RequestStatus.sql, None, db, req.request_id)
        logger.info(
            "Prepared ai_request",
            flow_stage="ask_llm",
            flow_step_num=next(flow_step),
            ai_request=messages,
        )

        try:
            with TracingTimer() as llm_timer:
                # Use get_structured_with_usage to get token counts for tracing
                if hasattr(ai_model, "get_structured_with_usage"):
                    llm_result = ai_model.get_structured_with_usage(
                        messages, QueryMetadata
                    )
                    llm_response = llm_result.result
                    tokens_in = llm_result.tokens_in
                    tokens_out = llm_result.tokens_out
                else:
                    llm_response = ai_model.get_structured(messages, QueryMetadata)
                    tokens_in = None
                    tokens_out = None

            # Trace LLM call
            if tracer:
                await tracer.trace_llm_call(
                    model=ai_model.get_name(),
                    input_messages=messages,
                    output_raw=llm_response.model_dump_json(),
                    output_parsed=llm_response.model_dump(),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    duration_ms=llm_timer.duration_ms,
                    metadata={"attempt": attempt},
                )
        except Exception as e:
            logger.error(
                "Error getting LLM response",
                flow_stage="error_llm",
                flow_step_num=next(flow_step),
                error=str(e),
            )
            # Trace error
            if tracer:
                await tracer.trace_error(
                    error_message=str(e),
                    error_type="llm_call_failed",
                    metadata={"attempt": attempt},
                )
            req.status = RequestStatus.error
            req.err = str(e)
            await update_request_status(
                RequestStatus.error, req.err, db, req.request_id
            )
            if tracer:
                await tracer.finalize()
            return QueryResult(success=False)

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

        # Capture original result from first attempt to preserve user-facing description
        if attempt == 1 and llm_response.result:
            original_result = llm_response.result

        # Validate QueryMetadata consistency
        with TracingTimer() as validation_timer:
            validation_result = MetadataValidator.validate_metadata(
                llm_response, dialect=warehouse_dialect
            )

        # Trace validation
        if tracer:
            await tracer.trace_validation(
                validation_type="metadata_validation",
                success=validation_result["valid"],
                errors=[{"error": e} for e in validation_result.get("errors", [])],
                duration_ms=validation_timer.duration_ms,
                metadata={
                    "attempt": attempt,
                    "warnings": validation_result.get("warnings", []),
                },
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
            errors_list = "\n".join(f"  - {err}" for err in validation_result["errors"])
            retry_errors.append(
                {
                    "attempt": attempt,
                    "type": "metadata_validation",
                    "error": errors_list,
                }
            )
            if attempt < 3:
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
                    "column_name should be 'trade_date'\n\n"
                    "IMPORTANT: Keep the 'result' field exactly as you wrote it "
                    "originally. The result should describe what the query "
                    "accomplishes for the user, NOT what you fixed. "
                    "Do NOT mention any fixes or repairs in the result field."
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
                # Trace repair attempt with prompt content
                if tracer:
                    await tracer.trace_repair(
                        repair_attempt=attempt,
                        error_message=errors_list,
                        metadata={
                            "repair_type": "metadata_validation",
                            "repair_prompt": validation_error_msg[:1000],
                        },
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

            # Strip trailing semicolon (breaks Trino subqueries and pagination)
            extracted_sql = extracted_sql.strip().rstrip(";")

            # Validate fully-qualified table names for Trino
            if warehouse_dialect == "trino":
                # Check if SQL contains unqualified table names in FROM/JOIN clauses
                # Pattern: FROM/JOIN followed by table name without catalog.schema prefix
                unqualified_pattern = (
                    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b(?!\s*\.)"
                )
                unqualified_matches = re.findall(
                    unqualified_pattern, extracted_sql, re.IGNORECASE
                )

                if unqualified_matches:
                    # Filter out SQL keywords that might match
                    sql_keywords = {"SELECT", "WHERE", "UNNEST", "LATERAL", "VALUES"}
                    actual_unqualified = [
                        m for m in unqualified_matches if m.upper() not in sql_keywords
                    ]

                    if actual_unqualified:
                        logger.warning(
                            "Unqualified table names detected in Trino SQL",
                            flow_stage="sql_validation",
                            flow_step_num=next(flow_step),
                            unqualified_tables=actual_unqualified,
                        )
                        retry_errors.append(
                            {
                                "attempt": attempt,
                                "type": "unqualified_tables",
                                "error": f"Unqualified: {', '.join(actual_unqualified)}",
                            }
                        )

                        if attempt < 3:
                            validation_error_msg = (
                                f"SQL validation error: Invalid or unqualified table names.\n\n"
                                f"Found invalid table(s): {', '.join(actual_unqualified)}\n\n"
                                f"These tables either:\n"
                                f"1. Do not exist in the database schema, OR\n"
                                f"2. Are missing the required catalog.schema prefix\n\n"
                                f"IMPORTANT: You must ONLY use tables that were "
                                f"provided in the database schema above. Do NOT "
                                f"invent or assume table names.\n\n"
                                f"Review the schema and use the correct fully-qualified "
                                f"table names (e.g., dwh.public.wifi_hotspots, "
                                f"dwh.public.bf_inventory).\n\n"
                                f"Rewrite the SQL query using ONLY tables from "
                                f"the provided schema.\n\n"
                                f"IMPORTANT: Keep the 'result' field exactly as "
                                f"you wrote it originally. The result should "
                                f"describe what the query accomplishes for the "
                                f"user, NOT what you fixed. Do NOT mention any "
                                f"fixes or repairs in the result field."
                            )

                            messages.append(
                                {
                                    "role": "system",
                                    "content": validation_error_msg,
                                }
                            )

                            # Trace repair attempt for unqualified tables
                            if tracer:
                                unqualified_err = ", ".join(actual_unqualified)
                                err_msg = f"Unqualified tables: {unqualified_err}"
                                await tracer.trace_repair(
                                    repair_attempt=attempt,
                                    error_message=err_msg,
                                    metadata={
                                        "repair_type": "unqualified_tables",
                                        "repair_prompt": validation_error_msg[:1000],
                                    },
                                )

                            attempt += 1
                            continue

            logger.info(
                "Extracted SQL",
                flow_stage="extracted_sql",
                flow_step_num=next(flow_step),
                extracted_sql=extracted_sql,
            )

            with TracingTimer() as preflight_timer:
                analyzed = await db_meta_mcp_analyze_query(
                    req, extracted_sql, 5, settings, logger
                )

            # Trace SQL preflight validation
            if tracer:
                preflight_success = analyzed.get("explanation") is not None
                await tracer.trace_validation(
                    validation_type="sql_preflight",
                    success=preflight_success,
                    errors=[{"error": analyzed.get("error")}]
                    if analyzed.get("error")
                    else None,
                    duration_ms=preflight_timer.duration_ms,
                    metadata={
                        "attempt": attempt,
                        "estimated_rows": analyzed.get("estimated_rows"),
                        "estimated_size_gb": analyzed.get("estimated_output_size_gb"),
                    },
                )

            if analyzed.get("explanation"):
                explain_output = analyzed.get("explanation")[0]

                # Check for large result set estimates (Trino only)
                estimated_rows = analyzed.get("estimated_rows")
                estimated_size_gb = analyzed.get("estimated_output_size_gb")

                # Build explanation object with EXPLAIN output and performance metrics
                explanation = {
                    "explain": explain_output,
                }

                if estimated_rows is not None:
                    explanation["estimated_rows"] = estimated_rows
                if estimated_size_gb is not None:
                    explanation["estimated_size_gb"] = estimated_size_gb

                new_metadata.update({"explanation": explanation})

                if estimated_rows is not None:
                    logger.info(
                        "Query estimates from execution plan",
                        flow_stage="query_estimates",
                        flow_step_num=next(flow_step),
                        estimated_rows=estimated_rows,
                        estimated_size_gb=estimated_size_gb,
                    )

                    # Database-specific warning thresholds
                    # Trino is slower with large scans, ClickHouse handles more efficiently
                    if warehouse_dialect == "trino":
                        warning_threshold_rows = 1_000_000_000  # 1B rows for Trino
                        warning_threshold_size_gb = 10.0  # 10 GB for Trino
                    else:  # clickhouse
                        warning_threshold_rows = 5_000_000_000  # 5B rows for ClickHouse
                        warning_threshold_size_gb = 5000.0  # 5TB for ClickHouse

                    if estimated_rows > warning_threshold_rows or (
                        estimated_size_gb is not None
                        and estimated_size_gb > warning_threshold_size_gb
                    ):
                        warning_msg = f"""
                            WARNING: This query may be inefficient and could timeout.

                            Query estimates:
                            - Estimated rows to process: {estimated_rows:,}
                            {f"- Estimated output size: {estimated_size_gb:.2f} GB" if estimated_size_gb else ""}

                            The query appears to be scanning a very large dataset without sufficient filtering or limits.

                            Suggestions to improve performance:
                            1. Add a LIMIT clause if you only need a sample of results
                            2. Add more WHERE filters to reduce the data scanned
                            3. Use approx_distinct() instead of SELECT DISTINCT for cardinality estimates
                            4. Consider using TABLESAMPLE for exploratory queries

                            Would you like to:
                            a) Proceed with this query (may timeout)
                            b) Revise the query to add LIMIT or more filters

                            If you didn't intend to scan this much data, please rephrase your request with specific limits.
                        """

                        logger.warning(
                            "Large result set detected",
                            flow_stage="large_result_warning",
                            flow_step_num=next(flow_step),
                            estimated_rows=estimated_rows,
                            estimated_size_gb=estimated_size_gb,
                        )

                        # Add warning to messages for LLM to see
                        messages.append(
                            {
                                "role": "system",
                                "content": warning_msg,
                            }
                        )

                        # Store performance warning in explanation and metadata
                        explanation["performance_warning"] = True
                        new_metadata.update({"explanation": explanation})

                        # Also store in metadata for backwards compatibility
                        new_metadata.update(
                            {
                                "estimated_rows": estimated_rows,
                                "estimated_size_gb": estimated_size_gb,
                                "performance_warning": True,
                            }
                        )
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
                error_pattern = r"(DB::Exception.*?)Stack trace"
                error_match = re.search(error_pattern, str(err), re.DOTALL)
                error_message = error_match.group(1) if error_match else str(err)
                retry_errors.append(
                    {
                        "attempt": attempt,
                        "type": "db_exception",
                        "error": error_message.strip()[:200],  # Truncate long errors
                    }
                )
                attempt += 1

                repair_prompt = f"""
                    We have got DB exception: {error_message}\n.
                    Please regenerate SQL to fix the issue.
                    Remember instructions from original prompt!.

                    IMPORTANT: Keep the 'result' field exactly as you
                    wrote it originally. The result should describe what
                    the query accomplishes for the user, NOT what you
                    fixed. Do NOT mention fixes or repairs in result.
                """

                messages.append(
                    {
                        "role": "system",
                        "content": repair_prompt,
                    }
                )

                # Trace repair attempt for db_exception
                if tracer:
                    await tracer.trace_repair(
                        repair_attempt=attempt - 1,
                        error_message=error_message.strip()[:500],
                        metadata={
                            "repair_type": "db_exception",
                            "repair_prompt": repair_prompt[:1000],
                        },
                    )
                continue

            # Smart row count: skip if query is too expensive based on EXPLAIN estimates
            row_count = None
            try:
                # Get estimates from EXPLAIN (already fetched above)
                estimated_rows = analyzed.get("estimated_rows")
                estimated_size_gb = analyzed.get("estimated_output_size_gb")

                # Define thresholds for skipping row count
                # These are higher than warning thresholds since row count is less critical
                skip_row_count_threshold_rows = 10_000_000_000  # 10B rows
                skip_row_count_threshold_size_gb = 100.0  # 100 GB

                # TODO: temp disabled row count !!!
                should_skip_count = True
                if estimated_rows and estimated_rows > skip_row_count_threshold_rows:
                    should_skip_count = True
                    logger.info(
                        "Skipping row count due to high estimated rows",
                        flow_stage="skip_row_count",
                        flow_step_num=next(flow_step),
                        estimated_rows=estimated_rows,
                    )
                elif (
                    estimated_size_gb
                    and estimated_size_gb > skip_row_count_threshold_size_gb
                ):
                    should_skip_count = True
                    logger.info(
                        "Skipping row count due to high estimated size",
                        flow_stage="skip_row_count",
                        flow_step_num=next(flow_step),
                        estimated_size_gb=estimated_size_gb,
                    )

                if not should_skip_count:
                    row_count = count_wh_request(extracted_sql, db_wh)
                    new_metadata.update({"row_count": row_count})
                    logger.info(
                        "Row count completed",
                        flow_stage="row_count",
                        flow_step_num=next(flow_step),
                        row_count=row_count,
                    )
                else:
                    # Set row_count to None when skipped, frontend can handle this gracefully
                    new_metadata.update({"row_count": None, "row_count_skipped": True})

                # Chart detection: build chart metadata from LLM suggestion + empirical validation
                from fm_app.utils.chart_detection import build_chart_metadata

                chart_metadata = build_chart_metadata(
                    columns=llm_response.columns or [],
                    row_count=row_count,
                    suggested_chart=new_metadata.get("chart_suggestion"),
                )
                new_metadata.update({"chart": chart_metadata.model_dump()})

                logger.info(
                    "Chart metadata generated",
                    flow_stage="chart_detection",
                    flow_step_num=next(flow_step),
                    suggested_chart=chart_metadata.suggested_chart,
                    available_charts=chart_metadata.available_charts,
                )

            except Exception as e:
                # Don't fail the entire flow if row count fails
                logger.warning(
                    "Error counting rows, continuing without row count",
                    flow_stage="count_rows_error",
                    flow_step_num=next(flow_step),
                    error=str(e),
                )
                new_metadata.update({"row_count": None})

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
                chart=chart_metadata if "chart_metadata" in locals() else None,
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

            # Link query to the plan that produced it (if plan_id provided)
            if plan_id is not None:
                try:
                    await update_query_plan_id(db, new_query_stored.query_id, plan_id)
                    logger.info(
                        "Linked query to plan",
                        flow_stage="link_query_to_plan",
                        flow_step_num=next(flow_step),
                        query_id=str(new_query_stored.query_id),
                        plan_id=str(plan_id),
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to link query to plan",
                        flow_stage="link_query_to_plan_error",
                        error=str(e),
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
            if tracer:
                await tracer.trace_error(
                    error_message="No SQL generated",
                    error_type="no_sql_output",
                )
                await tracer.finalize()
            return QueryResult(success=False)

        # Complete the flow
        logger.info(
            "Flow complete",
            flow_stage="end",
            flow_step_num=next(flow_step),
            flow=req.flow,
            metadata=new_metadata,
        )

        await update_request_status(RequestStatus.done, None, db, req.request_id)

        # Restore original result if we retried (prevents "fix" descriptions
        # from overwriting user-facing result)
        if original_result and attempt > 1:
            llm_response.result = original_result
            logger.info(
                "Restored original result after SQL repair",
                flow_stage="restore_result",
                flow_step_num=next(flow_step),
                original_result=original_result,
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

        # Finalize tracing on successful completion
        if tracer:
            await tracer.finalize()

        return QueryResult(success=True)

    # If we reach here, exhausted all attempts
    # Build detailed error message with all retry errors
    if retry_errors:
        errors_summary = "\n".join(
            f"Attempt {e['attempt']}: [{e['type']}] {e['error']}" for e in retry_errors
        )
        detailed_error = f"Failed after 3 attempts:\n{errors_summary}"
    else:
        detailed_error = "Failed to generate valid SQL after 3 attempts"

    await update_request_status(
        RequestStatus.error,
        detailed_error,
        db,
        req.request_id,
    )
    logger.info(
        "Failed to generate valid SQL after 3 attempts",
        flow_stage="failed_sql_generation",
        flow_step_num=next(flow_step),
        retry_errors=retry_errors,
    )

    # Trace error and finalize
    if tracer:
        await tracer.trace_error(
            error_message=detailed_error,
            error_type="max_retries_exceeded",
            metadata={"retry_errors": retry_errors},
        )
        await tracer.finalize()

    req.status = RequestStatus.error
    req.err = detailed_error

    # Signal that re-planning is needed - orchestrator will handle this
    # by generating a new plan with the error context and returning to user
    return QueryResult(success=False, needs_replan=True, errors=retry_errors)
