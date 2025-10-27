import hashlib
import itertools
import json
import pathlib
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Type

import structlog
import yaml
from celery.utils.log import get_task_logger
from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.logging import LogMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from mcp.types import TextContent
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.session import Session
from typing_extensions import TypedDict

from fm_app.ai_models.model import AIModel
from fm_app.api.model import (
    DBType,
    McpServerRequest,
    RequestStatus,
    StructuredResponse,
    WorkerRequest,
)
from fm_app.config import Settings
from fm_app.db.db import update_request_status
from fm_app.mcp_servers.mcp_async_providers import (
    DbMetaAsyncProvider,
    DbRefAsyncProvider,
)
from fm_app.prompt_assembler.prompt_packs import PromptAssembler
from fm_app.workers.model import ExecutionPipeline, QueryMetadata, Step

load_dotenv(".env")
settings = Settings()
logger = structlog.wrap_logger(get_task_logger(__name__))
server_script = "fm_app/mcp_servers/solana_db.py"
flow_step = itertools.count(1)  # start from 1


def log_handler(params: LogMessage):
    logger.info(
        f"[MCP - {params.level.upper()}] {params.logger or 'default'}: {params.data}"
    )


def compute_vector_id(vector: Dict[str, Any]) -> str:
    canonical = json.dumps(vector, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[
        :16
    ]  # e.g. '9f2e3a0c1b0d8a4e'


def resolve_step_sql(
    step_sql: str,
    dependencies: Dict[str, Step],  # prior steps keyed by step.id
    id_fn: Callable[[QueryMetadata], str] = compute_vector_id,
    table_template: str = "temp_{table}_{id}",
) -> str:
    """
    Replaces logical table references like <step_X_id>
    in SQL with deterministic materialized table names.
    """
    rewritten_sql = step_sql

    for dep_id, dep_step in dependencies.items():
        if dep_step.metadata is None:
            raise ValueError(f"Step {dep_id} has no metadata to compute slice ID.")

        slice_id = id_fn(dep_step.metadata.model_dump())
        physical_table = table_template.format(
            table=dep_step.metadata.table, id=slice_id
        )

        rewritten_sql = rewritten_sql.replace(f"<{dep_id}_id>", physical_table)

    return rewritten_sql


# db_client = Client(server_script, log_handler=log_handler)
db_client = Client(server_script)

llm = ChatOpenAI(
    temperature=0.0,
    model=settings.openai_llm_name,
    api_key=settings.openai_api_key,
)


class FlowState(BaseModel):
    db_name: str
    user_input: str
    clarified_input: Optional[str] = None
    pipeline_output: Optional[Any] = None
    final_response: Optional[str] = None


class InnerState(TypedDict):
    db_name: str


async def process_input_node(state: Dict[str, Any]) -> Dict[str, Any]:
    # temp shortcut for testing
    return {"clarified_input": state.user_input}


async def generate_execution_plan_node(state: Dict[str, Any]) -> Dict[str, Any]:
    query = state.clarified_input
    db_name = state.db_name

    # Step 1: Ask LLM for a plan
    plan = await ask_llm_for_plan(query, db_name)

    # Step 3: Build dynamic subgraph
    subgraph = StateGraph(state_schema=Dict[str, Any])

    def make_executor(_step, _prev_step) -> Callable[[InnerState], Dict[str, Any]]:
        async def step_fn(inner_state: Dict[str, Any]):
            # Gather prior step metadata
            fallback_dep_id = (
                _prev_step.id if isinstance(_prev_step, Step) else _prev_step
            )
            dependencies = {
                dep_id: plan.step_map[dep_id]
                for dep_id in _step.depends_on or [fallback_dep_id]
            }
            print(f"  Executing step: {_step.id}, dependencies: {dependencies}")

            # Rewriting SQL to use real temp table names
            resolved_sql = resolve_step_sql(
                _step.sql, dependencies, id_fn=compute_vector_id
            )
            print(f"  Resolved SQL for {_step.id}: {resolved_sql}")
            # Clone the step with updated SQL
            step_with_sql = _step.model_copy(update={"sql": resolved_sql})

            result = await execute_step(step_with_sql.model_dump(), inner_state)

            print(f"  Intermediate Result for {_step.id}: {result}")

            return {
                _step.id: result,
                "db_name": inner_state["db_name"],  # keep state intact
            }

        return step_fn

    for i, step in enumerate(plan.steps):
        subgraph.add_node(
            step.id, make_executor(step, step if i == 0 else plan.steps[i - 1])
        )

    for i, step in enumerate(plan.steps):
        if i > 0 and not step.depends_on:
            subgraph.add_edge(plan.steps[i - 1].id, step.id)

    subgraph.set_entry_point(plan.steps[0].id)
    subgraph.set_finish_point(plan.output_step_id or plan.steps[-1].id)

    # Step 4: Run subgraph
    compiled = subgraph.compile()
    inner = InnerState(db_name=state.db_name)
    output_dict = await compiled.ainvoke(inner)
    print("Subgraph output:", output_dict)

    # Step 5: Extract final result
    final_result = output_dict.get(plan.output_step_id)

    print("Pipeline output:", final_result.get(plan.output_step_id, {}))
    return {
        "pipeline_output": final_result.get(plan.output_step_id, {}),
        "intermediate_steps": output_dict,
    }


async def format_response_node(state: Dict[str, Any]) -> Dict[str, Any]:
    # Format the response for the user
    response = state.pipeline_output
    print("final result", response)
    formatted_response = f"Here are the results: {json.dumps(response)}"
    return {"formatted_response": formatted_response}


NODE_REGISTRY = {
    "process_input_node": process_input_node,
    "generate_execution_plan_node": generate_execution_plan_node,
    "format_response_node": format_response_node,
}


def load_graph_from_yaml(path: str):
    with open(path, "r") as f:
        config = yaml.safe_load(f)

    graph = StateGraph(state_schema=FlowState)

    for node in config["nodes"]:
        fn = NODE_REGISTRY[node["function"]]
        graph.add_node(node["id"], fn)

    for edge in config["edges"]:
        graph.add_edge(edge["from"], edge["to"])

    graph.set_entry_point(config["entry_point"])
    graph.set_finish_point(config["finish_point"])

    return graph.compile()


async def run_sql_query(sql: str, db: str) -> dict:
    # Replace with actual DB access
    print(f"Running SQL:\n{sql}")

    async with db_client:
        try:
            result: list[TextContent] = await db_client.call_tool(
                "fetch_data",
                {
                    "request": sql,
                    "db": db,
                    "settings": settings,
                },
            )
            data = json.loads(result[0].text)
            print(f"SQL result: {data}")
            return data

        except Exception as e:
            print(f"SQL call failed: {e}")
            return {"error": str(e)}


async def execute_step(step: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    sql = step["sql"]
    # You can replace "step1" with actual result table name if needed
    print("step", step.get("id"), "state", state)
    result = await run_sql_query(sql, state.get("db_name"))
    return {step.get("id"): result}


async def ask_llm_for_plan(query: str, db_name: str) -> ExecutionPipeline:
    req = WorkerRequest(
        request=query,
        db=DBType(db_name),
        session_id=uuid.uuid4(),  # fake
        request_id=uuid.uuid4(),  # fake
        user="",  # fake
        status=RequestStatus.in_process,  # fake
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
        "flow_step_num": next(flow_step),  # for logging purposes
    }

    slot = await assembler.render_async(
        "legacy_langchain",
        variables=planner_vars,
        req_ctx=mcp_ctx,
        mcp_caps=db_meta_caps,
    )
    system = slot.prompt_text
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", f"Break down this request into execution steps: {query}"),
        ]
    )

    llm_structured = llm.with_structured_output(
        method="json_mode", schema=ExecutionPipeline.model_json_schema()
    )
    parsed = llm_structured.invoke(prompt.format_prompt(query=query).to_messages())
    print(f"PIPELINE: {parsed}")
    steps = [
        Step(
            id=f"step_{i + 1}",
            label=s.get("label") or f"step_{i + 1}",
            description=s.get("description"),
            depends_on=s.get("depends_on"),
            type=s.get("type") or "sql",
            parameters=s.get("parameters"),
            sql=s.get("sql"),
            output_table=s.get("output_table"),
            metadata=QueryMetadata(**s.get("metadata")) if s.get("metadata") else None,
        )
        for i, s in enumerate(parsed.get("steps", []))
    ]
    pipeline = ExecutionPipeline(
        query_id=str(uuid.uuid4()),
        user_question=query,
        steps=steps,
        step_map={step.id: step for step in steps},
        output_step_id=steps[-1].id,
        result=None,
    )
    return pipeline


async def langgraph_flow(
    req: WorkerRequest, ai_model: Type[AIModel], db_wh: Session, db: AsyncSession
):
    structlog.contextvars.bind_contextvars(
        request_id=req.request_id, flow_name=ai_model.get_name() + "_langgraph"
    )
    logger.info(
        "Starting flow",
        flow_stage="start",
        flow_step_num=next(flow_step),
        flow=req.flow,
    )
    pipeline = load_graph_from_yaml("./fm_app/workers/pipeline.yml")
    state = {
        "user_input": req.request,
        "user_id": req.user,
        "db_name": req.db.value,
    }
    result = await pipeline.ainvoke(state)
    print("result", result.get("pipeline_output"))

    await update_request_status(RequestStatus.done, None, db, req.request_id)
    req.response = json.dumps(result.get("pipeline_output"))
    req.structured_response = StructuredResponse()
    req.status = RequestStatus.done
    req.structured_response.csv = result.get("pipeline_output", {}).get("csv")
    return req


# print(
#    asyncio.run(
#        ask_llm_for_plan(
#           "What is the timestamp of the largest MOBILE token transfer in April 2025?",
#           "NWH",
#        )
#    )
# )
