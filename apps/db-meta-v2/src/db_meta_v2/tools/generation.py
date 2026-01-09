"""SQL generation MCP tools - get_data, run_sql, get_result.

These are the three main entry points per v2 architecture:
- get_data(intent) - Natural language -> Plan -> SQL -> Result
- run_sql(sql) - Direct SQL with validation
- get_result(query_uuid) - Fetch cached/stored query result

Uses PydanticAI with MCPSamplingModel for LLM calls through the MCP client,
and MCP Elicitation for user confirmations.

Gracefully degrades when sampling/elicitation aren't supported:
- No sampling: Returns context for client to generate SQL
- No elicitation: Auto-approves or returns confirmation_required status
"""

import csv
import hashlib
import io
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.mcp_sampling import MCPSamplingModel
from sg_models import QueryPlan
from sqlalchemy import text

from db_meta_v2.config import get_settings
from db_meta_v2.db.connection import get_engine
from db_meta_v2.onboarding.schema_store import load_schema_descriptions
from db_meta_v2.training.store import load_examples, load_instructions
from db_meta_v2.validation.explain import (
    CostTier,
    ExplainResult,
    explain_sql,
    validate_read_only,
)

# =============================================================================
# Elicitation Models
# =============================================================================


@dataclass
class PlanApproval:
    """User response for plan approval."""

    approved: bool
    notes: str = ""


@dataclass
class ExecutionConfirmation:
    """User response for query execution confirmation."""

    confirmed: bool


# =============================================================================
# PydanticAI Agents
# =============================================================================


# Agent for generating query plans
planner_agent = Agent(
    system_prompt="""You are a SQL query planner. Given a user's natural language intent
and database schema, create a structured query plan.

Your plan should identify:
1. Which tables are needed
2. How tables should be joined
3. What filters to apply
4. Any aggregations or groupings
5. Sort order and limits

Be specific about column names and table relationships.
Only use tables and columns that exist in the provided schema.
""",
    output_type=QueryPlan,
)


class SQLGenerationResult(BaseModel):
    """Result of SQL generation."""

    sql: str = Field(..., description="The generated SQL query")
    explanation: str = Field(..., description="Brief explanation of the query")


# Agent for generating SQL from a plan
sql_generator_agent = Agent(
    system_prompt="""You are a SQL generator. Given a query plan and database schema,
generate the correct SQL query.

Follow the plan exactly. Use proper SQL syntax for the specified dialect.
Include appropriate JOINs, WHERE clauses, GROUP BY, ORDER BY as specified.
Always include a LIMIT clause if not specified (default to 100).
""",
    output_type=SQLGenerationResult,
)


# =============================================================================
# Context Building
# =============================================================================


def _build_schema_context(provider_id: str, tables_hint: list[str] | None = None) -> str:
    """Build schema context string for LLM prompts."""
    schema = load_schema_descriptions(provider_id)
    if not schema:
        return ""

    lines = ["## Available Tables\n"]

    for table in schema.tables:
        if tables_hint and table.full_name not in tables_hint:
            continue

        desc = f" - {table.description}" if table.description else ""
        lines.append(f"### {table.full_name}{desc}\n")
        lines.append("Columns:")

        for col in table.columns:
            col_desc = f" -- {col.description}" if col.description else ""
            lines.append(f"  - {col.name}: {col.type or 'unknown'}{col_desc}")

        lines.append("")

    return "\n".join(lines)


def _build_examples_context(provider_id: str, limit: int = 5) -> str:
    """Build examples context for few-shot learning."""
    examples = load_examples(provider_id)
    if not examples.examples:
        return ""

    lines = ["## Query Examples\n"]

    for ex in examples.examples[:limit]:
        lines.append(f"Question: {ex.natural_language}")
        lines.append(f"SQL: {ex.sql}")
        lines.append("")

    return "\n".join(lines)


def _build_rules_context(provider_id: str) -> str:
    """Build business rules context."""
    instructions = load_instructions(provider_id)
    if not instructions.rules:
        return ""

    lines = ["## Business Rules\n"]
    for rule in instructions.rules:
        lines.append(f"- {rule}")

    return "\n".join(lines)


def _generate_query_uuid(sql: str) -> str:
    """Generate a deterministic UUID for a SQL query."""
    normalized = " ".join(sql.lower().split())
    hash_bytes = hashlib.sha256(normalized.encode()).digest()[:16]
    return str(uuid.UUID(bytes=hash_bytes))


