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

import asyncio
import csv
import hashlib
import io
import logging
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
from db_meta_v2.tasks.store import QueryStatus, get_query_store
from db_meta_v2.tools.shell import inject_protocol
from db_meta_v2.training.store import load_examples, load_instructions
from db_meta_v2.validation.explain import (
    CostTier,
    ExplainResult,
    explain_sql,
    validate_read_only,
)

logger = logging.getLogger(__name__)

# Threshold for async execution (rows estimated to scan)
# Queries above this go async to avoid timeout
ASYNC_ROW_THRESHOLD = 50_000

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

    # Log query start with truncated SQL
    sql_preview = sql[:200] + "..." if len(sql) > 200 else sql
    logger.info(f"[WH_QUERY] Starting execution: {sql_preview}")
    logger.debug(f"[WH_QUERY] Full SQL: {sql}")

    start_time = time.time()

    try:
        with engine.connect() as conn:
            logger.info("[WH_QUERY] Connection established, executing...")

            result = conn.execute(text(sql))
            columns = list(result.keys())

            logger.info(f"[WH_QUERY] Query executed, fetching rows (limit={limit})...")

            rows = []
            fetch_start = time.time()
            for i, row in enumerate(result):
                if limit and i >= limit:
                    logger.info(f"[WH_QUERY] Reached row limit ({limit}), stopping fetch")
                    break
                rows.append(dict(zip(columns, row)))

                # Log progress every 100 rows
                if (i + 1) % 100 == 0:
                    elapsed = time.time() - fetch_start
                    logger.debug(f"[WH_QUERY] Fetched {i + 1} rows ({elapsed:.1f}s)")

            fetch_duration_ms = (time.time() - fetch_start) * 1000
            total_duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[WH_QUERY] Complete: {len(rows)} rows, "
            f"fetch={fetch_duration_ms:.0f}ms, total={total_duration_ms:.0f}ms"
        )

        return {
            "data": rows,
            "columns": columns,
            "rows_returned": len(rows),
            "duration_ms": round(total_duration_ms, 2),
            "provider_id": settings.provider_id,
        }

    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        logger.error(f"[WH_QUERY] FAILED after {elapsed:.0f}ms: {type(e).__name__}: {e}")
        raise


