import asyncio
import logging
from logging.config import dictConfig

import structlog
from celery import Celery
from celery.signals import setup_logging
from celery.utils.log import get_task_logger

# from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fm_app.ai_models.llm import AnthropicModel, DeepSeekModel, GeminiModel, OpenAIModel
from fm_app.api.model import (
    AddRequestModel,
    DBType,
    FlowType,
    InteractiveRequestType,
    ModelType,
    RequestStatus,
    UpdateRequestModel,
    WorkerRequest,
)
from fm_app.config import get_settings
from fm_app.db.db import add_request, update_request, update_request_failure
from fm_app.stopwatch import stopwatch
from fm_app.workers.agent import close_agent, init_agent
from fm_app.workers.data_only_flow import data_only_flow
from fm_app.workers.db_session import get_db
from fm_app.workers.flex_flow import flex_flow
from fm_app.workers.interactive_flow import interactive_flow
from fm_app.workers.langgraph_flow import langgraph_flow
from fm_app.workers.mcp_flow import mcp_flow
from fm_app.workers.multistep_flow import multistep_flow
from fm_app.workers.simple_flow import simple_flow

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
    },
}

app = Celery("ai_handler", broker=settings.wrk_broker_connection)

app.conf.update(broker_connection_retry_on_startup=True)

DATABASE_URL_WH = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server}:{settings.database_wh_port}/{settings.database_wh_db}{settings.database_wh_params}"
DATABASE_URL_WH_NEW = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_new}:{settings.database_wh_port_new}/{settings.database_wh_db_new}{settings.database_wh_params_new}"
DATABASE_URL_WH_V2 = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_v2}:{settings.database_wh_port_v2}/{settings.database_wh_db_v2}{settings.database_wh_params_v2}"

ENGINE_WH = create_engine(
    DATABASE_URL_WH, pool_size=40, max_overflow=60, pool_pre_ping=True, pool_recycle=360
)
SESSION_WH = sessionmaker(bind=ENGINE_WH, expire_on_commit=False)

ENGINE_WH_NEW = create_engine(
    DATABASE_URL_WH_NEW,
    pool_size=40,
    max_overflow=60,
    pool_pre_ping=True,
    pool_recycle=360,
)
SESSION_WH_NWW = sessionmaker(bind=ENGINE_WH_NEW, expire_on_commit=False)

ENGINE_WH_V2 = create_engine(
    DATABASE_URL_WH_V2,
    pool_size=40,
    max_overflow=60,
    pool_pre_ping=True,
    pool_recycle=360,
)
SESSION_WH_V2 = sessionmaker(bind=ENGINE_WH_V2, expire_on_commit=False)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


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
    asyncio.get_event_loop().run_until_complete(init_agent())


@app.on_after_finalize.disconnect
def cleanup_agent_context(sender, **kwargs):
    # Run the agent initializer once on worker startup
    asyncio.get_event_loop().run_until_complete(close_agent())


@app.task(name="wrk_add_request")
def wrk_add_request(args):
    return asyncio.get_event_loop().run_until_complete(_wrk_add_request(args))


async def _wrk_add_request(args):
    request = WorkerRequest(**args)
    try:
        async for db in get_db():
            db_wh = SESSION_WH()
            db_wh_new = SESSION_WH_NWW()
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
                    request=request.model_dump(),
                    flow_stage="error_in_flow",
                    flow_step_num=10000,
                )
            else:
                logger.info(
                    "Done with request",
                    request=request.model_dump(),
                    flow_stage="done_with_request",
                    flow_step_num=10000,
                )

                print(">>> DONE", stopwatch.lap())

                status = (
                    RequestStatus.done
                    if request.status != RequestStatus.error
                    else RequestStatus.error
                )
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
                    if structured_response.linked_session_id is not None:
                        # launch a new worker task for linked session
                        (response, task_id) = await add_request(
                            user_owner=request.user,
                            session_id=structured_response.linked_session_id,
                            add_req=AddRequestModel(
                                request=request.request,
                                request_type=InteractiveRequestType.tbd,
                                flow=request.flow,
                                model=request.model,
                                db=request.db,
                                refs=request.refs,
                            ),
                            db=db,
                        )
                        wrk_req = WorkerRequest(
                            session_id=structured_response.linked_session_id,
                            request_id=response.request_id,
                            user=request.user,
                            request=request.request,
                            request_type=InteractiveRequestType.tbd,
                            response=None,
                            status=RequestStatus.new,
                            flow=request.flow,
                            model=request.model,
                            db=request.db,
                            refs=request.refs,
                        )
                        wrk_arg = wrk_req.model_dump()
                        task = wrk_add_request.apply_async(
                            args=[wrk_arg], task_id=task_id
                        )
                        logging.info(
                            "Send linked task",
                            extra={"action": "send_task", "task_id": task},
                        )
                        print("spawned linked task", task_id)

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
                                structured_response.refs.model_dump()
                                if structured_response.refs
                                else None
                            ),
                            linked_session_id=structured_response.linked_session_id,
                        ),
                    )
            # await db.close()

    except Exception as e:
        async for db in get_db():
            request.status = RequestStatus.error
            logger.error(
                f"Unhandled Exception: {e}", request=request.model_dump(), exc_info=True
            )
            request.err = "Unhandled exception, check logs"
            await update_request_failure(err=str(e), status=RequestStatus.error, db=db)
            # await db.close()

    # finally:
    #    return request
