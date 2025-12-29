import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal
from logging.config import dictConfig

import structlog
import urllib3
from celery import Celery
from celery.signals import setup_logging
from celery.utils.log import get_task_logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from trino.auth import BasicAuthentication

from fm_app.ai_models.llm import (
    AnthropicModel,
    DeepSeekModel,
    GeminiModel,
    OpenAIModel,
)
from fm_app.api.db_session import normalize_database_driver
from fm_app.api.model import (
    DBType,
    FlowType,
    ModelType,
    RequestStatus,
    UpdateRequestModel,
    WorkerRequest,
)
from fm_app.config import get_settings
from fm_app.db.db import update_request, update_request_failure
from fm_app.workers.db_session import get_db
from fm_app.workers.experimental.flex_flow import flex_flow
from fm_app.workers.experimental.langgraph_flow import langgraph_flow
from fm_app.workers.experimental.mcp_flow import mcp_flow
from fm_app.workers.interactive_flow import interactive_flow
from fm_app.workers.legacy.data_only_flow import data_only_flow
from fm_app.workers.legacy.multistep_flow import multistep_flow
from fm_app.workers.legacy.simple_flow import simple_flow

# Disable urllib3 SSL warnings for Trino connections with verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def serialize_value(value):
    """Convert non-JSON-serializable types to JSON-compatible formats."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    elif isinstance(value, Decimal):
        return float(value)
    elif value is None:
        return None
    else:
        return value


settings = get_settings()

LOGGING_CONFIG_NORMAL = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {
            # "()": jsonlogger.JsonFormatter,
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        }
    },
    "handlers": {
        "default": {
            "level": settings.log_level,
            "class": "logging.StreamHandler",
            "formatter": "plain",
        },
    },
    "loggers": {
        "": {"handlers": ["default"], "level": settings.log_level},
        "celery.app.trace": {
            "handlers": ["default"],
            "level": "WARNING",
            "propagate": False,
        },
        "celery.worker": {
            "handlers": ["default"],
            "level": "WARNING",
            "propagate": False,
        },
        "amqp": {
            "handlers": ["default"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
LOGGING_CONFIG_JSON = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {
            # "()": jsonlogger.JsonFormatter,
            "format": "%(message)s",
        }
    },
    "handlers": {
        "default": {
            "level": settings.log_level,
            "class": "logging.StreamHandler",
            "formatter": "plain",
        },
    },
    "loggers": {
        "": {"handlers": ["default"], "level": settings.log_level},
        "celery.app.trace": {
            "handlers": ["default"],
            "level": "WARNING",
            "propagate": False,
        },
        "celery.worker": {
            "handlers": ["default"],
            "level": "WARNING",
            "propagate": False,
        },
        "amqp": {
            "handlers": ["default"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}


def create_wh_engine(driver: str, url: str):
    if driver == "trino":
        logging.info("Starting Trino session")
        wh_engine = create_engine(
            url,
            echo=False,  # Disable SQLAlchemy query logging
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=360,
            connect_args={
                "http_scheme": "https",
                # Use a CA file path instead in prod, e.g. "/path/to/ca.crt"
                "verify": False,
                "auth": BasicAuthentication(
                    settings.database_wh_user, settings.database_wh_pass
                ),
            },
        )
    else:
        logging.info(f"Starting {driver} session")
        wh_engine = create_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=360,
        )
    return wh_engine


app = Celery(
    "ai_handler",
    broker=settings.wrk_broker_connection,
)

# Use PostgreSQL as result backend
result_backend_url = f"db+postgresql://{settings.database_user}:{settings.database_pass}@{settings.database_server}:{settings.database_port}/{settings.database_db}"

app.conf.update(
    broker_connection_retry_on_startup=True,
    result_backend=result_backend_url,
    result_expires=3600,  # Results expire after 1 hour
)

normalized_driver = normalize_database_driver(settings.database_wh_driver)

DATABASE_URL_WH = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server}:{settings.database_wh_port}/{settings.database_wh_db}{settings.database_wh_params}"
DATABASE_URL_WH_NEW = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_new}:{settings.database_wh_port_new}/{settings.database_wh_db_new}{settings.database_wh_params_new}"
DATABASE_URL_WH_V2 = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_v2}:{settings.database_wh_port_v2}/{settings.database_wh_db_v2}{settings.database_wh_params_v2}"
ENGINE_WH = create_wh_engine(normalized_driver, DATABASE_URL_WH)
# ENGINE_WH = create_engine(
#     DATABASE_URL_WH, pool_size=40, max_overflow=60, pool_pre_ping=True,
#     pool_recycle=360
# )
# )
ENGINE_WH_NEW = create_wh_engine(normalized_driver, DATABASE_URL_WH_NEW)
# ENGINE_WH_NEW = create_engine(
#     DATABASE_URL_WH_NEW,
#     pool_size=40,
#     max_overflow=60,
#     pool_pre_ping=True,
#     pool_recycle=360,
# )

ENGINE_WH_V2 = create_wh_engine(normalized_driver, DATABASE_URL_WH_V2)
# ENGINE_WH_V2 = create_engine(
#     DATABASE_URL_WH_V2,
#     pool_size=40,
#     max_overflow=60,
#     pool_pre_ping=True,
#     pool_recycle=360,
# )

SESSION_WH = sessionmaker(bind=ENGINE_WH, expire_on_commit=False)
SESSION_WH_NEW = sessionmaker(bind=ENGINE_WH_NEW, expire_on_commit=False)
SESSION_WH_V2 = sessionmaker(bind=ENGINE_WH_V2, expire_on_commit=False)

# Import notification tasks to register them with Celery
# Must happen after 'app' is created above
from fm_app.workers.tasks import notify  # noqa: F401, E402


def add_fields_to_log(logger, log_method, event_dict):
    if isinstance(logger, logging.Logger):
        event_dict["name"] = logger.name
    ts = event_dict.get("timestamp")
    if ts:
        event_dict["asctime"] = ts
    return event_dict


if settings.json_log:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            add_fields_to_log,
            structlog.processors.JSONRenderer(),
        ],
    )
logger = structlog.wrap_logger(get_task_logger(__name__))


@setup_logging.connect
def config_loggers(*args, **kwargs):
    if settings.json_log:
        dictConfig(LOGGING_CONFIG_JSON)
    else:
        dictConfig(LOGGING_CONFIG_NORMAL)


@app.on_after_finalize.connect
def setup_agent_context(sender, **kwargs):
    # Run the agent initializer once on worker startup
    # asyncio.get_event_loop().run_until_complete(init_agent())
    logger.info("Agent context setup placeholder")


@app.on_after_finalize.disconnect
def cleanup_agent_context(sender, **kwargs):
    # Run the agent initializer once on worker startup
    # asyncio.get_event_loop().run_until_complete(close_agent())
    logger.info("Agent context setup placeholder")


@app.task(name="wrk_add_request")
def wrk_add_request(args):
    from fm_app.workers.db_session import dispose_engine_for_current_loop

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_wrk_add_request(args))
    finally:
        # Dispose the SQLAlchemy engine for this event loop to release connections
        try:
            loop.run_until_complete(dispose_engine_for_current_loop())
        except Exception:
            pass  # Best effort cleanup
        loop.close()


async def _wrk_add_request(args):
    request = WorkerRequest(**args)
    try:
        async for db in get_db():
            db_wh = SESSION_WH()
            db_wh_new = SESSION_WH_NEW()
            db_wh_v2 = SESSION_WH_V2()
            logger.info(
                "Got request",
                args=args,
                flow_step_num=0,
                flow_stage="got_request",
                flow=request.flow,
                model=request.model,
                db=request.db,
            )

            # new flows
            if request.model and (request.db or request.db == ""):
                if request.model == ModelType.openai_default:
                    OpenAIModel.init(settings)
                    llm = OpenAIModel
                elif request.model == ModelType.gemini_default:
                    GeminiModel.init(settings)
                    llm = GeminiModel
                elif request.model == ModelType.deepseek_default:
                    DeepSeekModel.init(settings)
                    llm = DeepSeekModel
                elif request.model == ModelType.anthropic_default:
                    AnthropicModel.init(settings)
                    llm = AnthropicModel
                else:
                    raise NotImplementedError("model not known or not implemented")

                if request.db == DBType.legacy:
                    db_wh = db_wh
                elif request.db == DBType.new_wh:
                    db_wh = db_wh_new
                elif request.db == DBType.v2:
                    db_wh = db_wh_v2
                else:
                    raise NotImplementedError("db not known or not implemented")

                if request.flow == FlowType.simple:
                    request = await simple_flow(request, llm, db_wh=db_wh, db=db)
                elif request.flow == FlowType.multistep:
                    request = await multistep_flow(request, llm, db_wh=db_wh, db=db)
                elif request.flow == FlowType.data_only:
                    request = await data_only_flow(request, llm, db_wh=db_wh, db=db)
                elif request.flow == FlowType.mcp:
                    request = await mcp_flow(request, llm)
                elif request.flow == FlowType.flex:
                    request = await flex_flow(request, llm, db_wh=db_wh, db=db)
                elif request.flow == FlowType.langgraph:
                    request = await langgraph_flow(request, llm, db_wh=db_wh, db=db)
                elif request.flow == FlowType.interactive:
                    request = await interactive_flow(request, llm, db_wh=db_wh, db=db)
                else:
                    raise NotImplementedError("flow not known or not implemented")

            # legacy flows
            elif request.flow == FlowType.openai_simple:
                OpenAIModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(request, OpenAIModel, db_wh=db_wh, db=db)
            elif request.flow == FlowType.openai_simple_new_wh:
                OpenAIModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(
                    request, OpenAIModel, db_wh=db_wh_new, db=db
                )
            elif request.flow == FlowType.openai_simple_v2:
                OpenAIModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(request, OpenAIModel, db_wh=db_wh_v2, db=db)
            elif request.flow == FlowType.openai_multisteps:
                OpenAIModel.init(settings)  # Ensure client is initialized
                request = await multistep_flow(request, OpenAIModel, db_wh=db_wh, db=db)
            elif request.flow == FlowType.deepseek_simple:
                DeepSeekModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(request, DeepSeekModel, db_wh=db_wh, db=db)
            elif request.flow == FlowType.deepseek_simple_new_wh:
                DeepSeekModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(
                    request, DeepSeekModel, db_wh=db_wh_new, db=db
                )
            elif request.flow == FlowType.deepseek_simple_v2:
                DeepSeekModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(
                    request, DeepSeekModel, db_wh=db_wh_v2, db=db
                )
            elif request.flow == FlowType.deepseek_multistep:
                DeepSeekModel.init(settings)  # Ensure client is initialized
                request = await multistep_flow(
                    request, DeepSeekModel, db_wh=db_wh, db=db
                )
            elif request.flow == FlowType.gemini_simple:
                GeminiModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(request, GeminiModel, db_wh=db_wh, db=db)
            elif request.flow == FlowType.gemini_simple_new_wh:
                GeminiModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(
                    request, GeminiModel, db_wh=db_wh_new, db=db
                )
            elif request.flow == FlowType.gemini_simple_v2:
                GeminiModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(request, GeminiModel, db_wh=db_wh_v2, db=db)
            elif request.flow == FlowType.gemini_multistep:
                GeminiModel.init(settings)  # Ensure client is initialized
                request = await multistep_flow(request, GeminiModel, db_wh=db_wh, db=db)
            elif request.flow == FlowType.anthropic_simple:
                AnthropicModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(request, AnthropicModel, db_wh=db_wh, db=db)
            elif request.flow == FlowType.anthropic_simple_new_wh:
                AnthropicModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(
                    request, AnthropicModel, db_wh=db_wh_new, db=db
                )
            elif request.flow == FlowType.anthropic_simple_v2:
                AnthropicModel.init(settings)  # Ensure client is initialized
                request = await simple_flow(
                    request, AnthropicModel, db_wh=db_wh_v2, db=db
                )
            elif request.flow == FlowType.anthropic_multistep:
                AnthropicModel.init(settings)  # Ensure client is initialized
                request = await multistep_flow(
                    request, AnthropicModel, db_wh=db_wh, db=db
                )
            else:
                raise NotImplementedError("leg.flow not known or not implemented")

            if request.status == RequestStatus.error:
                logger.error(
                    "Error in flow",
                    request=request.model_dump(mode="json"),
                    flow_stage="error_in_flow",
                    flow_step_num=10000,
                )
            else:
                logger.info(
                    "Done with request",
                    request=request.model_dump(mode="json"),
                    flow_stage="done_with_request",
                    flow_step_num=10000,
                )

                # Preserve terminal statuses that shouldn't be overwritten to 'done'
                # - feedback_requested: waiting for user approval of query plan
                # - error: request failed
                terminal_statuses = {
                    RequestStatus.feedback_requested,
                    RequestStatus.error,
                }
                if request.status in terminal_statuses:
                    status = request.status
                else:
                    status = RequestStatus.done
                structured_response = request.structured_response
                if structured_response is None:
                    await update_request(
                        db=db,
                        update=UpdateRequestModel(
                            request_id=request.request_id,
                            err=request.err,
                            status=status,
                            response=request.response,
                        ),
                    )
                else:
                    # if structured_response.linked_session_id is not None:
                    #    # launch a new worker task for linked session
                    #    (response, task_id) = await add_request(
                    #        user_owner=request.user,
                    #        session_id=structured_response.linked_session_id,
                    #        add_req=AddRequestModel(
                    #            request=request.request,
                    #            request_type=InteractiveRequestType.tbd,
                    #            flow=request.flow,
                    #            model=request.model,
                    #            db=request.db,
                    #            refs=request.refs,
                    #        ),
                    #        db=db,
                    #    )
                    #    wrk_req = WorkerRequest(
                    #        session_id=structured_response.linked_session_id,
                    #        request_id=response.request_id,
                    #        user=request.user,
                    #        request=request.request,
                    #        request_type=InteractiveRequestType.tbd,
                    #        response=None,
                    #        status=RequestStatus.new,
                    #        flow=request.flow,
                    #        model=request.model,
                    #        db=request.db,
                    #        refs=request.refs,
                    #    )
                    #    wrk_arg = wrk_req.model_dump()
                    #    task = wrk_add_request.apply_async(
                    #        args=[wrk_arg], task_id=task_id
                    #    )
                    #    logging.info(
                    #        "Send linked task",
                    #        extra={"action": "send_task", "task_id": task},
                    #    )
                    #    print("spawned linked task", task_id)

                    # Build response_type and payload from structured_response
                    response_type = structured_response.response_type
                    payload = None

                    if (
                        response_type == "clarification"
                        and structured_response.clarification
                    ):
                        payload = structured_response.clarification.model_dump()
                    elif (
                        response_type == "plan_approval"
                        and structured_response.query_plan
                    ):
                        payload = structured_response.query_plan.model_dump()
                    # For other types, payload can be built as needed

                    logger.info(
                        "Updating request with response_type and payload",
                        flow_stage="update_request_response_type",
                        response_type=response_type,
                        has_payload=payload is not None,
                        has_clarification=structured_response.clarification is not None,
                        request_id=str(request.request_id),
                    )

                    await update_request(
                        db=db,
                        update=UpdateRequestModel(
                            request_id=request.request_id,
                            err=request.err,
                            status=status,
                            response=request.response,
                            sql=structured_response.sql,
                            intent=structured_response.intent,
                            assumptions=structured_response.assumptions,
                            intro=structured_response.intro,
                            outro=structured_response.outro,
                            raw_data_labels=structured_response.raw_data_labels,
                            raw_data_rows=structured_response.raw_data_rows,
                            csv=structured_response.csv,
                            chart=structured_response.chart,
                            chart_url=structured_response.chart_url,
                            refs=(
                                structured_response.refs.model_dump(mode="json")
                                if structured_response.refs
                                else None
                            ),
                            linked_session_id=structured_response.linked_session_id,
                            query_plan=(
                                structured_response.query_plan.model_dump()
                                if structured_response.query_plan
                                else None
                            ),
                            response_type=response_type,
                            payload=payload,
                        ),
                    )
            # await db.close()

    except Exception as e:
        async for db in get_db():
            request.status = RequestStatus.error
            logger.error(
                f"Unhandled Exception: {e}",
                request=request.model_dump(mode="json"),
                exc_info=True,
            )
            request.err = "Unhandled exception, check logs"
            await update_request_failure(err=str(e), status=RequestStatus.error, db=db)
            # await db.close()

    # finally:
    #    return request


@app.task(
    name="wrk_fetch_data",
    bind=True,
    soft_time_limit=settings.query_soft_timeout,
    time_limit=settings.query_hard_timeout,
)
def wrk_fetch_data(self, args):
    """
    Background task for fetching data from warehouse with Redis caching.
    Args:
        args: dict with keys:
            - query_id: str (UUID)
            - sql: str (the SQL query to execute)
            - limit: int
            - offset: int
            - sort_by: Optional[str]
            - sort_order: str
            - notify_on_complete: bool (optional)
            - user_email: str (optional, for notifications)
            - data_fetch_id: str (UUID, optional) - for tracking
    Returns:
        dict with keys:
            - status: "success" | "error"
            - rows: list[dict] (if success)
            - total_rows: int (if success)
            - error: str (if error)
    """

    from uuid import UUID as PyUUID

    from sqlalchemy import text

    from fm_app.cache.query_cache import get_cached_query, run_async, set_cached_query

    query_id = args.get("query_id")
    sql = args.get("sql")
    limit = args.get("limit", 100)
    offset = args.get("offset", 0)
    sort_by = args.get("sort_by")
    sort_order = args.get("sort_order", "asc")
    notify_on_complete = args.get("notify_on_complete", False)
    user_email = args.get("user_email")
    force = args.get("force", False)
    data_fetch_id = args.get("data_fetch_id")

    # Helper to update data_fetch status
    def update_data_fetch_status(status, row_count=None, error=None, cache_hit=False):
        if not data_fetch_id:
            return
        try:
            from fm_app.api.model import DataFetchStatus
            from fm_app.db.data_fetch_db import (
                update_data_fetch_completed,
                update_data_fetch_error,
                update_data_fetch_started,
            )
            from fm_app.workers.db_session import get_db

            async def do_update():
                async for db in get_db():
                    df_id = PyUUID(data_fetch_id)
                    if status == "running":
                        await update_data_fetch_started(db, df_id)
                    elif status == "success":
                        await update_data_fetch_completed(
                            db, df_id, row_count or 0, cache_hit
                        )
                    elif status == "error":
                        await update_data_fetch_error(
                            db, df_id, error or "Unknown error", DataFetchStatus.error
                        )
                    elif status == "timed_out":
                        await update_data_fetch_error(
                            db, df_id, error or "Timeout", DataFetchStatus.timed_out
                        )
                    elif status == "cancelled":
                        await update_data_fetch_error(
                            db, df_id, error or "Cancelled", DataFetchStatus.cancelled
                        )

            run_async(do_update())
        except Exception as e:
            logger.warning(f"Failed to update data_fetch status: {e}")

    # Report task has started (prevents false "workers_busy" warnings)
    self.update_state(
        state="STARTED",
        meta={
            "query_id": query_id,
            "stage": "started",
        },
    )

    # Update data_fetch to running status
    update_data_fetch_status("running")

    logger.info(
        f"Starting data fetch for query {query_id}",
        extra={
            "query_id": query_id,
            "limit": limit,
            "offset": offset,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "notify_requested": notify_on_complete,
            "has_email": bool(user_email),
            "force": force,
        },
    )

    # Check cache first (skip if force=True)
    try:
        from fm_app.cache.query_cache import invalidate_query_cache, run_async

        cached_result = None
        if not force:
            cached_result = run_async(
                get_cached_query(query_id, limit, offset, sort_by, sort_order)
            )
        else:
            # Invalidate all cache entries for this query before fetching fresh data
            invalidated_count = run_async(invalidate_query_cache(query_id))
            logger.info(
                f"Force refresh requested, invalidated {invalidated_count} "
                f"cache entries for query {query_id}"
            )

        if cached_result:
            logger.info(f"Returning cached data for query {query_id}")
            total_rows = cached_result["total_rows"]
            result = {
                "status": "success",
                "query_id": query_id,
                "rows": cached_result["rows"],
                "total_rows": total_rows,
                "limit": limit,
                "offset": offset,
                "from_cache": True,
            }

            # Clear running task tracker
            from fm_app.cache.query_cache import run_async
            from fm_app.cache.task_tracker import clear_running_task

            run_async(clear_running_task(query_id))

            # Update data_fetch tracking - cache hit success
            update_data_fetch_status("success", row_count=total_rows, cache_hit=True)

            # Do NOT send notification for cached results - only for fresh queries
            # Cache hits return immediately, so notifications aren't needed
            logger.debug(f"Cache hit - notification not sent for query {query_id}")

            return result
    except Exception as e:
        logger.warning(f"Cache check failed, continuing with DB query: {e}")

    try:
        # Fetch actual data
        from fm_app.api.routes import build_sorted_paginated_sql

        # Build the paginated SQL (no need for total_count now)
        combined_sql = build_sorted_paginated_sql(
            sql,
            sort_by=sort_by,
            sort_order=sort_order,
            include_total_count=settings,  # We already have it
        )

        # Report we're about to execute the query (this is the slow part)
        self.update_state(
            state="PROGRESS",
            meta={
                "query_id": query_id,
                "stage": "executing_query",
            },
        )

        # Execute using the warehouse engine
        with ENGINE_WH_V2.connect() as conn:
            result = conn.execute(
                text(combined_sql),
                {
                    "limit": limit,
                    "offset": offset,
                },
            )

            # Convert to dicts
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            # Extract total_count if present (case-insensitive for Trino)
            if rows:
                total_count = None
                for k in rows[0].keys():
                    if k.lower() == "total_count":
                        total_count = rows[0].get(k, 0)
                        break
                if total_count is None:
                    total_count = 0
            else:
                total_count = 0

            logger.debug(
                "Fetching data done",
                query_id=query_id,
                total_count=total_count,
            )

            serialized_rows = [
                {
                    k: serialize_value(v)
                    for k, v in row.items()
                    if k.lower() != "total_count"
                }
                for row in rows
            ]

            # Cache the results
            try:
                run_async(
                    set_cached_query(
                        query_id,
                        limit,
                        offset,
                        serialized_rows,
                        total_count,
                        sort_by,
                        sort_order,
                    )
                )
            except Exception as cache_err:
                logger.warning(f"Failed to cache query results: {cache_err}")

            result = {
                "status": "success",
                "query_id": query_id,
                "rows": serialized_rows,
                "total_rows": total_count,
                "limit": limit,
                "offset": offset,
                "from_cache": False,
            }

            # Send notifications to all subscribers who requested them
            subscribers = []
            if settings.notifications_enabled:
                from fm_app.cache.task_tracker import get_task_subscribers
                from fm_app.workers.tasks.notify import send_query_notification

                subscribers = run_async(get_task_subscribers(query_id))
                if subscribers:
                    logger.info(
                        f"Sending notifications to {len(subscribers)} "
                        f"subscriber(s) for query {query_id}"
                    )
                    for subscriber in subscribers:
                        send_query_notification.delay(
                            query_id,
                            subscriber["user_email"],
                            row_count=total_count,
                        )

            # Clear running task tracker
            from fm_app.cache.task_tracker import clear_running_task

            run_async(clear_running_task(query_id))

            # Update data_fetch tracking - database query success
            update_data_fetch_status("success", row_count=total_count, cache_hit=False)

            logger.info(
                f"Data fetch completed successfully for query {query_id}",
                extra={
                    "query_id": query_id,
                    "rows_returned": len(serialized_rows),
                    "total_rows": total_count,
                    "from_cache": False,
                    "notifications_sent": len(subscribers),
                },
            )

            return result

    except Exception as e:
        from celery.exceptions import SoftTimeLimitExceeded

        if isinstance(e, SoftTimeLimitExceeded):
            timeout_minutes = (
                settings.query_soft_timeout // 60 if settings.query_soft_timeout else 0
            )
            logger.warning(
                f"Query timeout ({timeout_minutes} minute soft limit): {query_id}",
                query_id=query_id,
            )

            # Send timeout notifications to all subscribers (only once per query)
            if settings.notifications_enabled:
                from fm_app.cache.task_tracker import (
                    get_task_subscribers,
                    set_timeout_notified,
                )

                # Check if we've already sent timeout notifications for this query
                should_notify = run_async(set_timeout_notified(query_id))
                if should_notify:
                    from fm_app.workers.tasks.notify import (
                        send_query_timeout_notification,
                    )

                    subscribers = run_async(get_task_subscribers(query_id))
                    if subscribers:
                        logger.info(
                            f"Sending timeout notifications to {len(subscribers)} "
                            f"subscriber(s) for query {query_id}"
                        )
                        for subscriber in subscribers:
                            send_query_timeout_notification.delay(
                                query_id, subscriber["user_email"], timeout_minutes
                            )
                else:
                    logger.debug(
                        f"Timeout notification already sent for query {query_id}"
                    )

            # Update data_fetch tracking - timeout
            timeout_error = (
                f"Query execution timed out ({timeout_minutes} minute limit). "
                "Please simplify your query or add more filters."
            )
            update_data_fetch_status("timed_out", error=timeout_error)

            # Clear running task tracker so retries start fresh
            from fm_app.cache.task_tracker import clear_running_task

            run_async(clear_running_task(query_id))

            return {
                "status": "error",
                "query_id": query_id,
                "error": timeout_error,
            }

        logger.error(
            f"Error fetching data: {e}",
            query_id=query_id,
            exc_info=True,
        )

        # Update data_fetch tracking - general error
        update_data_fetch_status("error", error=str(e))

        # Clear running task tracker so retries start fresh
        from fm_app.cache.task_tracker import clear_running_task

        run_async(clear_running_task(query_id))

        return {
            "status": "error",
            "query_id": query_id,
            "error": str(e),
        }
