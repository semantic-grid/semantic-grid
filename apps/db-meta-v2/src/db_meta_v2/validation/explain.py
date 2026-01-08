"""SQL validation using EXPLAIN for different database dialects."""

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from db_meta_v2.db.connection import DatabaseError, detect_dialect_from_url, get_engine


class CostTier(str, Enum):
    """Query cost tier determining execution behavior."""

    AUTO = "auto"  # Execute immediately
    CONFIRM = "confirm"  # Require user confirmation
    REJECT = "reject"  # Too expensive, reject


class ExplainResult(BaseModel):
    """Result of SQL EXPLAIN analysis."""

    valid: bool = Field(..., description="Whether the SQL is valid")
    error: str | None = Field(default=None, description="Error message if invalid")

    # Execution plan
    explanation: list[dict[str, Any]] = Field(
        default_factory=list, description="Raw EXPLAIN output"
    )

    # Cost estimates
    estimated_rows: int | None = Field(default=None, description="Estimated rows")
    estimated_cost: float | None = Field(default=None, description="Estimated cost")
    estimated_size_gb: float | None = Field(
        default=None, description="Estimated output size in GB"
    )

    # Cost tier evaluation
    cost_tier: CostTier = Field(default=CostTier.AUTO, description="Execution tier")
    tier_reason: str | None = Field(default=None, description="Reason for cost tier assignment")


import os


def _get_cost_thresholds() -> dict[str, int | float]:
    """Get cost thresholds from environment or defaults."""
    return {
        "auto_max_rows": int(os.environ.get("COST_AUTO_MAX_ROWS", 100_000)),
        "auto_max_cost": float(os.environ.get("COST_AUTO_MAX_COST", 1000)),
        "confirm_max_rows": int(os.environ.get("COST_CONFIRM_MAX_ROWS", 100_000_000)),
        "confirm_max_cost": float(os.environ.get("COST_CONFIRM_MAX_COST", 1_000_000)),
        # Above confirm thresholds -> REJECT (unless allow_override is True)
    }


# For backwards compatibility
COST_THRESHOLDS = _get_cost_thresholds()


def get_explain_command(dialect: str) -> str:
    """Get the appropriate EXPLAIN command for a database dialect.

    Args:
        dialect: Database dialect name

    Returns:
        EXPLAIN command string
    """
    dialect = dialect.lower()

    if dialect == "clickhouse":
        return "EXPLAIN ESTIMATE"
    elif dialect in ("postgresql", "postgres"):
        return "EXPLAIN"
    elif dialect == "trino":
        return "EXPLAIN"
    elif dialect in ("mysql", "mariadb"):
        return "EXPLAIN"
    elif dialect == "sqlite":
        return "EXPLAIN QUERY PLAN"
    else:
        return "EXPLAIN"


def parse_postgresql_estimates(
    rows: list[dict[str, Any]],
) -> tuple[int | None, float | None, float | None]:
    """Parse PostgreSQL EXPLAIN output for estimates.

    Returns:
        (estimated_rows, estimated_cost, estimated_size_gb)
    """
    max_rows = None
    max_cost = None

    for row in rows:
        plan_text = row.get("QUERY PLAN", "") or str(list(row.values())[0])

        # Pattern: (cost=0.00..123.45 rows=1000 width=100)
        cost_pattern = r"cost=([\d.]+)\.\.([\d.]+)\s+rows=(\d+)"
        matches = re.findall(cost_pattern, plan_text)

        for match in matches:
            _, total_cost, rows_est = match
            cost = float(total_cost)
            rows_count = int(rows_est)

            if max_cost is None or cost > max_cost:
                max_cost = cost
            if max_rows is None or rows_count > max_rows:
                max_rows = rows_count

    # Rough size estimate: ~1KB per row
    size_gb = (max_rows * 1024) / (1024**3) if max_rows else None

    return max_rows, max_cost, size_gb


