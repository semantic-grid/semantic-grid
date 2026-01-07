"""SQL generation MCP tools - get_data, run_sql, get_result.

These are the three main entry points per v2 architecture:
- get_data(intent) - Natural language -> Plan -> SQL -> Result
- run_sql(sql) - Direct SQL with validation
- get_result(query_uuid) - Fetch cached/stored query result
"""

import hashlib
import time
import uuid
from typing import Any

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


def _build_schema_context(provider_id: str, tables_hint: list[str] | None = None) -> str:
    """Build schema context string for LLM prompts.

    Args:
        provider_id: Provider identifier
        tables_hint: Optional list of tables to focus on

    Returns:
        Schema context as formatted string
    """
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
    """Build examples context for few-shot learning.

    Args:
        provider_id: Provider identifier
        limit: Max examples to include

    Returns:
        Examples context as formatted string
    """
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
    """Build business rules context.

    Args:
        provider_id: Provider identifier

    Returns:
        Rules context as formatted string
    """
    instructions = load_instructions(provider_id)
    if not instructions.rules:
        return ""

    lines = ["## Business Rules\n"]
    for rule in instructions.rules:
        lines.append(f"- {rule}")

    return "\n".join(lines)


def _generate_query_uuid(sql: str) -> str:
    """Generate a deterministic UUID for a SQL query.

    This normalizes the SQL and generates a hash for deduplication.

    Args:
        sql: SQL query

    Returns:
        UUID string
    """
    # Normalize: lowercase, collapse whitespace
    normalized = " ".join(sql.lower().split())
    hash_bytes = hashlib.sha256(normalized.encode()).digest()[:16]
    return str(uuid.UUID(bytes=hash_bytes))


def _execute_query(
    sql: str,
    limit: int | None = 1000,
) -> dict[str, Any]:
    """Execute a SQL query and return results.

    Args:
        sql: SQL to execute
        limit: Row limit (applied if not in SQL)

    Returns:
        Dict with data, columns, metadata
    """
    engine = get_engine()
    settings = get_settings()

    start_time = time.time()

    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())

        # Fetch rows
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


async def _get_data(
    intent: str,
    tables_hint: list[str] | None = None,
    auto_execute: bool = False,
) -> dict:
    """Generate SQL from natural language intent.

    This is the main entry point for natural language queries. The flow is:
    1. Build context from schema, examples, rules
    2. Return context for LLM to generate plan
    3. (After plan approval) Generate SQL
    4. Validate SQL via EXPLAIN
    5. Execute if cost tier allows

    Note: In production with MCP sampling, steps 2-3 would use the client's LLM.
    For now, this returns context for the assistant to generate SQL.

    Args:
        intent: Natural language query description
        tables_hint: Optional tables to focus on
        auto_execute: If True, execute AUTO tier queries immediately

    Returns:
        Dict with generation context or results
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

    # Build context for SQL generation
    schema_context = _build_schema_context(provider_id, tables_hint)
    examples_context = _build_examples_context(provider_id)
    rules_context = _build_rules_context(provider_id)

    # Return generation context
    # In production, this would trigger MCP sampling to generate the plan/SQL
    return {
        "status": "ready_for_generation",
        "intent": intent,
        "dialect": schema.dialect,
        "context": {
            "schema": schema_context,
            "examples": examples_context,
            "rules": rules_context,
            "tables_available": len(schema.tables),
        },
        "instructions": """Generate SQL for the user's intent using the schema above.

Follow these steps:
1. First, create a query plan identifying:
   - Tables needed
   - Join conditions
   - Filters to apply
   - Aggregations/groupings
   - Sort order

2. After plan is confirmed, generate the SQL.

3. Use run_sql to validate and execute the query.

Important:
- Only use tables and columns from the schema
- Follow any business rules provided
- Use appropriate JOINs based on relationships
- Apply reasonable LIMIT if not specified""",
    }


async def _run_sql(
    sql: str,
    skip_validation: bool = False,
    force_execute: bool = False,
) -> dict:
    """Validate and execute a SQL query.

    This is the direct SQL entry point. It:
    1. Validates SQL is read-only
    2. Runs EXPLAIN to check cost
    3. Executes based on cost tier

    Args:
        sql: SQL query to execute
        skip_validation: Skip EXPLAIN validation (not recommended)
        force_execute: Execute even if CONFIRM tier (use with caution)

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
    if not skip_validation:
        explain_result: ExplainResult = explain_sql(sql)

        if not explain_result.valid:
            return {
                "status": "invalid",
                "error": explain_result.error,
                "sql": sql,
            }

        # Step 3: Cost tier check
        if explain_result.cost_tier == CostTier.REJECT:
            return {
                "status": "rejected",
                "cost_tier": "reject",
                "reason": explain_result.tier_reason,
                "estimated_rows": explain_result.estimated_rows,
                "estimated_cost": explain_result.estimated_cost,
                "sql": sql,
                "suggestion": "Narrow your query with filters or a smaller date range.",
            }

        if explain_result.cost_tier == CostTier.CONFIRM and not force_execute:
            return {
                "status": "confirm_required",
                "cost_tier": "confirm",
                "reason": explain_result.tier_reason,
                "estimated_rows": explain_result.estimated_rows,
                "estimated_cost": explain_result.estimated_cost,
                "estimated_size_gb": explain_result.estimated_size_gb,
                "sql": sql,
                "message": "Query requires confirmation. Use force_execute=True to proceed.",
            }

    # Step 4: Execute
    try:
        query_uuid = _generate_query_uuid(sql)
        result = _execute_query(sql)

        return {
            "status": "success",
            "query_uuid": query_uuid,
            "sql": sql,
            "data": result["data"],
            "columns": result["columns"],
            "rows_returned": result["rows_returned"],
            "duration_ms": result["duration_ms"],
            "provider_id": result["provider_id"],
            "cost_tier": "auto" if skip_validation else explain_result.cost_tier.value,
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
        "explanation": explain_result.explanation[:5] if explain_result.explanation else [],
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
    # For now, return not found
    return {
        "status": "not_found",
        "query_uuid": query_uuid,
        "message": "Query store not yet implemented. Use run_sql to execute queries.",
    }
