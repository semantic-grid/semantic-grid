"""Setup and initialization for interactive flow."""

import itertools
import pathlib
from dataclasses import dataclass
from datetime import datetime
from typing import Type

import structlog
from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session

from fm_app.ai_models.model import AIModel
from fm_app.api.v1.model import WorkerRequest
from fm_app.config import Settings, get_settings
from fm_app.db.db import get_query_by_id, get_session_by_id
from fm_app.mcp_servers.mcp_async_providers import (
    DbMetaAsyncProvider,
    DbRefAsyncProvider,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
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

    # Get session data
    request_session = await get_session_by_id(session_id=req.session_id, db=db)
    parent_session = (
        await get_session_by_id(session_id=req.parent_session_id, db=db)
        if req.parent_session_id
        else None
    )

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
    )


async def build_prompt_variables(ctx: FlowContext) -> dict:
    """Build common prompt variables from context."""
    req = ctx.req
    request_session = ctx.request_session
    parent_session = ctx.parent_session
    settings = ctx.settings
    db = ctx.db

    # Fetch referenced query if refs.parent is provided
    referenced_query = None
    if req.refs is not None and req.refs.parent is not None:
        try:
            referenced_query = await get_query_by_id(query_id=req.refs.parent, db=db)
            ctx.logger.info(
                "Fetched referenced query from refs.parent",
                referenced_query_id=str(req.refs.parent),
            )
        except Exception as e:
            ctx.logger.warning(
                "Failed to fetch referenced query",
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

    return {
        "client_id": settings.client_id,
        "intent_hint": intent_hint,
        "query_metadata": query_metadata_instruction,
        "parent_query_metadata": parent_metadata_instruction,
        "parent_session_id": parent_instruction,
        "selected_row_data": rows_instruction,
        "selected_column_data": column_instruction,
        "current_datetime": datetime.now().replace(microsecond=0),
    }
