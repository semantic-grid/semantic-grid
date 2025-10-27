import itertools
import pathlib
import re
import uuid
from datetime import datetime
from typing import Type

import structlog
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel
from fm_app.api.model import (
    CreateQueryModel,
    CreateSessionModel,
    IntentAnalysis,
    InteractiveRequestType,
    McpServerRequest,
    QueryMetadata,
    RequestStatus,
    StructuredResponse,
    UpdateRequestModel,
    WorkerRequest,
)
from fm_app.config import get_settings
from fm_app.db.db import (
    add_new_session,
    count_wh_request,
    create_query,
    get_all_requests,
    get_history,
    get_session_by_id,
    update_query_metadata,
    update_request,
    update_request_status,
    update_session_name,
)
from fm_app.mcp_servers.db_meta import (
    db_meta_mcp_analyze_query,
)
from fm_app.mcp_servers.mcp_async_providers import (
    DbMetaAsyncProvider,
    DbRefAsyncProvider,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
from fm_app.stopwatch import stopwatch
from fm_app.utils import get_cached_warehouse_dialect
from fm_app.validators import MetadataValidator


async def interactive_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
):
    logger = structlog.wrap_logger(get_task_logger(__name__))
    flow_step = itertools.count(1)  # start from 1
    print(">>> FLOW START", stopwatch.lap())

    settings = get_settings()
    # Detect warehouse database dialect
    warehouse_dialect = get_cached_warehouse_dialect()
    structlog.contextvars.bind_contextvars(
        request_id=req.request_id, flow_name=ai_model.get_name() + "_interactive"
    )

    # Initialize for fm-app with client overlays
    # repo_root = pathlib.Path(settings.packs_resources_dir).resolve()  # adjust depth
    repo_root = pathlib.Path(settings.packs_resources_dir)  # adjust depth
    assembler = PromptAssembler(
        repo_root=repo_root,  # containing /prompts and /client-configs
        component="fm_app",
        client=settings.client_id,
        env=settings.env,
        system_version=settings.system_version,  # pick latest
    )

    # Register async MCP providers for db-meta and db-ref
    assembler.register_async_mcp(DbMetaAsyncProvider(settings, logger))
    assembler.register_async_mcp(DbRefAsyncProvider(settings, logger))

    # Intent distillation step
    request_session = await get_session_by_id(session_id=req.session_id, db=db)
    parent_session = (
        await get_session_by_id(session_id=req.parent_session_id, db=db)
        if req.parent_session_id
        else None
    )

    await update_request_status(RequestStatus.in_process, None, db, req.request_id)

    query_metadata_instruction = (
        f"Current QueryMetadata: {req.query.model_dump_json()}"
        if req.query is not None
        else (
            f"Current QueryMetadata: {request_session.metadata}"
            if request_session.metadata is not None
            else f"QueryMetadata ID (new): {uuid.uuid4()}"
        )
    )

    parent_instruction = (
        f"Parent session UUID: {request_session.parent}"
        if request_session.parent is not None
        else ""
    )

    parent_metadata_instruction = (
        f"Parent QueryMetadata: {parent_session.metadata}"
        if parent_session is not None
        else ""
    )

    column_instruction = (
        (
            ""
            if req.refs is None or req.refs.cols is None
            else f"Selected Column Data [id, ...data values]: {req.refs.cols}"
        )
        if req.refs is not None and req.refs.cols is not None
        else ""
    )

    rows_instruction = (
        f"Selected Row Data [[...headers], ...[...values]]: {req.refs.rows}"
        if req.refs is not None and req.refs.rows is not None
        else ""
    )

    intent_hint = f"Intent Hint: {req.request_type}"

    # print("column_instruction", column_instruction)
    # print("rows_instruction", rows_instruction)
    # print("parent_metadata_instruction", parent_metadata_instruction)
    # print("intent_hint", intent_hint)

    # Variables you inject at runtime

    if req.request_type == InteractiveRequestType.manual_query:
        ### MANUAL QUERY ###
        manual_query_vars = {
            "client_id": settings.client_id,
            "request": req.request,
            "current_datetime": datetime.now().replace(microsecond=0),
        }
        await update_request_status(RequestStatus.new, None, db, req.request_id)

        # Capabilities coming from MCPs (db-meta/db-ref)
        # db_meta_caps = {
        # "sql_dialect": "clickhouse",
        # "cost_tier": "standard",
        # "max_result_rows": 5000,
        # }
        mcp_ctx = {
            "req": McpServerRequest(
                request_id=req.request_id,
                db=req.db,
                request=req.request,
                session_id=req.session_id,
                model=req.model,
                flow=req.flow,
            ),
            "flow_step_num": next(flow_step),  # for logging purposes
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

        print(">>> PRE MANUAL QUERY", stopwatch.lap())
        await update_request_status(RequestStatus.sql, None, db, req.request_id)

        try:
            llm_response = ai_model.get_structured(
                messages, QueryMetadata, "gpt-4.1-mini-2025-04-14"
                # "gpt-4.1-2025-04-14"
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
            await update_request_status(RequestStatus.error, req.err, db,
                                        req.request_id)
            return req

        print(">>> POST MANUAL QUERY", stopwatch.lap())
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

        # copy dict from request_session.metadata
        new_metadata = llm_response.model_dump()

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
                req.err = analyzed.get("error")
                return req

            # if we have a valid SQL, get the row count

            print(">>> PRE ROW COUNT", stopwatch.lap())

            try:
                row_count = count_wh_request(extracted_sql, db_wh)
                new_metadata.update({"row_count": row_count})

                print(">>> POST ROW COUNT", stopwatch.lap())

                await update_query_metadata(
                    session_id=req.session_id,
                    user_owner=req.user,
                    metadata=new_metadata,
                    db=db,
                )

                requests_for_session = await get_all_requests(
                    session_id=req.session_id, db=db, user_owner=req.user
                )
                # cycle through requests to latest request with query_id set
                parent_id = None
                for request in requests_for_session:
                    if request.query is not None:
                        parent_id = (
                            request.query.query_id
                            if request.query.query_id
                            else None
                        )
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
                    parent_id=(
                        req.query.query_id if req.query is not None else parent_id
                    ),  # Link to the previous query if exists
                )
                # Create a new query in the database
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

                print(">>> DONE MANUAL QUERY", stopwatch.lap())

                return req

            # unable to count rows, log the error and keep going
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

                req.err = str(e)
                return req

    elif req.request_type == InteractiveRequestType.linked_query:
        ### LINKED SESSION ###
        linked_query_vars = {
            "client_id": settings.client_id,
            "intent_hint": intent_hint,
            "query_metadata": query_metadata_instruction,
            "current_datetime": datetime.now().replace(microsecond=0),
        }
        await update_request_status(RequestStatus.new, None, db, req.request_id)

        # Capabilities coming from MCPs (db-meta/db-ref)
        # db_meta_caps = {
            # "sql_dialect": "clickhouse",
            # "cost_tier": "standard",
            # "max_result_rows": 5000,
        # }
        mcp_ctx = {
            "req": McpServerRequest(
                request_id=req.request_id,
                db=req.db,
                request=req.request,
                session_id=req.session_id,
                model=req.model,
                flow=req.flow,
            ),
            "flow_step_num": next(flow_step),  # for logging purposes
        }

        slot = await assembler.render_async(
            "linked_query", variables=linked_query_vars, req_ctx=mcp_ctx, mcp_caps=None
        )

        linked_query_llm_system_prompt = slot.prompt_text

        if ai_model.get_name() != "gemini":
            messages = [{"role": "system", "content": linked_query_llm_system_prompt}]
            messages.append({"role": "user", "content": req.request})

        else:
            messages = f"""
                 {linked_query_llm_system_prompt}\n
                 User input: {req.request}\n"""

        logger.info(
            "Prepared linked_query request",
            flow_stage="linked_query",
            flow_step_num=next(flow_step),
            ai_request=messages,
        )

        print(">>> PRE LINKED QUERY", stopwatch.lap())
        await update_request_status(RequestStatus.intent, None, db, req.request_id)

        try:
            llm_response = ai_model.get_structured(
                messages, IntentAnalysis, "gpt-4.1-mini-2025-04-14" # "gpt-4.1-2025-04-14"
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
            await update_request_status(RequestStatus.error, req.err, db,
                                        req.request_id)
            return req

        print(">>> POST LINKED QUERY", stopwatch.lap())
        await update_request_status(RequestStatus.finalizing, None, db, req.request_id)

        if ai_model.get_name() != "gemini":
            messages.append({"role": "assistant", "content": llm_response})
        else:
            messages = f"""
                     {messages}\n
                     AI response: {llm_response}\n"""

        # copy dict from request_session.metadata
        new_metadata_dict = {
            "id": str(uuid.uuid4()),
            "summary":  llm_response.intent,
            "description": llm_response.intent,
            "sql": req.query.sql,
            # for columns, we need to convert list[Column] to list[dict]
            "columns": [c.model_dump() for c in req.query.columns] ,
            "row_count": req.query.row_count,
        }

        # complete the flow
        logger.info(
            "Flow complete",
            flow_stage="end",
            flow_step_num=next(flow_step),
            flow=req.flow,
            intent=llm_response.intent,
        )
        await update_query_metadata(
            session_id=req.session_id,
            user_owner=req.user,
            metadata=new_metadata_dict,
            db=db,
        )
        await update_request_status(RequestStatus.done, None, db, req.request_id)
        req.response = llm_response.intent
        req.structured_response = StructuredResponse(
            intent=llm_response.intent,
            description=llm_response.intent,
            intro=None,
            sql=req.query.sql,
            metadata=QueryMetadata(**new_metadata_dict),
            refs=None,
        )

        print(">>> DONE LINKED QUERY", stopwatch.lap())

        return req


    else:
        ### QUERY PLANNER / INTENT ###

        planner_vars = {
            "client_id": settings.client_id,
            "intent_hint": intent_hint,
            "query_metadata": query_metadata_instruction,
            "parent_query_metadata": parent_metadata_instruction,
            "parent_session_id": parent_instruction,
            "selected_row_data": rows_instruction,
            "selected_column_data": column_instruction,
            "current_datetime": datetime.now().replace(microsecond=0),
        }

        # Capabilities coming from MCPs (db-meta/db-ref)
        db_meta_caps = {
            # "sql_dialect": "clickhouse",
            # "cost_tier": "standard",
            # "max_result_rows": 5000,
        }
        mcp_ctx = {
            "req": McpServerRequest(
                request_id=req.request_id,
                db=req.db,
                request=req.request,
                session_id=req.session_id,
                model=req.model,
                flow=req.flow,
            ),
            "flow_step_num": next(flow_step),  # for logging purposes
        }

        slot = await assembler.render_async(
            "planner", variables=planner_vars, req_ctx=mcp_ctx, mcp_caps=db_meta_caps
        )

        intent_llm_system_prompt = slot.prompt_text

        history = await get_history(db, req.session_id, include_responses=False)
        if ai_model.get_name() != "gemini":
            messages = [{"role": "system", "content": intent_llm_system_prompt}]
            for item in history:
                if item.get("content") is not None:
                    messages.append(item)
            messages.append({"role": "user", "content": req.request})

        else:
            messages = f"""
                 {intent_llm_system_prompt}\n
                 User input: {req.request}\n"""

        logger.info(
            "Prepared intent request",
            flow_stage="intent",
            flow_step_num=next(flow_step),
            ai_request=messages,
        )

        user_intent = None
        print(">>> PRE INTENT", stopwatch.lap())

        try:
            llm_response = ai_model.get_structured(
                messages, IntentAnalysis, "gpt-4.1-2025-04-14"
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
            return req

        print(">>> POST INTENT", stopwatch.lap())

        if ai_model.get_name() != "gemini":
            messages.append({"role": "assistant", "content": llm_response})
        else:
            messages = f"""
             {messages}\n
             AI response: {llm_response}\n"""

        logger.info(
            "Got intent",
            flow_stage="llm_intent",
            flow_step_num=next(flow_step),
            ai_response=llm_response,
        )
        await update_request_status(RequestStatus.intent, None, db, req.request_id)
        if llm_response.intent:
            user_intent = llm_response.intent
            await update_request(
                update=UpdateRequestModel(
                    request_id=req.request_id, intent=llm_response.intent
                ),
                db=db,
            )

        user_intent_instruction = (
            f"User intent: {llm_response.intent}" if llm_response.intent is not None else ""
        )

    ### LINKED SESSION QUERY ###
    if (
        llm_response.request_type == InteractiveRequestType.linked_session
        or req.request_type == InteractiveRequestType.linked_session
    ):

        await update_request_status(RequestStatus.finalizing, None, db, req.request_id)

        # create new session
        linked_session = CreateSessionModel(
            name="New linked session",
            tags="",
            parent=req.session_id,
            refs=req.refs,
        )
        session_response = await add_new_session(
            session=linked_session, user_owner=req.user, db=db
        )

        await update_request_status(RequestStatus.done, None, db, req.request_id)
        req.structured_response = StructuredResponse(
            intent=llm_response.intent,
            intro=llm_response.response,
            sql=request_session.metadata.get("sql"),
            metadata=request_session.metadata,
            refs=req.refs,
            linked_session_id=session_response.session_id,
        )
        req.status = RequestStatus.done
        req.response = llm_response.response
        return req

    ### INTERACTIVE QUERY ###
    elif llm_response.request_type == InteractiveRequestType.interactive_query:

        history = await get_history(db, req.session_id, include_responses=False)

        interactive_query_vars = {
            "client_id": settings.client_id,
            "intent_hint": intent_hint,
            "query_metadata": query_metadata_instruction,
            "parent_query_metadata": parent_metadata_instruction,
            "parent_session_id": parent_instruction,
            "selected_row_data": rows_instruction,
            "selected_column_data": column_instruction,
            "current_datetime": datetime.now().replace(microsecond=0),
        }

        # Capabilities coming from MCPs (db-meta/db-ref)
        db_meta_caps = {
            # "sql_dialect": "clickhouse",
            # "cost_tier": "standard",
            # "max_result_rows": 5000,
        }
        mcp_ctx = {
            "req": McpServerRequest(
                request_id=req.request_id,
                session_id=req.session_id,
                db=req.db,
                request=req.request,
                model=req.model,
                flow=req.flow,
            ),
            "flow_step_num": next(flow_step),  # for logging purposes
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

        ### do at most 3 attempts to generate valid SQL for the request
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
                return req

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
                # This will help the LLM fix column_name issues before SQL execution
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
            await update_session_name(
                req.session_id, req.user, llm_response.summary, db
            )

            if (request_session.parent is not None) and (
                request_session.parent not in llm_response.parents
            ):
                llm_response.parents.append(request_session.parent)

            new_metadata = llm_response.model_dump()

            await update_request_status(
                RequestStatus.finalizing, None, db, req.request_id
            )
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
                    # instead of returning we increment the attempt counter and keep going
                    attempt += 1
                    error_pattern = r"(DB::Exception.*?)Stack trace"
                    error_match = re.search(error_pattern, str(err), re.DOTALL)
                    error_message = error_match.group(1)
                    # error_type = type(err)
                    # error_args = err.args

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

                    # req.status = RequestStatus.error
                    # req.err = analyzed.get("error")
                    # return req

                # if we have a valid SQL, get the row count

                print(">>> PRE ROW COUNT", stopwatch.lap())

                try:
                    row_count = count_wh_request(extracted_sql, db_wh)
                    new_metadata.update({"row_count": row_count})

                    print(">>> POST ROW COUNT", stopwatch.lap())

                    await update_query_metadata(
                        session_id=req.session_id,
                        user_owner=req.user,
                        metadata=new_metadata,
                        db=db,
                    )

                    requests_for_session = await get_all_requests(
                        session_id=req.session_id, db=db, user_owner=req.user
                    )
                    # cycle through requests to latest request with query_id set
                    parent_id = None
                    for request in requests_for_session:
                        if request.query is not None:
                            parent_id = (
                                request.query.query_id
                                if request.query.query_id
                                else None
                            )
                            break
                    new_query = CreateQueryModel(
                        request=req.request,
                        intent=user_intent,
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
                        parent_id=(
                            req.query.query_id if req.query is not None else parent_id
                        ),  # Link to the previous query if exists
                    )
                    # Create a new query in the database
                    new_query_stored = await create_query(db=db, init=new_query)
                    await update_request(
                        db=db,
                        update=UpdateRequestModel(
                            request_id=req.request_id,
                            query_id=new_query_stored.query_id,
                        ),
                    )

                # unable to count rows, log the error and keep going
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
                    # req.status = RequestStatus.error
                    # req.err = str(e)
                    # return req

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
                return req

            # complete the flow
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


            return req

        # if we reach here, it means we exhausted all attempts to generate valid SQL
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
        return req

    ### DATA ANALYSIS ###
    elif llm_response.request_type == InteractiveRequestType.data_analysis:

        data_analysis_vars = {
            "client_id": settings.client_id,
            "intent_hint": intent_hint,
            "query_metadata": query_metadata_instruction,
            "parent_query_metadata": parent_metadata_instruction,
            "parent_session_id": parent_instruction,
            "selected_row_data": rows_instruction,
            "selected_column_data": column_instruction,
            "current_datetime": datetime.now().replace(microsecond=0),
        }

        # Capabilities coming from MCPs (db-meta/db-ref)
        db_meta_caps = {
            # "sql_dialect": "clickhouse",
            # "cost_tier": "standard",
            # "max_result_rows": 5000,
        }
        mcp_ctx = {
            "req": McpServerRequest(
                request_id=req.request_id,
                session_id=req.session_id,
                db=req.db,
                request=req.request,
                model=req.model,
                flow=req.flow,
            ),
            "flow_step_num": next(flow_step),  # for logging purposes
        }

        slot = await assembler.render_async(
            "data_analysis",
            variables=data_analysis_vars,
            req_ctx=mcp_ctx,
            mcp_caps=db_meta_caps,
        )

        analysis_llm_system_prompt = slot.prompt_text

        history = await get_history(db, req.session_id, include_responses=False)
        if ai_model.get_name() != "gemini":
            messages = [{"role": "system", "content": analysis_llm_system_prompt}]
            for item in history:
                if item.get("content") is not None:
                    messages.append(item)
            messages.append({"role": "user", "content": req.request})

        else:
            messages = f"""
                     {analysis_llm_system_prompt}\n
                     User input: {req.request}\n"""

        await update_request_status(RequestStatus.finalizing, None, db, req.request_id)
        logger.info(
            "Prepared analysis request",
            flow_stage="analysis",
            flow_step_num=next(flow_step),
            ai_request=messages,
        )

        try:
            llm_response = ai_model.get_response(messages)

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
            return req

        if ai_model.get_name() != "gemini":
            messages.append({"role": "assistant", "content": llm_response})
        else:
            messages = f"""
                 {messages}\n
                 AI response: {llm_response}\n"""

        logger.info(
            "Response to user",
            flow_stage="data_analysis",
            flow_step_num=next(flow_step),
            ai_response=llm_response,
        )
        await update_request_status(RequestStatus.done, None, db, req.request_id)
        req.response = llm_response
        req.structured_response = StructuredResponse(
            intro=llm_response,
            metadata=request_session.metadata,
            refs=req.refs,
        )
        return req

    ### GENERAL CHAT OR DISAMBIGUATION ###
    elif (
        llm_response.request_type == InteractiveRequestType.general_chat
        or llm_response.request_type == InteractiveRequestType.disambiguation
    ):
        logger.info(
            "Response to user",
            flow_stage="general_question or disambiguation",
            flow_step_num=next(flow_step),
            ai_response=llm_response,
        )
        await update_request_status(RequestStatus.done, None, db, req.request_id)
        req.response = llm_response.response
        req.structured_response = StructuredResponse(
            intent=llm_response.request_type,
            intro=llm_response.response,
            description=None,
            metadata=request_session.metadata,
            refs=req.refs,
        )
        return req

    ### UNSUPPORTED REQUEST TYPE ###
    else:
        logger.info(
            "Unsupported request type",
            flow_stage="unsupported_request_type",
            flow_step_num=next(flow_step),
            ai_response=llm_response,
        )
        await update_request_status(RequestStatus.done, None, db, req.request_id)
        req.response = "Unsupported request type"
        req.structured_response = StructuredResponse(
            intent=llm_response.request_type,
            intro="Unsupported request type",
            metadata=request_session.metadata,
            refs=req.refs,
        )
        return req
