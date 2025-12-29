import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional

from fastmcp import Client

from fm_app.api.model import (
    DBType,
    FlowType,
    McpServerRequest,
    PromptItemType,
    WorkerRequest,
)


def create_db_meta_client(settings) -> Client:
    """
    Create a new MCP client for db-meta.

    Creates a fresh client instance. Use this at the flow level and pass
    the client to all MCP functions to reuse the session within a single flow.

    Note: Do NOT cache clients across Celery tasks - each task runs in a
    different event loop, and reusing clients across loops causes errors.

    Args:
        settings: Application settings containing dbmeta URL

    Returns:
        New Client instance
    """
    url = f"{settings.dbmeta}mcp"
    # Set timeout to 120 seconds - db-meta can take 45+ seconds on cache miss
    # Default httpx timeout is only 5 seconds which causes premature timeouts
    return Client(url, timeout=120)


# Alias for backward compatibility
get_db_meta_client = create_db_meta_client


@asynccontextmanager
async def db_meta_client_session(settings):
    """
    Context manager for db-meta MCP client session.

    Use this at the flow level to maintain a single session across
    multiple MCP tool calls:

        async with db_meta_client_session(settings) as client:
            result1 = await get_db_meta_mcp_prompt_items_v2(..., client=client)
            result2 = await validate_query_plan(..., client=client)

    Args:
        settings: Application settings

    Yields:
        Connected Client instance
    """
    client = create_db_meta_client(settings)
    async with client:
        yield client


@asynccontextmanager
async def _use_client(client: Optional[Client], settings):
    """
    Internal helper: use provided client or create a new session.

    If client is provided, yields it directly (assumes caller manages session).
    If client is None, creates a new client and session.

    Args:
        client: Optional pre-connected client
        settings: Application settings (used if client is None)

    Yields:
        Client instance ready for use
    """
    if client is not None:
        # Client provided - use it directly, caller manages the session
        yield client
    else:
        # No client - create new one with session
        new_client = create_db_meta_client(settings)
        async with new_client:
            yield new_client


@dataclass
class PromptItemResult:
    """Structured result from prompt_items_v2 call."""

    text: str
    prompt_item_type: PromptItemType
    content_hash: str
    metadata: Optional[dict[str, Any]] = None


@dataclass
class PromptItemsV2Result:
    """Result from prompt_items_v2 MCP call with lineage info."""

    items: list[PromptItemResult]
    source: str
    version: str
    combined_text: str  # All items concatenated for backward compat


def get_db_name(req: WorkerRequest):
    if (
        req.db == DBType.new_wh
        or req.flow == FlowType.openai_simple_new_wh
        or req.flow == FlowType.gemini_simple_new_wh
        or req.flow == FlowType.deepseek_simple_new_wh
        or req.flow == FlowType.anthropic_simple_new_wh
    ):
        db = "new_wh"
    elif (
        req.db == DBType.v2
        or req.flow == FlowType.openai_simple_v2
        or req.flow == FlowType.gemini_simple_v2
        or req.flow == FlowType.deepseek_simple_v2
        or req.flow == FlowType.anthropic_simple_v2
    ):
        db = "wh_v2"
    else:
        db = "wh"
    return db


