import logging
from typing import Annotated, Any

from fastapi import Header
from fastmcp import FastMCP

from dbmeta_app.api.model import (
    GetPromptItemsRequestV2,
    GetPromptModel,
    GetTableDetailsRequest,
    GetTableDetailsResponse,
    PromptItemType,
    PromptsSetModel,
    TestSqlModel,
    ValidatePlanRequest,
    ValidatePlanResult,
)
from dbmeta_app.config import get_settings
from dbmeta_app.prompt_items.db_struct import (
    DbSchema,
    PreflightResult,
    get_data_samples,
    get_db_schema,
    get_schema_prompt_item,
    query_preflight,
    validate_plan_against_schema,
)
from dbmeta_app.prompt_items.domain_model import get_domain_model_item
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
            get_schema_prompt_item(
                user_request=user_request
            ),  # Enable semantic filtering
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
        {get_schema_prompt_item(user_request=user_request).text}\n\n
        {get_query_example_prompt_item(query=user_request, db=db).text}\n\n
        {get_prompt_instructions_item(profile=db).text}
        {get_sql_dialect_item(profile=db).text}
    """
    logging.info(f"prompt_items: {db_meta}")

    return db_meta


@mcp.tool()
async def prompt_items_v2(
    req: GetPromptItemsRequestV2, request_id: Annotated[str | None, Header()] = None
) -> PromptsSetModel:
    """
    Get prompt items with structured response and lineage metadata.

    Returns individual PromptItems with content_hash and metadata for tracking.
    Allows parameterized selection of which items to include via the items array.

    Args:
        req: Request with user_request, db profile, items to include, and top_k params

    Returns:
        PromptsSetModel with list of PromptItems including hash and metadata
    """
    logging.info(
        "prompt_items_v2 request",
        extra={"request_id": request_id, "request": req.model_dump()},
    )

    db = req.db if req.db else settings.database_wh_db
    prompt_items_list = []

    # Generate requested items
    for item_type in req.items:
        if item_type == PromptItemType.db_struct:
            item = get_schema_prompt_item(
                user_request=req.user_request,
                top_k=req.schema_top_k,
            )
            prompt_items_list.append(item)

        elif item_type == PromptItemType.query_example:
            if req.user_request:
                item = get_query_example_prompt_item(
                    query=req.user_request,
                    db=db,
                )
                prompt_items_list.append(item)

        elif item_type == PromptItemType.instruction:
            item = get_prompt_instructions_item(profile=db)
            prompt_items_list.append(item)

        elif item_type == PromptItemType.sql_dialect:
            item = get_sql_dialect_item(profile=db)
            prompt_items_list.append(item)

        elif item_type == PromptItemType.domain_model:
            item = get_domain_model_item(profile=db)
            if item:  # Only append if domain_model.md exists
                prompt_items_list.append(item)

    response = PromptsSetModel(
        prompt_items=prompt_items_list,
        source="db_meta",
        version="2.0.0",
    )

    logging.info(
        "prompt_items_v2 response",
        extra={
            "request_id": request_id,
            "items_count": len(prompt_items_list),
            "item_types": [item.prompt_item_type for item in prompt_items_list],
        },
    )

    return response


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


@mcp.tool()
async def validate_plan(req: ValidatePlanRequest) -> ValidatePlanResult:
    """
    Validate that tables and columns from a query plan exist in the database schema.

    This tool checks:
    1. All tables in the plan exist in the schema
    2. All columns_referenced exist in the schema

    Returns validation result with:
    - valid: boolean indicating if all tables/columns exist
    - errors: list of validation errors with type, name, and suggestion
    - available_tables: list of valid table names (only if errors exist)
    """
    result = validate_plan_against_schema(
        tables=req.tables,
        columns_referenced=req.columns_referenced,
    )
    return ValidatePlanResult(**result)


@mcp.tool()
async def get_table_details(req: GetTableDetailsRequest) -> GetTableDetailsResponse:
    """
    Get detailed metadata for specific tables including relationships and statistics.

    This tool provides granular, on-demand schema exploration for selected tables.
    Use this after query planning to get rich metadata for tables you'll query.

    Includes (based on 'include' parameter):
    - relationships: Primary keys and foreign key constraints
    - cardinality: Approximate distinct value counts per column
    - low_cardinality_values: Actual values for columns with few distinct values
    - ranges: Min/max values for numeric and date columns
    - indexes: Index information

    Args:
        req: Request with:
            - tables: List of fully qualified table names (e.g., "schema.table")
            - db: Optional database profile ("wh", "wh_new", "wh_v2")
            - include: List of detail types to fetch
            - cardinality_threshold: Max distinct values for "low cardinality"
            - sample_size: Rows to sample for statistics

    Returns:
        GetTableDetailsResponse with:
            - tables: List of TableDetails with columns, relationships, and stats
            - content_hash: SHA256 hash for lineage tracking
            - metadata: Request parameters and profile info
    """
    from dbmeta_app.prompt_items.table_details import (
        get_table_details as get_table_details_impl,
    )

    return get_table_details_impl(req)