def _execute_query(sql: str, limit: int | None = 1000) -> dict[str, Any]:
    """Execute a SQL query and return results."""
    engine = get_engine()
    settings = get_settings()

    start_time = time.time()

    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())

        rows = []
        for i, row in enumerate(result):
            if limit and i >= limit:
                break
            rows.append(dict(zip(columns, row)))

        duration_ms = (time.time() - start_time) * 1000

    return {
        "data": rows,
        "columns": columns,
        "rows_returned": len(rows),
        "duration_ms": round(duration_ms, 2),
        "provider_id": settings.provider_id,
    }


def _check_sampling_support(ctx: Context) -> bool:
    """Check if the MCP context supports sampling."""
    try:
        return ctx.session is not None and hasattr(ctx.session, "create_message")
    except Exception:
        return False


# =============================================================================
# MCP Tools
# =============================================================================


async def _get_data(
    ctx: Context,
    intent: str,
    tables_hint: list[str] | None = None,
) -> dict:
    """Generate and execute SQL from natural language intent.

    This is the main entry point for natural language queries.

    When MCP Sampling is supported (e.g., fm-app-v2):
    1. Generate query plan via MCP Sampling
    2. Elicit user approval for the plan
    3. Generate SQL via MCP Sampling
    4. Validate and execute

    When MCP Sampling is NOT supported (e.g., Claude Desktop):
    - Returns context for the client to generate SQL
    - Client should then call run_sql() with the generated SQL

    Args:
        ctx: MCP Context for sampling and elicitation
        intent: Natural language query description
        tables_hint: Optional tables to focus on

    Returns:
        Dict with query results, or context for client-side generation
    """
    settings = get_settings()
    provider_id = settings.provider_id

    # Check if schema is available
    schema = load_schema_descriptions(provider_id)
    if not schema:
        return {
            "status": "error",
            "error": "No schema descriptions found. Complete onboarding first.",
            "phase": "schema_required",
        }

    # Build context
    schema_context = _build_schema_context(provider_id, tables_hint)
    examples_context = _build_examples_context(provider_id)
    rules_context = _build_rules_context(provider_id)

    full_context = f"""
User Intent: {intent}

Database Dialect: {schema.dialect or "unknown"}

{schema_context}

{examples_context}

{rules_context}
"""

    # ==========================================================================
    # Try MCP Sampling for plan generation
    # ==========================================================================
    plan: QueryPlan | None = None

    try:
        plan_result = await planner_agent.run(
            full_context,
            model=MCPSamplingModel(session=ctx.session),
        )
        plan = plan_result.output
        plan.intent = intent
    except Exception:
        # Sampling not supported - return context for client to generate SQL
        return {
            "status": "ready_for_generation",
            "mode": "client_generation",
            "intent": intent,
            "dialect": schema.dialect,
            "context": {
                "schema": schema_context,
                "examples": examples_context,
                "rules": rules_context,
                "tables_available": len(schema.tables),
            },
            "instructions": """Generate SQL for the user's intent using the schema above.

Steps:
1. Identify the tables needed based on the intent
2. Determine JOIN conditions if multiple tables
3. Add appropriate WHERE filters
4. Include GROUP BY for aggregations
5. Add ORDER BY and LIMIT

IMPORTANT: After generating SQL, you MUST call run_sql(sql) to execute it.
Do NOT just show the SQL - the user wants DATA, not SQL code.

Important:
- Only use tables and columns from the schema
- Follow any business rules provided
- Default LIMIT to 100 if not specified""",
            "guidance": {
                "summary": "Generate SQL and execute it to return data.",
                "next_steps": [
                    "Generate SQL based on schema and intent",
                    "Call run_sql(sql) to execute and get results",
                    "Show the data to the user",
                ],
                "important": (
                    "The user asked for DATA, not SQL. After generating SQL, "
                    "you MUST call run_sql() to execute it and return the actual data."
                ),
            },
        }

    # ==========================================================================
    # Try elicitation for plan approval
    # ==========================================================================
    try:
        approval_result = await ctx.elicit(
            message=f"Query Plan:\n\n{plan.summary()}\n\nApprove this plan?",
            response_type=PlanApproval,
        )

        if approval_result.action != "accept" or not approval_result.data.approved:
            return {
                "status": "cancelled",
                "message": "Plan not approved by user",
                "plan": plan.model_dump(),
            }

        if approval_result.data.notes:
            plan.approval_notes = approval_result.data.notes

        plan.approved = True

    except Exception:
        # Elicitation not supported - auto-approve
        plan.approved = True
        plan.approval_notes = "Auto-approved (elicitation not available)"

    # ==========================================================================
    # Generate SQL via MCP Sampling
    # ==========================================================================
    sql_prompt = f"""
Approved Query Plan:
{plan.summary()}

Database Dialect: {schema.dialect or "standard SQL"}

{schema_context}

Generate the SQL query that implements this plan.
"""

    try:
        sql_result = await sql_generator_agent.run(
            sql_prompt,
            model=MCPSamplingModel(session=ctx.session),
        )
        generated_sql = sql_result.output.sql
    except Exception as e:
        # This shouldn't happen if plan generation worked, but handle it
        return {
            "status": "error",
            "error": f"SQL generation failed: {e}",
            "phase": "sql_generation",
            "plan": plan.model_dump(),
        }

    # ==========================================================================
    # Validate SQL
    # ==========================================================================
    is_read_only, error = validate_read_only(generated_sql)
    if not is_read_only:
        return {
            "status": "rejected",
            "error": error,
            "sql": generated_sql,
            "plan": plan.model_dump(),
        }

    explain_result: ExplainResult = explain_sql(generated_sql)

    if not explain_result.valid:
        return {
            "status": "invalid",
            "error": explain_result.error,
            "sql": generated_sql,
            "plan": plan.model_dump(),
        }

    # ==========================================================================
    # Cost tier handling
    # ==========================================================================
    if explain_result.cost_tier == CostTier.REJECT:
        return {
            "status": "rejected",
            "cost_tier": "reject",
            "reason": explain_result.tier_reason,
            "estimated_rows": explain_result.estimated_rows,
            "sql": generated_sql,
            "plan": plan.model_dump(),
            "suggestion": "Narrow your query with filters or a smaller date range.",
        }

    if explain_result.cost_tier == CostTier.CONFIRM:
        # Try elicitation for execution confirmation
        try:
            confirm_result = await ctx.elicit(
                message=(
                    f"Query Execution Confirmation\n\n"
                    f"Reason: {explain_result.tier_reason}\n"
                    f"Estimated rows: {explain_result.estimated_rows:,}\n\n"
                    f"SQL:\n{generated_sql}\n\n"
                    f"Execute this query?"
                ),
                response_type=ExecutionConfirmation,
            )

            if confirm_result.action != "accept" or not confirm_result.data.confirmed:
                return {
                    "status": "cancelled",
                    "message": "Query execution not confirmed",
                    "cost_tier": "confirm",
                    "sql": generated_sql,
                    "plan": plan.model_dump(),
                }

        except Exception:
            # Elicitation not supported - return for manual confirmation
            return {
                "status": "confirm_required",
                "cost_tier": "confirm",
                "reason": explain_result.tier_reason,
                "estimated_rows": explain_result.estimated_rows,
                "sql": generated_sql,
                "plan": plan.model_dump(),
                "message": "Use run_sql(sql, confirmed=true) to proceed.",
            }

    # ==========================================================================
    # Execute
    # ==========================================================================
    try:
        query_uuid = _generate_query_uuid(generated_sql)
        result = _execute_query(generated_sql)

        return {
            "status": "success",
            "query_uuid": query_uuid,
            "sql": generated_sql,
            "data": result["data"],
            "columns": result["columns"],
            "rows_returned": result["rows_returned"],
            "duration_ms": result["duration_ms"],
            "provider_id": result["provider_id"],
            "cost_tier": explain_result.cost_tier.value,
            "plan": plan.model_dump(),
        }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Execution failed: {e}",
            "sql": generated_sql,
            "plan": plan.model_dump(),
        }