async def _execute_query_background(query_id: str, sql: str) -> None:
    """Execute query in background and update query store.

    This runs in an asyncio task, allowing the MCP tool to return immediately
    while the query executes.
    """
    store = get_query_store()

    try:
        await store.update_status(query_id, QueryStatus.RUNNING)
        logger.info(f"Query {query_id}: Starting background execution")

        # Run the blocking query in a thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _execute_query, sql, 1000)

        await store.update_status(
            query_id,
            QueryStatus.COMPLETE,
            result=result,
            rows_returned=result["rows_returned"],
        )
        logger.info(f"Query {query_id}: Complete, {result['rows_returned']} rows")

    except Exception as e:
        logger.exception(f"Query {query_id}: Failed with error: {e}")
        await store.update_status(
            query_id,
            QueryStatus.ERROR,
            error=str(e),
        )


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
        # Sampling not supported - guide the agent to explore manually
        # Use session_id for per-session protocol injection
        session_id = getattr(ctx, "session_id", None)
        return inject_protocol(
            {
                "status": "error",
                "error": "MCP Sampling not available. Use manual exploration.",
                "guidance": {
                    "summary": "This tool requires MCP Sampling (not supported here).",
                    "what_to_do": [
                        "1. Read PROTOCOL.md: shell(command='cat PROTOCOL.md')",
                        "2. Explore catalogs: list_catalogs()",
                        "3. Explore schemas: list_schemas(catalog='...')",
                        "4. List tables: list_tables(catalog='...', schema='...')",
                        "5. Describe tables: describe_table(...)",
                        "6. Search examples: shell(command='grep -ri \"keyword\" examples/')",
                        "7. Generate SQL yourself based on what you learned",
                        "8. Execute: run_sql(sql='SELECT ...')",
                    ],
                    "important": (
                        "Do NOT skip steps. Start with list_catalogs() to understand "
                        "the database hierarchy before writing any SQL."
                    ),
                },
            },
            session_id=session_id,
        )

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
    query_id: str,
    confirmed: bool = False,
) -> dict:
    """Execute a previously validated SQL query.

    REQUIRES a query_id from validate_sql. This ensures:
    1. All queries are validated before execution
    2. User/agent has seen the query plan
    3. Query can't be modified between validation and execution

    BEFORE generating SQL:
        1. Search existing examples: shell(command='grep -ri "keyword" examples/')
        2. If found, adapt existing SQL. Don't reinvent.

    AFTER successful query:
        Save for future reuse: shell(command='cat >> examples/new.yaml << EOF...')
        See PROTOCOL.md for format.

    Args:
        query_id: Query ID from validate_sql (required)
        confirmed: Override for high-cost queries (cost_tier='reject')

    Returns:
        Dict with query results or error
    """
    from db_meta_v2.tasks.store import QueryStatus, get_query_store

    store = get_query_store()

    # Step 1: Get validated query
    query = await store.get(query_id)

    if query is None:
        return inject_protocol(
            {
                "status": "error",
                "error": "Query not found. Use validate_sql first to get a query_id.",
                "query_id": query_id,
                "guidance": {
                    "next_steps": [
                        "1. Call validate_sql(sql='YOUR SQL HERE')",
                        "2. Use the returned query_id with run_sql(query_id='...')",
                    ],
                },
            }
        )

    if query.status == QueryStatus.EXPIRED:
        return inject_protocol(
            {
                "status": "error",
                "error": "Query validation has expired. Please re-validate.",
                "query_id": query_id,
                "guidance": {
                    "next_steps": [
                        "Call validate_sql again with your SQL",
                        "Query IDs expire after 30 minutes",
                    ],
                },
            }
        )

    if not query.can_execute:
        return inject_protocol(
            {
                "status": "error",
                "error": f"Query cannot be executed. Status: {query.status.value}",
                "query_id": query_id,
            }
        )

    sql = query.sql

    # Step 2: Check cost tier
    if query.cost_tier == "reject" and not confirmed:
        return inject_protocol(
            {
                "status": "rejected",
                "cost_tier": "reject",
                "query_id": query_id,
                "sql": sql,
                "estimated_rows": query.estimated_rows,
                "estimated_cost": query.estimated_cost,
                "message": "Query is too expensive. Add filters or use confirmed=true.",
                "guidance": {
                    "next_steps": [
                        "Add WHERE clauses to narrow the query",
                        "Or use run_sql(query_id='...', confirmed=true) to force execution",
                    ],
                },
            }
        )

    # Step 3: Check if query should run async
    should_run_async = query.estimated_rows and query.estimated_rows > ASYNC_ROW_THRESHOLD

    if should_run_async:
        # Mark as pending and start background execution
        started = await store.start_execution(query_id)
        if not started:
            return inject_protocol(
                {
                    "status": "error",
                    "error": "Failed to start query execution",
                    "query_id": query_id,
                }
            )

        # Start background execution
        asyncio.create_task(_execute_query_background(query_id, sql))

        return inject_protocol(
            {
                "status": "submitted",
                "mode": "async",
                "query_id": query_id,
                "sql": sql,
                "estimated_rows": query.estimated_rows,
                "message": (
                    f"Query submitted for background execution. "
                    f"Estimated ~{query.estimated_rows:,} rows to scan. "
                    f"Use get_result('{query_id}') to check status."
                ),
                "poll_interval_seconds": 10,
                "guidance": {
                    "next_steps": [
                        f"Poll status with: get_result('{query_id}')",
                        "Check every 10-30 seconds until status is 'complete'",
                    ],
                },
            }
        )

    # Step 4: Execute synchronously (fast queries)
    try:
        # Mark as running
        await store.update_status(query_id, QueryStatus.RUNNING)

        result = _execute_query(sql)

        # Mark as complete
        await store.update_status(
            query_id,
            QueryStatus.COMPLETE,
            result=result,
            rows_returned=result["rows_returned"],
        )

        rows_returned = result["rows_returned"]
        is_large = rows_returned > 100

        return inject_protocol(
            {
                "status": "success",
                "query_id": query_id,
                "sql": sql,
                "data": result["data"],
                "columns": result["columns"],
                "rows_returned": rows_returned,
                "duration_ms": result["duration_ms"],
                "provider_id": result["provider_id"],
                "cost_tier": query.cost_tier,
                "presentation_hints": {
                    "downloadable": True,
                    "suggested_filename": f"query_{query_id[:8]}_{datetime.now():%Y%m%d_%H%M%S}",
                    "suggested_formats": ["csv", "xlsx"],
                    "large_result": is_large,
                    "display_recommendation": "export" if is_large else "table",
                },
                "guidance": {
                    "summary": f"Query returned {rows_returned} rows.",
                    "next_steps": (
                        ["Export results to CSV for the user"]
                        if is_large
                        else ["Present data in a table", "Summarize key insights"]
                    ),
                },
            }
        )

    except Exception as e:
        await store.update_status(query_id, QueryStatus.ERROR, error=str(e))
        return inject_protocol(
            {
                "status": "error",
                "error": f"Execution failed: {e}",
                "query_id": query_id,
                "sql": sql,
            }
        )