async def get_db_meta_mcp_prompt_items(
    req: McpServerRequest,
    flow_step_num,
    settings,
    logger,
    client: Optional[Client] = None,
):
    db = get_db_name(req)
    async with _use_client(client, settings) as _client:
        try:
            prompts = await _client.call_tool(
                "prompt_items",
                {
                    "req": {
                        "user_request": req.request,
                        "db": db,
                    }
                },
            )
            logger.debug(
                f"Got prompts for db={db}, has_content={bool(prompts.content[0].text)}"
            )

        except Exception as e:
            logger.error(
                "Error reading MCP resource",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e

    return prompts.content[0].text


async def get_db_meta_mcp_prompt_items_v2(
    req: McpServerRequest,
    flow_step_num: int,
    settings,
    logger,
    items: Optional[list[str]] = None,
    schema_top_k: int = 10,
    examples_top_k: int = 5,
    client: Optional[Client] = None,
) -> PromptItemsV2Result:
    """Get prompt items with structured response and lineage metadata.

    Args:
        req: MCP server request context
        flow_step_num: Current flow step number for logging
        settings: Application settings
        logger: Logger instance
        items: List of item types to include (defaults to all)
        schema_top_k: Number of tables for schema filtering
        examples_top_k: Number of query examples
        client: Optional MCP client (for session reuse)

    Returns:
        PromptItemsV2Result with individual items and combined text
    """
    db = get_db_name(req)

    # Default items if not specified
    if items is None:
        items = ["DBStruct", "QueryExample", "Instruction", "SQLDialect", "DomainModel"]

    async with _use_client(client, settings) as _client:
        try:
            result = await _client.call_tool(
                "prompt_items_v2",
                {
                    "req": {
                        "user_request": req.request,
                        "db": db,
                        "items": items,
                        "schema_top_k": schema_top_k,
                        "examples_top_k": examples_top_k,
                    }
                },
            )

            # Parse the structured response
            response_data = json.loads(result.content[0].text)

            prompt_items = []
            texts = []

            for item_data in response_data.get("prompt_items", []):
                item = PromptItemResult(
                    text=item_data.get("text", ""),
                    prompt_item_type=PromptItemType(item_data.get("prompt_item_type")),
                    content_hash=item_data.get("content_hash", ""),
                    metadata=item_data.get("metadata"),
                )
                prompt_items.append(item)
                if item.text:
                    texts.append(item.text)

            combined_text = "\n\n".join(texts)

            logger.info(
                "Got prompt items v2",
                flow_stage="mcp_prompt_items_v2",
                flow_step_num=flow_step_num,
                db=db,
                items_count=len(prompt_items),
                item_types=[str(i.prompt_item_type.value) for i in prompt_items],
            )

            return PromptItemsV2Result(
                items=prompt_items,
                source=response_data.get("source", "db_meta"),
                version=response_data.get("version", "2.0.0"),
                combined_text=combined_text,
            )

        except Exception as e:
            logger.error(
                "Error calling prompt_items_v2",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e


async def db_meta_mcp_analyze_query(
    req: McpServerRequest,
    sql: str,
    flow_step_num,
    settings,
    logger,
    client: Optional[Client] = None,
):
    db = get_db_name(req)
    async with _use_client(client, settings) as _client:
        try:
            prompts = await _client.call_tool(
                "preflight_query",
                {
                    "req": {
                        "sql": sql,
                        "db": db,
                    }
                },
            )
            logger.debug(
                f"Preflight check for db={db}, "
                f"has_content={bool(prompts.content[0].text)}"
            )

        except Exception as e:
            logger.error(
                "Error reading MCP resource",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e

    return json.loads(prompts.content[0].text)


@dataclass
class PlanValidationError:
    """Single validation error from plan validation."""

    error_type: str  # "missing_table" or "missing_column"
    name: str  # The table or column name that's missing
    suggestion: Optional[str] = None  # Suggested alternative if found


@dataclass
class PlanValidationResult:
    """Result of plan validation against schema."""

    valid: bool
    errors: list[PlanValidationError]
    available_tables: Optional[list[str]] = None


async def validate_query_plan(
    req: McpServerRequest,
    tables: list[str],
    columns_referenced: list[str],
    flow_step_num: int,
    settings,
    logger,
    client: Optional[Client] = None,
) -> PlanValidationResult:
    """
    Validate that tables and columns from a query plan exist in the database schema.

    Args:
        req: MCP server request context
        tables: List of table names from the plan
        columns_referenced: List of column names referenced in the plan
        flow_step_num: Current flow step number for logging
        settings: Application settings
        logger: Logger instance
        client: Optional MCP client (for session reuse)

    Returns:
        PlanValidationResult with validation status, errors, and suggestions
    """
    db = get_db_name(req)

    async with _use_client(client, settings) as _client:
        try:
            result = await _client.call_tool(
                "validate_plan",
                {
                    "req": {
                        "tables": tables,
                        "columns_referenced": columns_referenced,
                        "db": db,
                    }
                },
            )

            # Parse the response
            response_data = json.loads(result.content[0].text)

            errors = [
                PlanValidationError(
                    error_type=e.get("error_type", ""),
                    name=e.get("name", ""),
                    suggestion=e.get("suggestion"),
                )
                for e in response_data.get("errors", [])
            ]

            validation_result = PlanValidationResult(
                valid=response_data.get("valid", False),
                errors=errors,
                available_tables=response_data.get("available_tables"),
            )

            logger.info(
                "Plan validation completed",
                flow_stage="plan_validation",
                flow_step_num=flow_step_num,
                valid=validation_result.valid,
                error_count=len(errors),
            )

            return validation_result

        except Exception as e:
            logger.error(
                "Error validating plan against schema",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e


@dataclass
class ColumnDetailsResult:
    """Detailed column information including statistics."""

    name: str
    type: str
    nullable: bool
    description: Optional[str] = None
    example: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    distinct_count: Optional[int] = None
    is_low_cardinality: Optional[bool] = None
    distinct_values: Optional[list[str]] = None
    min_value: Optional[str] = None
    max_value: Optional[str] = None


@dataclass
class ForeignKeyResult:
    """Foreign key relationship information."""

    columns: list[str]
    referred_table: str
    referred_columns: list[str]
    constraint_name: Optional[str] = None


@dataclass
class TableDetailsResult:
    """Detailed metadata for a single table."""

    table_name: str
    description: Optional[str] = None
    row_count_estimate: Optional[int] = None
    primary_key: Optional[list[str]] = None
    foreign_keys: list[ForeignKeyResult] = None
    columns: list[ColumnDetailsResult] = None


@dataclass
class GetTableDetailsResult:
    """Result from get_table_details MCP call."""

    tables: list[TableDetailsResult]
    content_hash: str
    metadata: dict[str, Any]


async def get_table_details_mcp(
    req: McpServerRequest,
    tables: list[str],
    flow_step_num: int,
    settings,
    logger,
    include: Optional[list[str]] = None,
    cardinality_threshold: int = 100,
    sample_size: int = 10000,
    client: Optional[Client] = None,
) -> GetTableDetailsResult:
    """
    Get detailed metadata for specific tables including relationships and stats.

    This function provides granular, on-demand schema exploration for selected
    tables. Use this after query planning to get rich metadata for SQL generation.

    Args:
        req: MCP server request context
        tables: List of fully qualified table names (e.g., "schema.table")
        flow_step_num: Current flow step number for logging
        settings: Application settings
        logger: Logger instance
        include: List of detail types to fetch. Options:
            - "relationships": PK-FK constraints
            - "cardinality": Distinct value counts
            - "low_cardinality_values": Actual values for low-card columns
            - "ranges": Min/max for numeric/date columns
            - "indexes": Index information
        cardinality_threshold: Max distinct values for "low cardinality"
        sample_size: Rows to sample for statistics
        client: Optional MCP client (for session reuse)

    Returns:
        GetTableDetailsResult with detailed table metadata and lineage info
    """
    db = get_db_name(req)

    # Default include options
    if include is None:
        include = ["relationships", "cardinality", "ranges"]

    async with _use_client(client, settings) as _client:
        try:
            result = await _client.call_tool(
                "get_table_details",
                {
                    "req": {
                        "db": db,
                        "tables": tables,
                        "include": include,
                        "cardinality_threshold": cardinality_threshold,
                        "sample_size": sample_size,
                    }
                },
            )

            # Parse the response
            response_data = json.loads(result.content[0].text)

            # Parse tables
            tables_result = []
            for table_data in response_data.get("tables", []):
                # Parse foreign keys
                fks = [
                    ForeignKeyResult(
                        columns=fk.get("columns", []),
                        referred_table=fk.get("referred_table", ""),
                        referred_columns=fk.get("referred_columns", []),
                        constraint_name=fk.get("constraint_name"),
                    )
                    for fk in table_data.get("foreign_keys", [])
                ]

                # Parse columns
                cols = [
                    ColumnDetailsResult(
                        name=col.get("name", ""),
                        type=col.get("type", ""),
                        nullable=col.get("nullable", True),
                        description=col.get("description"),
                        example=col.get("example"),
                        is_primary_key=col.get("is_primary_key", False),
                        is_foreign_key=col.get("is_foreign_key", False),
                        distinct_count=col.get("distinct_count"),
                        is_low_cardinality=col.get("is_low_cardinality"),
                        distinct_values=col.get("distinct_values"),
                        min_value=col.get("min_value"),
                        max_value=col.get("max_value"),
                    )
                    for col in table_data.get("columns", [])
                ]

                tables_result.append(
                    TableDetailsResult(
                        table_name=table_data.get("table_name", ""),
                        description=table_data.get("description"),
                        row_count_estimate=table_data.get("row_count_estimate"),
                        primary_key=table_data.get("primary_key"),
                        foreign_keys=fks,
                        columns=cols,
                    )
                )

            details_result = GetTableDetailsResult(
                tables=tables_result,
                content_hash=response_data.get("content_hash", ""),
                metadata=response_data.get("metadata", {}),
            )

            logger.info(
                "Got table details",
                flow_stage="table_details",
                flow_step_num=flow_step_num,
                tables_requested=tables,
                tables_found=len(tables_result),
                include=include,
            )

            return details_result

        except Exception as e:
            logger.error(
                "Error getting table details",
                flow_stage="error",
                flow_step_num=flow_step_num,
                tables=tables,
                error=str(e),
            )
            raise e


def format_table_details_for_prompt(result: GetTableDetailsResult) -> str:
    """
    Format table details into a human-readable string for LLM prompts.

    This renders the table details in a format suitable for inclusion
    in SQL generation prompts. Includes FULL column schema (names, types,
    descriptions) so the SQL generator knows the exact column names.

    Args:
        result: GetTableDetailsResult from get_table_details_mcp

    Returns:
        Formatted string with full schema and statistics
    """
    if not result.tables:
        return ""

    lines = ["## Table Schema Details\n"]

    for table in result.tables:
        lines.append(f"### {table.table_name}")

        if table.description:
            lines.append(f"_{table.description}_\n")

        if table.row_count_estimate:
            lines.append(f"- **Estimated rows**: {table.row_count_estimate:,}")

        if table.primary_key:
            lines.append(f"- **Primary key**: {', '.join(table.primary_key)}")

        if table.foreign_keys:
            lines.append("- **Foreign keys**:")
            for fk in table.foreign_keys:
                fk_cols = ", ".join(fk.columns)
                ref_cols = ", ".join(fk.referred_columns)
                lines.append(f"  - {fk_cols} → {fk.referred_table}({ref_cols})")

        # Full column schema - CRITICAL for SQL generation
        if table.columns:
            lines.append("\n**Columns:**")
            for col in table.columns:
                # Build column line: name (type) - description
                col_line = f"- **{col.name}** ({col.type})"
                if col.description:
                    col_line += f" - {col.description}"

                # Add stats inline if available
                stat_parts = []
                if col.is_low_cardinality and col.distinct_values:
                    values_preview = col.distinct_values[:5]
                    if len(col.distinct_values) > 5:
                        values_str = ", ".join(f"'{v}'" for v in values_preview)
                        values_str += ", ..."
                    else:
                        values_str = ", ".join(f"'{v}'" for v in values_preview)
                    stat_parts.append(f"values: [{values_str}]")
                elif col.min_value is not None and col.max_value is not None:
                    stat_parts.append(f"range: {col.min_value} to {col.max_value}")

                if stat_parts:
                    col_line += f" [{'; '.join(stat_parts)}]"

                lines.append(col_line)

        lines.append("")  # Empty line between tables

    return "\n".join(lines)


async def get_db_meta_database_overview(
    req: McpServerRequest,
    flow_step_num,
    settings,
    logger,
    client: Optional[Client] = None,
):
    """Get high-level database overview for discovery/welcome messages."""
    db = get_db_name(req)

    # Extract mode from request if present (format: "command|mode=value")
    mode = "help"  # default
    if "|mode=" in req.request:
        parts = req.request.split("|mode=")
        if len(parts) > 1:
            mode = parts[1]

    async with _use_client(client, settings) as _client:
        try:
            result = await _client.call_tool(
                "get_database_overview",
                {
                    "db": db,
                    "mode": mode,
                },
            )
            overview_text = result.content[0].text
            logger.info(
                "Got database overview",
                flow_stage="discovery_overview",
                flow_step_num=flow_step_num,
                mode=mode,
                overview_length=len(overview_text),
            )

        except Exception as e:
            logger.error(
                "Error getting database overview",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e

    return overview_text