def parse_clickhouse_estimates(
    rows: list[dict[str, Any]],
) -> tuple[int | None, float | None, float | None]:
    """Parse ClickHouse EXPLAIN ESTIMATE output.

    Returns:
        (estimated_rows, estimated_cost, estimated_size_gb)
    """
    max_rows = None

    for row in rows:
        # EXPLAIN ESTIMATE returns structured data with 'rows' field
        if "rows" in row and isinstance(row.get("rows"), (int, float)):
            rows_count = int(row["rows"])
            if max_rows is None or rows_count > max_rows:
                max_rows = rows_count
            continue

        # Fallback: parse text output
        explanation_text = (
            row.get("explain")
            or row.get("plan")
            or row.get("EXPLAIN")
            or str(list(row.values())[0])
            if row
            else ""
        )

        if not explanation_text or not isinstance(explanation_text, str):
            continue

        rows_pattern = r"rows?:\s*([\d,]+)"
        matches = re.findall(rows_pattern, explanation_text, re.IGNORECASE)

        for rows_str in matches:
            rows_count = int(rows_str.replace(",", ""))
            if max_rows is None or rows_count > max_rows:
                max_rows = rows_count

    # Rough size estimate
    size_gb = (max_rows * 1024) / (1024**3) if max_rows else None

    return max_rows, None, size_gb  # ClickHouse doesn't have a cost metric


def parse_trino_estimates(
    rows: list[dict[str, Any]],
) -> tuple[int | None, float | None, float | None]:
    """Parse Trino EXPLAIN output for estimates.

    Returns:
        (estimated_rows, estimated_cost, estimated_size_gb)
    """
    max_rows = None
    max_size_gb = None

    for row in rows:
        query_plan = row.get("Query Plan", "")
        if not query_plan:
            continue

        # Pattern: Estimates: {rows: NUMBER (SIZE), ...}
        estimate_pattern = r"Estimates:\s*\{rows:\s*([\d,]+)\s*\(([\d.]+)([KMGT]?B)\)"
        matches = re.findall(estimate_pattern, query_plan)

        for match in matches:
            rows_str, size_str, size_unit = match

            rows_count = int(rows_str.replace(",", ""))
            if max_rows is None or rows_count > max_rows:
                max_rows = rows_count

            # Parse size to GB
            size = float(size_str)
            unit_multipliers = {
                "B": 1 / (1024**3),
                "KB": 1 / (1024**2),
                "MB": 1 / 1024,
                "GB": 1,
                "TB": 1024,
            }
            size_gb = size * unit_multipliers.get(size_unit, 1 / (1024**3))

            if max_size_gb is None or size_gb > max_size_gb:
                max_size_gb = size_gb

    return max_rows, None, max_size_gb


def evaluate_cost_tier(
    estimated_rows: int | None,
    estimated_cost: float | None,
    estimated_size_gb: float | None,
) -> tuple[CostTier, str]:
    """Evaluate the cost tier based on estimates.

    Args:
        estimated_rows: Estimated row count
        estimated_cost: Estimated query cost
        estimated_size_gb: Estimated output size in GB

    Returns:
        (CostTier, reason string)
    """
    # If we have no estimates, default to CONFIRM for safety
    if estimated_rows is None and estimated_cost is None:
        return CostTier.CONFIRM, "Unable to estimate query cost"

    # Check against thresholds
    if estimated_rows is not None:
        if estimated_rows > COST_THRESHOLDS["confirm_max_rows"]:
            max_rows = COST_THRESHOLDS["confirm_max_rows"]
            return (
                CostTier.REJECT,
                f"Query would scan ~{estimated_rows:,} rows (max: {max_rows:,})",
            )
        elif estimated_rows > COST_THRESHOLDS["auto_max_rows"]:
            return CostTier.CONFIRM, f"Query scans ~{estimated_rows:,} rows"

    if estimated_cost is not None:
        if estimated_cost > COST_THRESHOLDS["confirm_max_cost"]:
            return CostTier.REJECT, f"Query cost {estimated_cost:,.0f} exceeds limit"
        elif estimated_cost > COST_THRESHOLDS["auto_max_cost"]:
            return CostTier.CONFIRM, f"Query cost ~{estimated_cost:,.0f}"

    # Size-based check (reject if output would be > 1GB)
    if estimated_size_gb is not None and estimated_size_gb > 1.0:
        return CostTier.CONFIRM, f"Query output ~{estimated_size_gb:.2f}GB"

    return CostTier.AUTO, "Query within auto-execution limits"


