"""
Simple Flow - Basic SQL generation with natural language response.

This flow provides a straightforward path for data queries with natural language
responses, similar to data_only_flow but with conversational output:

1. **Prompt Assembly**: Builds system prompt using "legacy_simple_request" slot
   - Includes MCP context (db-meta and db-ref providers)
   - Contains client-specific configuration and current datetime
   - Uses slot-based template composition

2. **SQL Generation**: LLM generates SQL query (single attempt, no retry)
   - Expects ```sql ... ``` formatted response
   - No structured output - uses plain text response

3. **Query Validation**: Analyzes query via db-meta MCP server
   - Calls db_meta_mcp_analyze_query for cost/complexity analysis
   - Validates SQL syntax using sqlglot
   - Logs errors but continues execution

4. **Query Execution**: Runs SQL against warehouse database
   - Uses run_structured_wh_request for execution
   - Returns CSV data if successful
   - Fails fast on execution errors (no retry)

5. **Response Generation**: Asks LLM to format results naturally
   - Uses "legacy_simple_response" slot for prompt
   - Provides CSV data to LLM for natural language formatting
   - Handles single-value vs multi-row responses differently

6. **Response Cleanup**: Removes embedded CSV from final response
   - Keeps CSV in structured_response.csv for client use
   - Removes CSV blocks from natural language response
   - Exception: Single-value results keep CSV inline

Key characteristics:
- Single-pass SQL generation (no retry loop)
- Query analysis via MCP (unlike data_only_flow)
- Natural language response generation (unlike data_only_flow)
- Syntax validation with sqlglot
- CSV cleanup for better user experience
- No query metadata, storage, or lineage tracking
- No cost-based optimization or query decomposition

Comparison to other flows:
- **vs data_only_flow**: Adds query analysis and natural language response
- **vs flex_flow**: No adaptive execution or pipeline decomposition
- **vs interactive_query_flow**: No retry loop, metadata, or storage
- **vs multistep_flow**: Single-step vs iterative reasoning

Use cases:
- Simple data queries needing conversational responses
- One-off questions that don't require follow-up
- Scenarios where query analysis is useful but retries aren't needed
- When natural language formatting adds value over raw CSV
- Quick exploratory queries in conversational context

Trade-offs:
+ Simpler than interactive/multistep flows
+ More user-friendly responses than data_only_flow
+ Query cost analysis for visibility
- No error recovery (single attempt)
- No query storage or reuse
- No structured metadata
- Limited error handling
"""

import csv
import io
import itertools
import pathlib
import re
from datetime import datetime
from typing import Type

import sqlglot
import structlog
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel
from fm_app.api.v1.model import (
    McpServerRequest,
    RequestStatus,
    StructuredResponse,
    WorkerRequest,
)
from fm_app.config import get_settings
from fm_app.db.db import run_structured_wh_request, update_request_status
from fm_app.mcp_servers.db_meta import (
    db_meta_mcp_analyze_query,
)
from fm_app.mcp_servers.mcp_async_providers import (
    DbMetaAsyncProvider,
    DbRefAsyncProvider,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
from fm_app.utils import get_cached_warehouse_dialect


async def simple_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
):
    logger = structlog.wrap_logger(get_task_logger(__name__))

    settings = get_settings()
    warehouse_dialect = get_cached_warehouse_dialect()
    structlog.contextvars.bind_contextvars(
        request_id=req.request_id, flow_name=ai_model.get_name() + "_simple"
    )
    flow_step = itertools.count(1)  # start from 1

    logger.info(
        "Starting flow",
        flow_stage="start",
        flow_step_num=next(flow_step),
        flow=req.flow,
    )

    # Initialize for fm-app with client overlays
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

    slost_vars = {
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
        "legacy_simple_request",
        variables=slost_vars,
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
        await db_meta_mcp_analyze_query(
            req, extracted_sql, next(flow_step), settings, logger
        )
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
            # wh_result = run_structured_wh_request_native(extracted_sql, db_wh)
            # wh_result = run_structured_wh_request_raw(extracted_sql, db_wh)
            wh_result = run_structured_wh_request(extracted_sql, db_wh)
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

    slot_vars = {
        "client_id": settings.client_id,
        "current_datetime": datetime.now().replace(microsecond=0),
        "data": "",
    }

    slot = await assembler.render_async(
        "legacy_simple_response",
        variables=slot_vars,
        req_ctx={},
        mcp_caps=None,
    )

    ai_request = slot.prompt_text

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
            slot_vars = {
                "client_id": settings.client_id,
                "current_datetime": datetime.now().replace(microsecond=0),
                "data": """Instead of formatting the supplied csv data,
                    insert CSV-formatted data (```csv ...```)
                    in the relevant part of your response.\n """,
            }

            slot = await assembler.render_async(
                "legacy_simple_response",
                variables=slot_vars,
                req_ctx={},
                mcp_caps=None,
            )

            ai_request = slot.prompt_text

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