async def _run_sql(
    ctx: Context,
    sql: str,
    skip_validation: bool = False,
    confirmed: bool = False,
) -> dict:
    """Validate and execute a SQL query.

    This is the direct SQL entry point. It:
    1. Validates SQL is read-only
    2. Runs EXPLAIN to check cost
    3. Elicits confirmation if CONFIRM tier (unless already confirmed)
    4. Executes and returns results

    Args:
        ctx: MCP Context for elicitation
        sql: SQL query to execute
        skip_validation: Skip EXPLAIN validation (not recommended)
        confirmed: User has already confirmed execution of high-cost query

    Returns:
        Dict with validation result and/or query results
    """
    # Step 1: Validate read-only
    is_read_only, error = validate_read_only(sql)
    if not is_read_only:
        return {
            "status": "rejected",
            "error": error,
            "sql": sql,
        }

    # Step 2: EXPLAIN validation
    explain_result: ExplainResult | None = None
    if not skip_validation:
        explain_result = explain_sql(sql)

        if not explain_result.valid:
            return {
                "status": "invalid",
                "error": explain_result.error,
                "sql": sql,
            }

        # Step 3: Cost tier check
        if explain_result.cost_tier == CostTier.REJECT:
            if not confirmed:
                return {
                    "status": "rejected",
                    "cost_tier": "reject",
                    "reason": explain_result.tier_reason,
                    "estimated_rows": explain_result.estimated_rows,
                    "estimated_cost": explain_result.estimated_cost,
                    "sql": sql,
                    "suggestion": "Narrow your query with filters or a smaller date range.",
                    "override": "Use confirmed=true to execute anyway (may be slow/expensive).",
                }
            # User confirmed - proceed with warning logged

        if explain_result.cost_tier == CostTier.CONFIRM and not confirmed:
            # Try to elicit confirmation
            try:
                confirm_result = await ctx.elicit(
                    message=(
                        f"Query Execution Confirmation\n\n"
                        f"Reason: {explain_result.tier_reason}\n"
                        f"Estimated rows: {explain_result.estimated_rows:,}\n\n"
                        f"SQL:\n{sql}\n\n"
                        f"Execute this query?"
                    ),
                    response_type=ExecutionConfirmation,
                )

                if confirm_result.action != "accept" or not confirm_result.data.confirmed:
                    return {
                        "status": "cancelled",
                        "message": "Query execution not confirmed",
                        "cost_tier": "confirm",
                        "sql": sql,
                    }

            except Exception:
                # Elicitation not supported
                return {
                    "status": "confirm_required",
                    "cost_tier": "confirm",
                    "reason": explain_result.tier_reason,
                    "estimated_rows": explain_result.estimated_rows,
                    "estimated_cost": explain_result.estimated_cost,
                    "estimated_size_gb": explain_result.estimated_size_gb,
                    "sql": sql,
                    "message": "Query requires confirmation. Use confirmed=true to proceed.",
                }

    # Step 4: Execute
    try:
        query_uuid = _generate_query_uuid(sql)
        result = _execute_query(sql)

        rows_returned = result["rows_returned"]
        is_large = rows_returned > 100

        return {
            "status": "success",
            "query_uuid": query_uuid,
            "sql": sql,
            "data": result["data"],
            "columns": result["columns"],
            "rows_returned": rows_returned,
            "duration_ms": result["duration_ms"],
            "provider_id": result["provider_id"],
            "cost_tier": (
                "auto"
                if skip_validation
                else (explain_result.cost_tier.value if explain_result else "unknown")
            ),
            "presentation_hints": {
                "downloadable": True,
                "suggested_filename": f"query_{query_uuid[:8]}_{datetime.now():%Y%m%d_%H%M%S}",
                "suggested_formats": ["csv", "xlsx"],
                "large_result": is_large,
                "display_recommendation": "export" if is_large else "table",
                "hint": (
                    f"Result has {rows_returned} rows. Consider exporting to CSV/Excel "
                    "for better viewing."
                    if is_large
                    else "Result is small enough to display as a table."
                ),
            },
            "guidance": {
                "summary": f"Query returned {rows_returned} rows.",
                "next_steps": (
                    [
                        "Export results using export_results(query_uuid, format='csv')",
                        "Create a downloadable file for the user",
                        "Offer to refine the query if needed",
                    ]
                    if is_large
                    else [
                        "Present the data in a clear table format",
                        "Offer to refine the query if needed",
                        "Suggest follow-up analyses",
                    ]
                ),
                "suggested_response": (
                    f"Result has {rows_returned} rows - too large for inline display. "
                    "Exporting to CSV for download..."
                    if is_large
                    else "Present the data above in a nice table format. "
                    "Summarize key insights from the results."
                ),
            },
        }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Execution failed: {e}",
            "sql": sql,
        }


