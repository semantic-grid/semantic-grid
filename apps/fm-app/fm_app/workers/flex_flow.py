import csv
import io
import itertools
import json
import pathlib
import re
from datetime import datetime
from typing import Optional, Type

import duckdb
import pandas as pd
import sqlglot
import structlog
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel
from fm_app.api.model import (
    McpServerRequest,
    RequestStatus,
    StructuredResponse,
    WorkerRequest,
)
from fm_app.config import get_settings
from fm_app.db.db import (
    run_structured_wh_request_dataframe,
    run_structured_wh_request_native,
    update_request_status,
)
from fm_app.mcp_servers.db_meta import (
    db_meta_mcp_analyze_query,
)
from fm_app.mcp_servers.mcp_async_providers import (
    DbMetaAsyncProvider,
    DbRefAsyncProvider,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
from fm_app.utils import get_cached_warehouse_dialect


async def flex_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
):
    logger = structlog.wrap_logger(get_task_logger(__name__))
    flow_step = itertools.count(1)  # start from 1

    settings = get_settings()
    warehouse_dialect = get_cached_warehouse_dialect()
    structlog.contextvars.bind_contextvars(
        request_id=req.request_id, flow_name=ai_model.get_name() + "_flex"
    )

    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()  # adjust depth
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

    logger.info(
        "Starting flow",
        flow_stage="start",
        flow_step_num=next(flow_step),
        flow=req.flow,
    )
    req.structured_response = StructuredResponse()

    planner_vars = {
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
        "flow_step_num": next(flow_step),
    }

    slot = await assembler.render_async(
        "legacy_flex_flow",
        variables=planner_vars,
        req_ctx=mcp_ctx,
        mcp_caps=db_meta_caps,
    )

    ai_request = slot.prompt_text

    messages = None
    if ai_model.get_name() != "gemini":
        messages = [
            {"role": "system", "content": ai_request},
            {"role": "user", "content": req.request},
        ]
    else:
        messages = f"""
        {ai_request}\n
        User input: {req.request}\n"""

    await update_request_status(RequestStatus.sql, None, db, req.request_id)
    logger.info(
        "Prepared ai_request",
        flow_stage="ask_for_sql",
        flow_step_num=next(flow_step),
        ai_request=messages,
    )
    sql_request = ai_model.get_response(messages)
    if ai_model.get_name() != "gemini":
        messages.append({"role": "assistant", "content": sql_request})
    else:
        messages = f"""
        {messages}\n
        AI response: {sql_request}\n"""
    # logprobs = [token.logprob for token in ai_response.choices[0].logprobs.content]
    # mean_logprob = sum(logprobs) / len(logprobs)
    # perplexity_score = np.exp(-mean_logprob)

    logger.info(
        "Got response",
        flow_stage="resp_sql",
        flow_step_num=next(flow_step),
        ai_response=sql_request,
    )
    # logger.info(
    #   "Perplexity",
    #   flow_stage='resp_sql', flow_step_num=next(flow_step), perplexity=perplexity_score
    # )

    pattern = r"```sql\n(.*?)```"
    sql_request = sql_request or ""
    sql_match = re.search(pattern, sql_request, re.DOTALL)
    wh_result = {}

    if sql_match:
        extracted_sql = sql_match.group(1).strip()

        ## TODO: refactor to use via prompt assembler
        analyzed = await db_meta_mcp_analyze_query(
            req, extracted_sql, next(flow_step), settings, logger
        )
        MAX_ROWS_SAFE = 50_000_000
        MAX_PARTS_SAFE = 3
        MAX_MARKS_SAFE = 100_000
        if analyzed.get("explanation"):
            analysis = analyzed.get("explanation")[0]
            parts = analysis.get("parts")
            rows = analysis.get("rows")
            marks = analysis.get("marks")
            if rows > MAX_ROWS_SAFE or marks > MAX_MARKS_SAFE or parts > MAX_PARTS_SAFE:
                # ask for breakdown of the query
                slot_vars = {
                    "client_id": settings.client_id,
                }

                slot = await assembler.render_async(
                    "legacy_sql_planner",
                    variables=slot_vars,
                    req_ctx={},
                    mcp_caps=None,
                )

                prompt = slot.prompt_text
                messages = [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": extracted_sql},
                ]
                pipeline_str = ai_model.get_response(messages)
                pipeline = json.loads(pipeline_str)
                con = duckdb.connect()
                df = None
                # db_result = None

                step_outputs = {}
                # cycle through the pipeline
                for step in pipeline:
                    step_sql = step.get("sql")
                    if not step_sql:
                        continue

                    try:
                        stage = step.get("stage")
                        if step.get("db") == "duckdb":
                            result = con.execute(step_sql)

                            if stage == "final":
                                step_outputs[stage] = result.fetchdf()

                        else:
                            rows, columns = run_structured_wh_request_dataframe(
                                step_sql, db_wh
                            )
                            df = pd.DataFrame(rows, columns=[col[0] for col in columns])
                            df_name = step.get("output_table", "df")

                            # con.register(df_name, df)
                            con.execute(
                                f"CREATE OR REPLACE TABLE {df_name} AS SELECT * FROM df"
                            )
                            step_outputs[stage] = df

                    except Exception as e:
                        logger.error(
                            "Error running SQL pipeline",
                            flow_stage="error_sql",
                            flow_step_num=next(flow_step),
                            error=str(e),
                        )
                        req.status = RequestStatus.error
                        req.err = str(e)
                        return req

                # get the final result
                final_result: Optional[pd.DataFrame] = step_outputs.get("final", None)
                if final_result is None or final_result.empty:
                    req.response = "No data was returned from the query pipeline."
                    req.status = RequestStatus.done
                    return req

                df_result = final_result.to_dict("records")
                csv_buffer = io.StringIO()
                final_result.to_csv(csv_buffer, index=False)
                csv_string = csv_buffer.getvalue()
                csv_buffer.close()

                ai_request = f"""
                                Here is the data you requested on previous step 
                                in CSV format ```csv \n
                                {csv_string} \n```\n
                            """
                ai_request = (
                    ai_request
                    + """
                            Please generate final response to original user input.\n 
                            If there is no data needed please prepare polite response 
                            that we have not necessary data.\n
                        """
                )
                req.structured_response.csv = csv_string
                csv_file = io.StringIO(req.structured_response.csv)
                reader = csv.reader(csv_file)
                csv_data = list(reader)
                csv_headers = csv_data[0] if len(csv_data) > 0 else []
                csv_rows = csv_data[1:][0] if len(csv_data) > 1 else []
                if len(csv_headers) > 1 or len(csv_rows) > 1:
                    ai_request = (
                        ai_request
                        + """Instead of formatting the supplied csv data, 
                                    insert CSV-formatted data (```csv ...```) 
                                    in the relevant part of your response.\n """
                    )
                if ai_model.get_name() != "gemini":
                    messages.append({"role": "system", "content": ai_request})
                else:
                    messages = f"""
                    {messages}\n
                    {ai_request}\n"""

                await update_request_status(
                    RequestStatus.finalizing, None, db, req.request_id
                )
                logger.info(
                    "Prepared ai_request",
                    flow_stage="ask_for_final",
                    flow_step_num=next(flow_step),
                    ai_request=messages,
                )
                ai_response = ai_model.get_response(messages)

                logger.info(
                    "Got response",
                    flow_stage="got_final",
                    flow_step_num=next(flow_step),
                    ai_response=ai_response,
                )
                await update_request_status(
                    RequestStatus.done, None, db, req.request_id
                )

                req.response = ai_response
                if req.structured_response.csv:
                    # remove CSV data from the response except if data has single value
                    if not (len(csv_rows) == 1 and len(csv_headers) == 1):
                        pattern = r"```csv.*?```"
                        cleaned = re.sub(pattern, "", ai_response, flags=re.DOTALL)
                        req.response = cleaned

                return req

        # process single SQL statement
        req.structured_response.sql = extracted_sql
        logger.info(
            "Extracted SQL",
            flow_stage="extracted_sql",
            flow_step_num=next(flow_step),
            extracted_sql=extracted_sql,
        )

        try:
            sqlglot.parse(extracted_sql, dialect=warehouse_dialect)
        except sqlglot.errors.ParseError as e:
            logger.error(
                "SQL syntax error",
                flow_stage="extracted_sql",
                flow_step_num=next(flow_step),
                extracted_sql=extracted_sql,
                error=str(e),
            )

        await update_request_status(RequestStatus.data, None, db, req.request_id)
        try:
            wh_result = run_structured_wh_request_native(extracted_sql, db_wh)
            # wh_result = run_structured_wh_request_raw(extracted_sql, db_wh)
            # wh_result = run_structured_wh_request(extracted_sql, db_wh)
        except Exception as e:
            error_pattern = r"(DB::Exception.*?)Stack trace"
            error_match = re.search(error_pattern, str(e), re.DOTALL)
            logger.error(
                "Error running SQL request",
                flow_stage="error_sql",
                flow_step_num=next(flow_step),
                error=error_match.group(1) if error_match else str(e),
            )
            req.status = RequestStatus.error
            req.err = error_match.group(1) if error_match else str(e)
            return req

        # logger.info(
        #   "Can't extract SQL to get the data", flow_stage='got_data', flow_step_num=next(flow_step)
        # )
        if wh_result.get("csv"):
            ai_request = f"""
                Here is the data you requested on previous step in CSV format ```csv \n
                {wh_result.get("csv")} \n```\n
            """
        else:
            ai_request = "There is no data for you SQL request from previous step. \n"

    else:
        logger.info(
            "Can't extract SQL to get the data",
            flow_stage="no_sql",
            flow_step_num=next(flow_step),
        )
        ai_request = """
            I did not find SQL request in your previous response. 
            Considering you don't need any additional data. 
        """

    ai_request = (
        ai_request
        + """
            Please generate final response to original user input.\n 
            If there is no data needed please prepare polite response 
            that we have not necessary data.\n
        """
    )

    csv_headers = []
    csv_rows = []
    if wh_result.get("rows") > 0:
        req.structured_response.csv = wh_result.get("csv")
        csv_file = io.StringIO(req.structured_response.csv)
        reader = csv.reader(csv_file)
        csv_data = list(reader)
        csv_headers = csv_data[0] if len(csv_data) > 0 else []
        csv_rows = csv_data[1:][0] if len(csv_data) > 1 else []
        if len(csv_headers) > 1 or len(csv_rows) > 1:
            ai_request = (
                ai_request
                + """Instead of formatting the supplied csv data, 
                    insert CSV-formatted data (```csv ...```) 
                    in the relevant part of your response.\n """
            )

    if ai_model.get_name() != "gemini":
        messages.append({"role": "system", "content": ai_request})
    else:
        messages = f"""
        {messages}\n
        {ai_request}\n"""

    await update_request_status(RequestStatus.finalizing, None, db, req.request_id)
    logger.info(
        "Prepared ai_request",
        flow_stage="ask_for_final",
        flow_step_num=next(flow_step),
        ai_request=messages,
    )
    ai_response = ai_model.get_response(messages)

    logger.info(
        "Got response",
        flow_stage="got_final",
        flow_step_num=next(flow_step),
        ai_response=ai_response,
    )
    await update_request_status(RequestStatus.done, None, db, req.request_id)

    req.response = ai_response
    if req.structured_response.csv:
        # remove CSV data from the response except if data has a single value
        if not (len(csv_rows) == 1 and len(csv_headers) == 1):
            pattern = r"```csv.*?```"
            cleaned = re.sub(pattern, "", ai_response, flags=re.DOTALL)
            req.response = cleaned

    return req
