import logging
from typing import Annotated, Any

from fastapi import Header
from fastmcp import FastMCP

from dbmeta_app.api.model import GetPromptModel, PromptsSetModel, TestSqlModel
from dbmeta_app.config import get_settings
from dbmeta_app.prompt_items.db_struct import (
    DbSchema,
    PreflightResult,
    get_data_samples,
    get_db_schema,
    get_schema_prompt_item,
    query_preflight,
)
from dbmeta_app.prompt_items.prompt_instructions import (
    get_prompt_instructions,
    get_prompt_instructions_item,
)
from dbmeta_app.prompt_items.query_examples import (
    get_query_example_prompt_item,
    get_query_examples,
)
from dbmeta_app.prompt_items.sql_dialect import get_sql_dialect_item
from dbmeta_app.vector_db.milvus import QueryExample

settings = get_settings()

mcp = FastMCP(name="ApeGPT DB Metadata MCP Server")


# @app.post("/get_prompt_items")
async def get_prompts_set(
    req: GetPromptModel, request_id: Annotated[str | None, Header()] = None
) -> PromptsSetModel:
    logging.info(
        "Got request", extra={"request_id": request_id, "request": req.model_dump()}
    )
    user_request = req.user_request
    db = req.db if req.db else settings.database_wh_db
    response = PromptsSetModel(
        prompt_items=[
            get_schema_prompt_item(),
            get_query_example_prompt_item(query=user_request, db=db),
            get_prompt_instructions_item(profile=db),
        ],
        source="db_meta",
    )
    logging.info(
        "Response", extra={"request_id": request_id, "response": response.model_dump()}
    )
    return response


@mcp.tool()
async def prompt_items(
    req: GetPromptModel, request_id: Annotated[str | None, Header()] = None
) -> str:
    logging.info(
        "Got request", extra={"request_id": request_id, "request": req.model_dump()}
    )
    user_request = req.user_request
    db = req.db if req.db else settings.database_wh_db
    db_meta = f"""
        {get_schema_prompt_item().text}\n\n
        {get_query_example_prompt_item(query=user_request, db=db).text}\n\n
        {get_prompt_instructions_item(profile=db).text}
        {get_sql_dialect_item(profile=db).text}
    """
    return db_meta


# @app.get("/schema/{db_name}")
async def db_schema(db_name: str) -> DbSchema:
    """
    Get database schema, organized as a dictionary of tables.
    Each table entry includes list of columns and descriptions.
    Each column object contains the column name, type, and description.
    """
    return get_db_schema()


# @app.get("/data_samples/{db_name}")
async def db_samples(db_name: str) -> dict[str, Any]:
    """
    Get sample data from each table of the database.
    Organized as a dictionary of tables and sample data for each table.
    """
    return get_data_samples()


# @app.get("/prompt_instructions/{db_name}")
async def prompt_instructions(db_name: str) -> list[str]:
    """
    Get prompt instructions for the database.
    Organized as a list of instruction strings.
    """
    db = db_name or get_settings().database_wh_db
    return get_prompt_instructions(profile=db)


# @app.post("/query_examples/{db_name}")
async def query_examples(req: GetPromptModel, db_name: str) -> list[QueryExample]:
    """
    Get examples of queries with corresponding responses, based on user request.
    Each query example contains user request, SQL response, and relative score.
    """
    db = db_name or get_settings().database_wh_db
    user_request = req.user_request
    return get_query_examples(db=db, query=user_request)


@mcp.tool()
async def preflight_query(req: TestSqlModel) -> PreflightResult:
    """
    Check if the query is valid and can be executed.
    Returns an object which could contain **explanation** or **error** fields.
    Presence or absence of **error** field indicates if the query is invalid or not.
    """
    query = req.sql
    return query_preflight(query=query)
