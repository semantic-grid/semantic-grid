"""Setup and initialization for interactive flow."""

import itertools
import pathlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Type

import structlog
from celery.utils.log import get_task_logger
from fastmcp import Client
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel
from fm_app.api.model import WorkerRequest
from fm_app.config import Settings, get_settings
from fm_app.db.db import get_query_by_id, get_session_by_id
from fm_app.db.query_plan_db import get_plan_for_query
from fm_app.mcp_servers.db_meta import get_db_meta_client
from fm_app.mcp_servers.mcp_async_providers import (
    DbMetaAsyncProvider,
    DbRefAsyncProvider,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
from fm_app.tracing import RequestTracer
from fm_app.utils import get_cached_warehouse_dialect


@dataclass
class FlowContext:
    """Shared context for all flow handlers."""

    req: WorkerRequest
    ai_model: Type[AIModel]
    db_wh: Session
    db: AsyncSession
    logger: structlog.BoundLogger
    settings: Settings
    warehouse_dialect: str
    assembler: PromptAssembler
    flow_step: itertools.count
    request_session: any
    parent_session: any
    tracer: Optional[RequestTracer] = field(default=None)
    mcp_client: Optional[Client] = field(default=None)


async def initialize_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
) -> FlowContext:
    """Initialize flow context with all required dependencies."""
    logger = structlog.wrap_logger(get_task_logger(__name__))
    flow_step = itertools.count(1)

    settings = get_settings()
    warehouse_dialect = get_cached_warehouse_dialect()

    structlog.contextvars.bind_contextvars(
        request_id=req.request_id, flow_name=ai_model.get_name() + "_interactive"
    )

    # Initialize PromptAssembler
    repo_root = pathlib.Path(settings.packs_resources_dir)
    assembler = PromptAssembler(
        repo_root=repo_root,
        component="fm_app",
        client=settings.client_id,
        env=settings.env,
        system_version=settings.system_version,
    )

    # Register async MCP providers
    assembler.register_async_mcp(DbMetaAsyncProvider(settings, logger))
    assembler.register_async_mcp(DbRefAsyncProvider(settings, logger))

    # Initialize MCP client for db-meta (reused across flow)
    mcp_client = get_db_meta_client(settings)

    # Get session data
    request_session = await get_session_by_id(session_id=req.session_id, db=db)
    parent_session = (
        await get_session_by_id(session_id=req.parent_session_id, db=db)
        if req.parent_session_id
        else None
    )

    # Initialize request tracer for observability
    tracer = RequestTracer(req.request_id, db)

    return FlowContext(
        req=req,
        ai_model=ai_model,
        db_wh=db_wh,
        db=db,
        logger=logger,
        settings=settings,
        warehouse_dialect=warehouse_dialect,
        assembler=assembler,
        flow_step=flow_step,
        request_session=request_session,
        parent_session=parent_session,
        tracer=tracer,
        mcp_client=mcp_client,
    )


async def build_prompt_variables(ctx: FlowContext) -> dict:
    """Build common prompt variables from context."""
    req = ctx.req
    request_session = ctx.request_session
    parent_session = ctx.parent_session
    settings = ctx.settings
    db = ctx.db

    # Fetch referenced query and its plan if refs.parent is provided
    referenced_query = None
    referenced_query_plan = None
    if req.refs is not None and req.refs.parent is not None:
        try:
            referenced_query = await get_query_by_id(query_id=req.refs.parent, db=db)
            ctx.logger.info(
                "Fetched referenced query from refs.parent",
                referenced_query_id=str(req.refs.parent),
            )
            # Also fetch the plan that produced this query
            referenced_query_plan = await get_plan_for_query(
                db=db, query_id=req.refs.parent
            )
            if referenced_query_plan:
                ctx.logger.info(
                    "Fetched plan for referenced query",
                    plan_id=str(referenced_query_plan.plan_id),
                )
        except Exception as e:
            ctx.logger.warning(
                "Failed to fetch referenced query or plan",
                referenced_query_id=str(req.refs.parent),
                error=str(e),
            )

    # Build query metadata instruction with priority:
    # 1. Referenced query (refs.parent) takes precedence - shows as "Referenced Query"
    # 2. Fallback to req.query (from /for_query endpoint) - shows as "Current Query"
    # 3. Fallback to session metadata
    if referenced_query is not None:
        query_metadata_instruction = (
            f"Referenced Query (ID: {req.refs.parent}):\n"
            f"  Summary: {referenced_query.summary}\n"
            f"  Description: {referenced_query.description}\n"
            f"  SQL: {referenced_query.sql}\n"
            f"  Columns: {referenced_query.columns}"
        )
    elif req.query is not None:
        # Format req.query nicely (from /for_query endpoint)
        query_metadata_instruction = (
            f"Current Query (ID: {req.query.query_id}):\n"
            f"  Summary: {req.query.summary}\n"
            f"  Description: {req.query.description}\n"
            f"  SQL: {req.query.sql}\n"
            f"  Columns: {req.query.columns}"
        )
    elif request_session.metadata is not None:
        query_metadata_instruction = (
            f"Current QueryMetadata: {request_session.metadata}"
        )
    else:
        query_metadata_instruction = f"QueryMetadata ID (new): {req.session_id}"

    # Parent session metadata (separate from referenced query)
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

    if req.refs is not None and req.refs.cols is not None and len(req.refs.cols) > 0:
        column_id = req.refs.cols[0]
        column_instruction = (
            f"User has selected column: '{column_id}'\n"
            f"Selected Column Data [column_id, ...data values]: {req.refs.cols}"
        )
    else:
        column_instruction = ""

    rows_instruction = (
        f"Selected Row Data [[...headers], ...[...values]]: {req.refs.rows}"
        if req.refs is not None and req.refs.rows is not None
        else ""
    )

    intent_hint = f"Intent Hint: {req.request_type}"

    # Build parent query plan instruction if available
    parent_query_plan_instruction = ""
    if referenced_query_plan:
        plan = referenced_query_plan
        parent_query_plan_instruction = (
            f"Parent Query Plan (ID: {plan.plan_id}):\n"
            f"  Summary: {plan.plan_summary}\n"
            f"  Tables: {plan.tables}\n"
            f"  Primary Table: {plan.primary_table}\n"
            f"  Joins: {plan.joins}\n"
            f"  Filters: {plan.filters}\n"
            f"  Aggregations: {plan.aggregations}\n"
            f"  Assumptions: {plan.assumptions}"
        )

    return {
        "client_id": settings.client_id,
        "intent_hint": intent_hint,
        "query_metadata": query_metadata_instruction,
        "parent_query_metadata": parent_metadata_instruction,
        "parent_query_plan": parent_query_plan_instruction,
        "parent_session_id": parent_instruction,
        "selected_row_data": rows_instruction,
        "selected_column_data": column_instruction,
        "current_datetime": datetime.now().replace(microsecond=0),
        "relevant_schema": None,  # Set by interactive_query when query_plan has schema
    }