def explain_sql(sql: str, database_url: str | None = None) -> ExplainResult:
    """Validate SQL using EXPLAIN and evaluate cost tier.

    Args:
        sql: SQL query to validate
        database_url: Optional database URL

    Returns:
        ExplainResult with validation status and cost tier
    """
    try:
        engine = get_engine(database_url)
        dialect = detect_dialect_from_url(str(engine.url))
        explain_cmd = get_explain_command(dialect)

        with engine.connect() as conn:
            result = conn.execute(text(f"{explain_cmd} {sql}"))
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

        # Parse estimates based on dialect
        if dialect in ("postgresql", "postgres"):
            est_rows, est_cost, est_size = parse_postgresql_estimates(rows)
        elif dialect == "clickhouse":
            est_rows, est_cost, est_size = parse_clickhouse_estimates(rows)
        elif dialect == "trino":
            est_rows, est_cost, est_size = parse_trino_estimates(rows)
        else:
            est_rows, est_cost, est_size = None, None, None

        # Evaluate cost tier
        cost_tier, tier_reason = evaluate_cost_tier(est_rows, est_cost, est_size)

        return ExplainResult(
            valid=True,
            explanation=rows,
            estimated_rows=est_rows,
            estimated_cost=est_cost,
            estimated_size_gb=est_size,
            cost_tier=cost_tier,
            tier_reason=tier_reason,
        )

    except DatabaseError as e:
        return ExplainResult(
            valid=False,
            error=str(e),
            cost_tier=CostTier.REJECT,
            tier_reason="Database error",
        )
    except Exception as e:
        error_msg = str(e)
        # Extract useful error message from SQL exceptions
        if "syntax" in error_msg.lower() or "parse" in error_msg.lower():
            return ExplainResult(
                valid=False,
                error=f"SQL syntax error: {error_msg}",
                cost_tier=CostTier.REJECT,
                tier_reason="Invalid SQL",
            )
        return ExplainResult(
            valid=False,
            error=f"Validation error: {error_msg}",
            cost_tier=CostTier.REJECT,
            tier_reason="Validation failed",
        )


def validate_read_only(sql: str) -> tuple[bool, str | None]:
    """Validate that SQL is read-only (SELECT only).

    Args:
        sql: SQL query to check

    Returns:
        (is_valid, error_message)
    """
    # Normalize and check for non-SELECT statements
    sql_upper = sql.strip().upper()

    # List of disallowed statement types
    disallowed = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "CREATE",
        "ALTER",
        "TRUNCATE",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "MERGE",
        "UPSERT",
    ]

    for keyword in disallowed:
        # Check if statement starts with disallowed keyword
        if sql_upper.startswith(keyword):
            return False, f"Statement type '{keyword}' is not allowed (read-only mode)"

        # Also check for these within CTEs or subqueries
        # Pattern: keyword followed by whitespace or opening paren
        if re.search(rf"\b{keyword}\s", sql_upper):
            # Allow SELECT ... INTO for temp tables in some contexts
            if keyword == "INTO" and "SELECT" in sql_upper:
                continue
            return False, f"Statement contains '{keyword}' which is not allowed"

    # Must start with SELECT, WITH (CTE), or EXPLAIN
    if not any(
        sql_upper.startswith(kw) for kw in ["SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE"]
    ):
        return False, "Query must be a SELECT statement"

    return True, None
