import json
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
    req: McpServerRequest, flow_step_num, settings, logger
):
    db = get_db_name(req)
    client = Client(f"""{settings.dbmeta}sse""")
    async with client:
        try:
            prompts = await client.call_tool(
                "prompt_items",
                {
                    "req": {
                        "user_request": req.request,
                        "db": db,
                    }
                },
            )
            logger.debug(
                f"Got prompts for db={db}, has_content={bool(prompts[0].text)}"
            )

        except Exception as e:
            logger.error(
                "Error reading MCP resource",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e

    return prompts[0].text


async def get_db_meta_mcp_prompt_items_v2(
    req: McpServerRequest,
    flow_step_num: int,
    settings,
    logger,
    items: Optional[list[str]] = None,
    schema_top_k: int = 10,
    examples_top_k: int = 5,
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

    Returns:
        PromptItemsV2Result with individual items and combined text
    """
    db = get_db_name(req)

    # Default items if not specified
    if items is None:
        items = ["DBStruct", "QueryExample", "Instruction", "SQLDialect", "DomainModel"]

    client = Client(f"""{settings.dbmeta}sse""")
    async with client:
        try:
            result = await client.call_tool(
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
            response_data = json.loads(result[0].text)

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
    req: McpServerRequest, sql: str, flow_step_num, settings, logger
):
    db = get_db_name(req)
    client = Client(f"""{settings.dbmeta}sse""")
    async with client:
        try:
            prompts = await client.call_tool(
                "preflight_query",
                {
                    "req": {
                        "sql": sql,
                        "db": db,
                    }
                },
            )
            logger.debug(
                f"Preflight check for db={db}, has_content={bool(prompts[0].text)}"
            )

        except Exception as e:
            logger.error(
                "Error reading MCP resource",
                flow_stage="error",
                flow_step_num=flow_step_num,
                error=str(e),
            )
            raise e

    return json.loads(prompts[0].text)


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

    Returns:
        PlanValidationResult with validation status, errors, and suggestions
    """
    db = get_db_name(req)
    client = Client(f"""{settings.dbmeta}sse""")

    async with client:
        try:
            result = await client.call_tool(
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
            response_data = json.loads(result[0].text)

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


async def get_db_meta_database_overview(
    req: McpServerRequest, flow_step_num, settings, logger
):
    """Get high-level database overview for discovery/welcome messages."""
    db = get_db_name(req)

    # Extract mode from request if present (format: "command|mode=value")
    mode = "help"  # default
    if "|mode=" in req.request:
        parts = req.request.split("|mode=")
        if len(parts) > 1:
            mode = parts[1]

    client = Client(f"""{settings.dbmeta}sse""")
    async with client:
        try:
            result = await client.call_tool(
                "get_database_overview",
                {
                    "db": db,
                    "mode": mode,
                },
            )
            overview_text = result[0].text
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