async def _validate_sql(sql: str) -> dict:
    """Validate SQL without executing it.

    Use this to check if SQL is valid before execution.

    Args:
        sql: SQL query to validate

    Returns:
        Dict with validation results
    """
    # Check read-only
    is_read_only, error = validate_read_only(sql)
    if not is_read_only:
        return {
            "valid": False,
            "error": error,
            "sql": sql,
        }

    # Run EXPLAIN
    explain_result = explain_sql(sql)

    return {
        "valid": explain_result.valid,
        "error": explain_result.error,
        "sql": sql,
        "cost_tier": explain_result.cost_tier.value,
        "tier_reason": explain_result.tier_reason,
        "estimated_rows": explain_result.estimated_rows,
        "estimated_cost": explain_result.estimated_cost,
        "estimated_size_gb": explain_result.estimated_size_gb,
        "explanation": (explain_result.explanation[:5] if explain_result.explanation else []),
    }


async def _get_result(query_uuid: str) -> dict:
    """Get result for a previously executed query.

    This fetches results from cache or re-executes a stored query.

    Args:
        query_uuid: UUID of the query

    Returns:
        Dict with query results or error
    """
    # TODO: Implement query store and caching
    return {
        "status": "not_found",
        "query_uuid": query_uuid,
        "message": "Query store not yet implemented. Use run_sql to execute queries.",
    }


