"""
Data Only Flow - Simplified SQL generation and execution for raw data extraction.

This flow provides a streamlined path for requests that only need data without
natural language responses or complex processing:

1. **Prompt Assembly**: Builds system prompt using the "legacy_data_only" slot with MCP context
2. **SQL Generation**: LLM generates SQL query from user request (single attempt, no retry loop)
3. **SQL Extraction**: Extracts SQL from LLM response (expects ```sql ... ``` format)
4. **Syntax Validation**: Validates SQL syntax using sqlglot (logs errors but continues)
5. **Query Execution**: Runs SQL against warehouse database
6. **Data Return**: Returns raw CSV data in structured response

Key characteristics:
- No retry/repair loop - single attempt SQL generation
- No query metadata, explanations, or column definitions
- No natural language response generation
- No query storage or lineage tracking
- No cost/complexity analysis before execution
- Minimal error handling - fails fast on SQL errors

Use cases:
- API-driven data extraction where clients handle their own error handling
- Simple, well-defined queries that don't need iterative refinement
- Batch data exports where speed is more important than validation
- Programmatic integrations that work directly with CSV output

This flow trades robustness and user-friendliness for speed and simplicity,
making it suitable for programmatic access rather than interactive exploration.
"""

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
from fm_app.mcp_servers.mcp_async_providers import (
    DbMetaAsyncProvider,
    DbRefAsyncProvider,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
from fm_app.utils import get_cached_warehouse_dialect


async def data_only_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
):
    logger = structlog.wrap_logger(get_task_logger(__name__))
    flow_step = itertools.count(1)  # start from 1

    settings = get_settings()
    warehouse_dialect = get_cached_warehouse_dialect()
    structlog.contextvars.bind_contextvars(
        request_id=req.request_id, flow_name=ai_model.get_name() + "_data_only"
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
    db_meta_caps = {}
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
        "legacy_data_only",
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
            await update_request_status(
                RequestStatus.error, req.err, db, req.request_id
            )
            return req

        if not wh_result.get("csv"):
            await update_request_status(RequestStatus.done, None, db, req.request_id)
            logger.info(
                "SQL request returned no data",
                flow_stage="no_data",
                flow_step_num=next(flow_step),
            )
            return req

    else:
        await update_request_status(RequestStatus.error, "No SQL", db, req.request_id)
        logger.info(
            "Can't extract SQL to get the data",
            flow_stage="no_sql",
            flow_step_num=next(flow_step),
        )
        return req

    if wh_result.get("rows") > 0:
        req.structured_response.csv = wh_result.get("csv")

    await update_request_status(RequestStatus.done, None, db, req.request_id)
    return req