async def _validate_sql(sql: str) -> dict:
    """Validate SQL and register it for execution.

    REQUIRED before run_sql - validates the query and returns a query_id
    that must be passed to run_sql for execution.

    This ensures:
    1. All queries are validated before execution
    2. User/agent sees the query plan before committing
    3. Queries can't be modified between validation and execution

    Args:
        sql: SQL query to validate

    Returns:
        Dict with validation results and query_id (if valid)
    """
    from db_meta_v2.tasks.store import get_query_store

    # Check read-only
    is_read_only, error = validate_read_only(sql)
    if not is_read_only:
        return inject_protocol(
            {
                "valid": False,
                "error": error,
                "sql": sql,
                "query_id": None,
            }
        )

    # Run EXPLAIN
    explain_result = explain_sql(sql)

    if not explain_result.valid:
        return inject_protocol(
            {
                "valid": False,
                "error": explain_result.error,
                "sql": sql,
                "query_id": None,
            }
        )

    # Register validated query
    store = get_query_store()
    query = await store.register_validated(
        sql=sql,
        estimated_rows=explain_result.estimated_rows,
        estimated_cost=explain_result.estimated_cost,
        cost_tier=explain_result.cost_tier.value,
        explanation=explain_result.explanation[:5] if explain_result.explanation else [],
    )

    return inject_protocol(
        {
            "valid": True,
            "query_id": query.query_id,
            "sql": sql,
            "cost_tier": explain_result.cost_tier.value,
            "tier_reason": explain_result.tier_reason,
            "estimated_rows": explain_result.estimated_rows,
            "estimated_cost": explain_result.estimated_cost,
            "estimated_size_gb": explain_result.estimated_size_gb,
            "explanation": query.explanation,
            "message": (
                f"Query validated successfully. "
                f"Use run_sql(query_id='{query.query_id}') to execute. "
                f"Query ID expires in 30 minutes."
            ),
            "guidance": {
                "next_steps": [
                    f"Execute with: run_sql(query_id='{query.query_id}')",
                    "Review the cost_tier and estimated_rows before executing",
                    "If cost_tier is 'confirm' or 'reject', consider adding filters",
                ],
            },
        }
    )


async def _get_result(query_id: str) -> dict:
    """Get status and results for a query.

    Use this to poll for results after run_sql returns status='submitted'.
    Call repeatedly until status is 'complete' or 'error'.

    Args:
        query_id: Query ID from validate_sql or run_sql

    Returns:
        Dict with query status and results (when complete)
    """
    store = get_query_store()
    query = await store.get(query_id)

    if query is None:
        return inject_protocol(
            {
                "status": "not_found",
                "query_id": query_id,
                "message": "Query not found. It may have expired or the ID is invalid.",
            }
        )

    if query.status == QueryStatus.VALIDATED:
        return inject_protocol(
            {
                "status": "validated",
                "query_id": query_id,
                "sql": query.sql,
                "estimated_rows": query.estimated_rows,
                "cost_tier": query.cost_tier,
                "message": "Query is validated but not yet executed.",
                "guidance": {"next_steps": [f"Execute with: run_sql(query_id='{query_id}')"]},
            }
        )

    if query.status == QueryStatus.PENDING:
        return inject_protocol(
            {
                "status": "pending",
                "query_id": query_id,
                "elapsed_seconds": round(query.elapsed_seconds, 1),
                "message": "Query is queued and will start shortly.",
                "guidance": {"next_steps": [f"Poll again in 5 seconds: get_result('{query_id}')"]},
            }
        )

    if query.status == QueryStatus.RUNNING:
        return inject_protocol(
            {
                "status": "running",
                "query_id": query_id,
                "elapsed_seconds": round(query.elapsed_seconds, 1),
                "running_seconds": round(query.running_seconds, 1)
                if query.running_seconds
                else None,
                "message": f"Query is executing ({query.elapsed_seconds:.0f}s elapsed).",
                "guidance": {
                    "next_steps": [
                        f"Poll again in 10-30 seconds: get_result('{query_id}')",
                        "Tell the user the query is still running",
                    ]
                },
            }
        )

    if query.status == QueryStatus.ERROR:
        return inject_protocol(
            {
                "status": "error",
                "query_id": query_id,
                "elapsed_seconds": round(query.elapsed_seconds, 1),
                "error": query.error,
                "sql": query.sql,
                "message": f"Query failed: {query.error}",
            }
        )

    if query.status == QueryStatus.EXPIRED:
        return inject_protocol(
            {
                "status": "expired",
                "query_id": query_id,
                "message": "Query has expired. Please re-validate with validate_sql.",
            }
        )

    if query.status == QueryStatus.COMPLETE:
        result = query.result or {}
        rows_returned = result.get("rows_returned", 0)
        is_large = rows_returned > 100

        return inject_protocol(
            {
                "status": "complete",
                "query_id": query_id,
                "elapsed_seconds": round(query.elapsed_seconds, 1),
                "sql": query.sql,
                "data": result.get("data", []),
                "columns": result.get("columns", []),
                "rows_returned": rows_returned,
                "duration_ms": result.get("duration_ms"),
                "provider_id": result.get("provider_id"),
                "presentation_hints": {
                    "downloadable": True,
                    "large_result": is_large,
                    "display_recommendation": "export" if is_large else "table",
                },
                "guidance": {
                    "summary": f"Query completed successfully. {rows_returned} rows returned.",
                    "next_steps": (
                        ["Export results to CSV for the user", "Offer to refine the query"]
                        if is_large
                        else ["Present data in a table", "Summarize key insights"]
                    ),
                },
            }
        )

    # Fallback for unknown status
    return inject_protocol(
        {
            "status": query.status.value,
            "query_id": query_id,
            "message": f"Query in unexpected state: {query.status.value}",
        }
    )


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