async def _export_results(
    ctx: Context,
    sql: str,
    format: str = "csv",
    filename: str | None = None,
) -> dict:
    """Export query results as CSV or other formats.

    Executes the query and returns the results formatted for export.
    The agent can use this to create downloadable files.

    Args:
        ctx: MCP Context
        sql: SQL query to execute and export
        format: Export format - 'csv' (default), 'json', or 'markdown'
        filename: Optional filename (without extension)

    Returns:
        Dict with formatted content and file metadata
    """
    # Validate read-only
    is_read_only, error = validate_read_only(sql)
    if not is_read_only:
        return {
            "status": "rejected",
            "error": error,
        }

    # Execute query
    try:
        result = _execute_query(sql, limit=10000)  # Higher limit for exports
    except Exception as e:
        return {
            "status": "error",
            "error": f"Query execution failed: {e}",
        }

    data = result["data"]
    columns = result["columns"]
    rows_returned = result["rows_returned"]

    # Generate filename if not provided
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not filename:
        query_hash = hashlib.sha256(sql.encode()).hexdigest()[:8]
        filename = f"export_{query_hash}_{timestamp}"

    # Format the content based on requested format
    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(data)
        content = output.getvalue()
        mime_type = "text/csv"
        extension = "csv"

    elif format == "json":
        import json

        content = json.dumps(data, indent=2, default=str)
        mime_type = "application/json"
        extension = "json"

    elif format == "markdown":
        # Create markdown table
        lines = []
        # Header
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
        # Rows
        for row in data:
            values = [str(row.get(col, "")) for col in columns]
            lines.append("| " + " | ".join(values) + " |")
        content = "\n".join(lines)
        mime_type = "text/markdown"
        extension = "md"

    else:
        return {
            "status": "error",
            "error": f"Unsupported format: {format}. Use 'csv', 'json', or 'markdown'.",
        }

    full_filename = f"{filename}.{extension}"

    return {
        "status": "success",
        "format": format,
        "filename": full_filename,
        "mime_type": mime_type,
        "content": content,
        "rows_exported": rows_returned,
        "columns": columns,
        "file_size_bytes": len(content.encode("utf-8")),
        "instructions": {
            "hint": (
                f"Export ready: {full_filename} ({rows_returned} rows). "
                "Save this content as a file and present to user for download."
            ),
            "for_chatgpt": (
                "Use create_file tool to write content to /mnt/user-data/outputs/, "
                "then use present_files to create download link."
            ),
            "for_claude": ("Create a downloadable artifact with this content."),
        },
    }


# =============================================================================
# Test Tools (can be removed in production)
# =============================================================================


@dataclass
class TestConfirmation:
    """Simple yes/no confirmation for testing."""

    confirmed: bool


async def _test_elicitation(ctx: Context, message: str = "Test message") -> dict:
    """Test if MCP elicitation is supported by the client.

    Args:
        ctx: MCP Context
        message: Message to show in elicitation prompt

    Returns:
        Dict with elicitation test result
    """
    try:
        result = await ctx.elicit(
            message=f"{message}\n\nDo you confirm?",
            response_type=TestConfirmation,
        )

        return {
            "status": "elicitation_supported",
            "action": result.action,
            "confirmed": result.data.confirmed if result.data else None,
            "message": "Elicitation works!",
        }

    except Exception as e:
        return {
            "status": "elicitation_not_supported",
            "error": str(e),
            "message": "Client does not support MCP elicitation.",
        }


async def _test_sampling(ctx: Context, prompt: str = "Say hello") -> dict:
    """Test if MCP sampling is supported by the client.

    Args:
        ctx: MCP Context
        prompt: Test prompt for the LLM

    Returns:
        Dict with sampling test result
    """
    try:
        # Simple agent just to test sampling works
        test_agent = Agent(
            system_prompt="You are a helpful assistant. Keep responses brief.",
        )

        result = await test_agent.run(
            prompt,
            model=MCPSamplingModel(session=ctx.session),
        )

        return {
            "status": "sampling_supported",
            "response": str(result.output),
            "message": "MCP Sampling works!",
        }

    except Exception as e:
        return {
            "status": "sampling_not_supported",
            "error": str(e),
            "message": "Client does not support MCP sampling.",
        }
