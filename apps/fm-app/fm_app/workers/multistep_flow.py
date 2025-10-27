import itertools
import json
import pathlib
import re
from datetime import datetime
from typing import Type

import sqlglot
import structlog
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel, InvestigationStep
from fm_app.api.model import (
    McpServerRequest,
    RequestStatus,
    StructuredResponse,
    WorkerRequest,
)
from fm_app.config import get_settings
from fm_app.db.db import (
    get_history,
    run_structured_wh_request,
    update_request_status,
    update_session_name,
)
from fm_app.mcp_servers.mcp_async_providers import (
    DbMetaAsyncProvider,
    DbRefAsyncProvider,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
from fm_app.services.charts import generate_chart_code, generate_chart_html
from fm_app.utils import get_cached_warehouse_dialect

#    intent_slots_suffix, intent_slots_prefix, verify_request_suffix,


async def multistep_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
):
    logger = structlog.wrap_logger(get_task_logger(__name__))
    settings = get_settings()
    warehouse_dialect = get_cached_warehouse_dialect()
    structlog.contextvars.bind_contextvars(
        request_id=str(req.request_id), flow_name=ai_model.get_name() + "_multistep"
    )
    flow_step = itertools.count(1)  # start from 1

    # Initialize for fm-app with client overlays
    # repo_root = pathlib.Path(__file__).resolve()  # adjust depth
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

    req.structured_response = StructuredResponse()

    logger.info(
        "Starting flow",
        flow_stage="start",
        flow_step_num=next(flow_step),
        flow=req.flow,
    )
    await update_request_status(RequestStatus.intent, None, db, req.request_id)

    intent_vars = {
        "client_id": settings.client_id,
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
        "multistep_intent",
        variables=intent_vars,
        req_ctx=mcp_ctx,
        mcp_caps=db_meta_caps,
    )

    ai_request = slot.prompt_text

    history = await get_history(db, req.session_id, include_responses=True)
    messages = [{"role": "system", "content": ai_request}]
    for item in history:
        messages.append(item)
    messages.append({"role": "user", "content": req.request})

    logger.info(
        "Request AI step *intent*",
        flow_stage="ai_request_intent",
        request=messages,
        flow_step_num=next(flow_step),
    )
    ai_response = ai_model.get_structured(messages, InvestigationStep)
    await update_session_name(req.session_id, req.user, ai_response.summary, db)
    req.structured_response.intent = ai_response.user_intent

    # CONFUSED OT NEED ADDITIONAL DATA
    if (
        ai_response.additional_data_request is not None
        and ai_response.additional_data_request not in ["N/A", "None", "", None]
    ):
        logger.info(
            "Additional info needed",
            flow_stage="additional_info_needed",
            flow_step_num=next(flow_step),
            ai_response=ai_response,
        )
        # TODO: temporarily switched off because it's too unstable
        # req.response = ai_response.additional_data_request
        # return req

    request_vars = {
        "client_id": settings.client_id,
        "current_datetime": datetime.now().replace(microsecond=0),
    }

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
        "multistep_request",
        variables=request_vars,
        req_ctx=mcp_ctx,
        mcp_caps=db_meta_caps,
    )

    ai_request = slot.prompt_text

    messages.append({"role": "system", "content": ai_request})
    messages.append(
        {
            "role": "user",
            "content": (
                ai_response.user_intent if ai_response.user_intent else req.request
            ),
        }
    )
    # history = get_history(db, req.session_id, include_responses=True)
    # for item in history:
    #    messages.append(item)
    # TODO: separate into a separate flow

    req.response = """
        Unfortunately I can't answer to your question. 
        Please reformulate it and try one more time.
    """
    await update_request_status(RequestStatus.sql, None, db, req.request_id)
    chart_requested = (
        req.request.find("chart") > -1
        or req.request.find("graph") > -1
        or req.request.find("diagram") > -1
    )

    for step in range(settings.max_steps):
        logger.info(
            f"Request AI step {step}",
            flow_stage=f"ai_request_{step}",
            request=messages,
            flow_step_num=next(flow_step),
        )
        ai_response = ai_model.get_structured(messages, InvestigationStep)
        # only put assumptions if they are not empty; don't overwrite
        if ai_response.user_friendly_assumptions:
            req.structured_response.assumptions = ai_response.user_friendly_assumptions

        logger.info(
            f"AI response step {step}",
            flow_stage=f"ai_response_{step}",
            ai_response=ai_response,
            flow_step_num=next(flow_step),
        )
        result = ai_response
        # if ai_model.get_name() == "open-ai":
        messages.append(
            {"role": "assistant", "content": json.dumps(result.model_dump())}
        )
        # elif ai_model.get_name() == "deep-seek":
        #    messages.append({'role': 'assistant', 'content': result.model_dump_json()})
        # elif ai_model.get_name() == "gemini":
        #    messages.append({'role': 'assistant', 'content': result.model_dump_json()})

        # READY TO RESPOND TO USER
        if result.response_to_user or (
            result.intro or result.outro or result.rows or result.labels
        ):
            if not result.response_to_user:
                result.response_to_user = f"""{result.intro}\n\n{result.outro}"""

            logger.info(
                "Got final answer",
                flow_stage="final_answer",
                flow_step_num=next(flow_step),
                ai_response=result,
            )
            req.structured_response.assumptions = result.user_friendly_assumptions
            req.structured_response.intro = result.intro
            req.structured_response.outro = result.outro
            req.structured_response.raw_data_rows = result.rows
            req.structured_response.raw_data_labels = result.labels

            # check if we got python code in the response (for chart generation)
            pattern = r"```python\n(.*?)```"
            code_match = re.search(pattern, result.response_to_user, re.DOTALL)
            if code_match:
                code = code_match.group(1).strip()

                chart_url = generate_chart_code(code, next(flow_step), logger)
                if chart_url:
                    result.response_to_user = f"""
                        {result.response_to_user}\n\n
                        ![Generated chart]({chart_url})
                    """
                    req.response = result.response_to_user.replace(
                        code_match.group(0), ""
                    )
                    req.structured_response.chart = code
                    req.structured_response.chart_url = chart_url
                    return req

                else:
                    req.response = result.response_to_user.replace(
                        code_match.group(0), "***No chart generated***"
                    )
                    return req

            elif chart_requested and result.labels and result.rows:
                chart_type = "Bar"
                if req.request.find("pie") > -1:
                    chart_type = "Pie"

                logger.info(
                    "Chart requested",
                    flow_stage="chart_url",
                    flow_step_num=next(flow_step),
                    ai_response=result,
                )
                chart_url = generate_chart_html(
                    result.rows, result.labels, chart_type, next(flow_step), logger
                )
                if chart_url:
                    req.response = f"""
                        {result.response_to_user}\n\n
                        <div>
                          <iframe frameborder=\"0\" src=\"{chart_url}\" width=\"100%\">
                          </iframe>
                        </div>
                    """
                    req.structured_response.chart_url = chart_url
                    return req

                else:
                    req.response = result.response_to_user.replace(
                        code_match.group(0), "***No chart generated***"
                    )
                    return req

            # regular response
            req.response = result.response_to_user
            return req

        # HAVE SQL AND READY TO EXECUTE
        if result.sql_request:
            req.structured_response.sql = result.sql_request
            logger.info(
                "Extracted SQL",
                flow_stage="extracted_sql",
                flow_step_num=next(flow_step),
                extracted_sql=result.sql_request,
            )

            try:
                sqlglot.parse(result.sql_request, dialect=warehouse_dialect)
            except sqlglot.errors.ParseError as e:
                logger.error(
                    "SQL syntax error",
                    flow_stage="extracted_sql",
                    flow_step_num=next(flow_step),
                    extracted_sql=result.sql_request,
                    error=str(e),
                )
                messages.append(
                    {
                        "role": "system",
                        "content": f"""We have SQL syntax error: {str(e)}\n. 
                                Please regenerate SQL to fix the issue. 
                                This is unacceptable!""",
                    }
                )
                await update_request_status(
                    RequestStatus.retry, None, db, req.request_id
                )
                continue

            # if not result.self_check_passed:
            #     logger.info(
            #         "Performing Self-check",
            #         flow_stage='self_check_failed',
            #         flow_step_num=next(flow_step), ai_response=result
            #     )
            #     messages.append({
            #         'role': 'system',
            #         'content': f"""
            #             Please check that the following SQL: {result.sql_request}
            #             is syntactically correct
            #             and answers user's request ({result.user_intent}).\n
            #             {verify_request_suffix}
            #         """
            #     })
            #     update_request_status(RequestStatus.retry, None, db, req.request_id)
            #     continue

            try:
                wh_result = run_structured_wh_request(result.sql_request, db_wh)

            except Exception as e:
                error_pattern = r"(DB::Exception.*?)Stack trace"
                error_match = re.search(error_pattern, str(e), re.DOTALL)
                error_message = error_match.group(1)
                error_type = type(e)
                error_args = e.args
                logger.error(
                    "SQL error",
                    flow_stage="sql_error",
                    error_message=error_message,
                    flow_step_num=next(flow_step),
                    error_type=error_type,
                    error_args=error_args,
                )
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
                await update_request_status(
                    RequestStatus.retry, None, db, req.request_id
                )
                continue

            await update_request_status(
                RequestStatus.finalizing, None, db, req.request_id
            )
            if wh_result is None or wh_result.get("rows") == 0:
                req.response = (
                    "Unfortunately there is no data for your request at this time"
                )
                req.structured_response.intro = req.response
                req.structured_response.sql = result.sql_request
                return req

            elif wh_result.get("csv"):
                req.structured_response.csv = wh_result.get("csv")
                new_req = req.model_copy(
                    update={"request": wh_result.get("csv").replace(",", " ")}
                )

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
                if chart_requested:
                    chart_vars = {
                        "client_id": settings.client_id,
                        "chart_data": f"```csv \n {wh_result.get("csv")} \n```",
                        "current_datetime": datetime.now().replace(microsecond=0),
                    }

                    slot = await assembler.render_async(
                        "multistep_chart",
                        variables=chart_vars,
                        req_ctx=mcp_ctx,
                        mcp_caps=db_meta_caps,
                    )

                    ai_request = slot.prompt_text

                    # ai_request = f"""
                    #    Given the following data, generate the python code
                    #    to draw chart using ***plotly*** package:\n\n
                    #    ```csv \n {wh_result.get('csv')} \n```.\n
                    #    {chart_code_request_suffix}
                    # """

                else:

                    if wh_result.get("rows") > 0:
                        response_vars = {
                            "client_id": settings.client_id,
                            "response_data": f"```csv \n {wh_result.get("csv")} \n```",
                            "current_datetime": datetime.now().replace(microsecond=0),
                        }

                        slot = await assembler.render_async(
                            "multistep_response",
                            variables=response_vars,
                            req_ctx=mcp_ctx,
                            mcp_caps=db_meta_caps,
                        )

                        ai_request = slot.prompt_text
                    else:
                        response_vars = {
                            "client_id": settings.client_id,
                            "response_data": f"```csv \n {wh_result.get("csv")} \n```",
                            "current_datetime": datetime.now().replace(microsecond=0),
                        }

                        slot = await assembler.render_async(
                            "multistep_response_plain",
                            variables=response_vars,
                            req_ctx=mcp_ctx,
                            mcp_caps=db_meta_caps,
                        )

                        ai_request = slot.prompt_text

            if ai_model.get_name() == "anthropic":
                # Anthropic has 8k tokens limit
                filtered_messages = [{"role": "system", "content": ai_request}]
                for item in messages:
                    if item["role"] != "system":
                        filtered_messages.append(item)
                messages = filtered_messages
            else:
                messages.append({"role": "system", "content": ai_request})
            req.structured_response.sql = result.sql_request
            continue

        # CONFUSED OT NEED ADDITIONAL DATA
        # TODO: for some reason Gemini returns "N/A" instead of None -- investigate !!!
        if (
            result.additional_data_request is not None
            and result.additional_data_request not in ["N/A", "None", "", None]
        ):
            logger.info(
                "Additional info needed",
                flow_stage="additional_info_needed",
                flow_step_num=next(flow_step),
                ai_response=result,
            )
            # TODO: temporarily switched off because it's too unstable
            # req.response = result.additional_data_request
            # return req
            result.additional_data_request = None
            continue

    return req
