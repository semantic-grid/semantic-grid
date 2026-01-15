"""SQL validation using EXPLAIN for different database dialects."""

import os
import re
from enum import Enum
from typing import Any

from opentelemetry import trace
from pydantic import BaseModel, Field
from sqlalchemy import text

from db_meta_v2.db.connection import DatabaseError, detect_dialect_from_url, get_engine

tracer = trace.get_tracer("dbmeta.validation")


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


def parse_mysql_estimates(
    rows: list[dict[str, Any]],
) -> tuple[int | None, float | None, float | None]:
    """Parse MySQL/MariaDB EXPLAIN output for estimates.

    MySQL EXPLAIN returns structured rows with columns like:
    - id, select_type, table, type, possible_keys, key, key_len, ref, rows, Extra
    MySQL 8.0+ EXPLAIN FORMAT=TREE or EXPLAIN ANALYZE provides more detail.

    Returns:
        (estimated_rows, estimated_cost, estimated_size_gb)
    """
    max_rows = None
    total_rows = 0

    for row in rows:
        # Standard EXPLAIN output has 'rows' column with estimated row count
        rows_est = row.get("rows") or row.get("ROWS")
        if rows_est is not None:
            try:
                rows_count = int(rows_est)
                total_rows += rows_count
                if max_rows is None or rows_count > max_rows:
                    max_rows = rows_count
            except (ValueError, TypeError):
                pass

        # Also check for text-based output (EXPLAIN FORMAT=TREE)
        for key in ("EXPLAIN", "Extra", "plan"):
            text_val = row.get(key, "")
            if isinstance(text_val, str) and text_val:
                # Pattern: rows=123 or (rows=123)
                rows_pattern = r"rows[=:]\s*(\d+)"
                matches = re.findall(rows_pattern, text_val, re.IGNORECASE)
                for match in matches:
                    rows_count = int(match)
                    if max_rows is None or rows_count > max_rows:
                        max_rows = rows_count

                # Note: MySQL EXPLAIN FORMAT=TREE also shows cost, but we don't use it
                # as MySQL doesn't provide a unified cost metric like PostgreSQL

    # Use total rows if we have multiple tables being joined
    estimated_rows = total_rows if total_rows > 0 else max_rows

    # Rough size estimate: ~1KB per row
    size_gb = (estimated_rows * 1024) / (1024**3) if estimated_rows else None

    return estimated_rows, None, size_gb


def parse_sqlite_estimates(
    rows: list[dict[str, Any]],
) -> tuple[int | None, float | None, float | None]:
    """Parse SQLite EXPLAIN QUERY PLAN output for estimates.

    SQLite's EXPLAIN QUERY PLAN returns rows with columns:
    - id, parent, notused, detail

    The 'detail' column contains the query plan in text form, e.g.:
    - SCAN TABLE users
    - SEARCH TABLE orders USING INDEX idx_user_id (user_id=?)
    - USE TEMP B-TREE FOR ORDER BY

    SQLite doesn't provide row estimates in EXPLAIN QUERY PLAN.
    We can only infer relative cost from the plan operations.

    Returns:
        (estimated_rows, estimated_cost, estimated_size_gb)
    """
    # SQLite EXPLAIN QUERY PLAN doesn't provide row estimates.
    # It only shows the query plan structure (SCAN TABLE, SEARCH using index, etc.)
    # Without row estimates, the cost tier evaluation will default to CONFIRM
    # when rows is None, which is the safest approach for SQLite.
    #
    # The plan details are still returned in the ExplainResult.explanation field
    # for manual inspection if needed.

    return None, None, None


def parse_mssql_estimates(
    rows: list[dict[str, Any]],
) -> tuple[int | None, float | None, float | None]:
    """Parse SQL Server (MSSQL) execution plan estimates.

    MSSQL SET SHOWPLAN_TEXT ON or SET SHOWPLAN_ALL ON returns plan info.
    SHOWPLAN_ALL returns structured rows with columns like:
    - StmtText, Type, EstimateRows, EstimateIO, EstimateCPU, TotalSubtreeCost, etc.

    Returns:
        (estimated_rows, estimated_cost, estimated_size_gb)
    """
    max_rows = None
    max_cost = None

    for row in rows:
        # SHOWPLAN_ALL structured output
        est_rows = row.get("EstimateRows") or row.get("ESTIMATEROWS")
        if est_rows is not None:
            try:
                rows_count = int(float(est_rows))
                if max_rows is None or rows_count > max_rows:
                    max_rows = rows_count
            except (ValueError, TypeError):
                pass

        # Total subtree cost
        total_cost = row.get("TotalSubtreeCost") or row.get("TOTALSUBTREECOST")
        if total_cost is not None:
            try:
                cost = float(total_cost)
                if max_cost is None or cost > max_cost:
                    max_cost = cost
            except (ValueError, TypeError):
                pass

        # Text-based plan output (SET SHOWPLAN_TEXT ON)
        stmt_text = row.get("StmtText") or row.get("STMTTEXT", "")
        if isinstance(stmt_text, str) and stmt_text:
            # Pattern: Estimated rows: 123 or EstimateRows = 123
            rows_pattern = r"(?:Estimated\s*rows|EstimateRows)[=:\s]*([\d.]+)"
            matches = re.findall(rows_pattern, stmt_text, re.IGNORECASE)
            for match in matches:
                rows_count = int(float(match))
                if max_rows is None or rows_count > max_rows:
                    max_rows = rows_count

            # Pattern: Cost = 0.123 or TotalSubtreeCost = 0.123
            cost_pattern = r"(?:Cost|TotalSubtreeCost)[=:\s]*([\d.]+)"
            cost_matches = re.findall(cost_pattern, stmt_text, re.IGNORECASE)
            for match in cost_matches:
                cost = float(match)
                if max_cost is None or cost > max_cost:
                    max_cost = cost

    # Rough size estimate: ~1KB per row
    size_gb = (max_rows * 1024) / (1024**3) if max_rows else None

    return max_rows, max_cost, size_gb


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
    with tracer.start_as_current_span(
        "explain_sql",
        attributes={"sql.preview": sql[:200] + "..." if len(sql) > 200 else sql},
    ) as span:
        try:
            engine = get_engine(database_url)
            dialect = detect_dialect_from_url(str(engine.url))
            explain_cmd = get_explain_command(dialect)
            span.set_attribute("db.dialect", dialect)

            with tracer.start_as_current_span("db_execute_explain"):
                with engine.connect() as conn:
                    result = conn.execute(text(f"{explain_cmd} {sql}"))
                    columns = result.keys()
                    rows = [dict(zip(columns, row)) for row in result.fetchall()]

            # Parse estimates based on dialect
            with tracer.start_as_current_span("parse_estimates") as parse_span:
                if dialect in ("postgresql", "postgres"):
                    est_rows, est_cost, est_size = parse_postgresql_estimates(rows)
                elif dialect == "clickhouse":
                    est_rows, est_cost, est_size = parse_clickhouse_estimates(rows)
                elif dialect == "trino":
                    est_rows, est_cost, est_size = parse_trino_estimates(rows)
                elif dialect in ("mysql", "mariadb"):
                    est_rows, est_cost, est_size = parse_mysql_estimates(rows)
                elif dialect == "sqlite":
                    est_rows, est_cost, est_size = parse_sqlite_estimates(rows)
                elif dialect == "mssql":
                    est_rows, est_cost, est_size = parse_mssql_estimates(rows)
                else:
                    est_rows, est_cost, est_size = None, None, None

                if est_rows is not None:
                    parse_span.set_attribute("estimated_rows", est_rows)
                if est_cost is not None:
                    parse_span.set_attribute("estimated_cost", est_cost)

            # Evaluate cost tier
            cost_tier, tier_reason = evaluate_cost_tier(est_rows, est_cost, est_size)
            span.set_attribute("cost_tier", cost_tier.value)

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
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            return ExplainResult(
                valid=False,
                error=str(e),
                cost_tier=CostTier.REJECT,
                tier_reason="Database error",
            )
        except Exception as e:
            error_msg = str(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
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
    with tracer.start_as_current_span("validate_read_only") as span:
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
                span.set_attribute("validation.rejected", keyword)
                return False, f"Statement type '{keyword}' is not allowed (read-only mode)"

            # Also check for these within CTEs or subqueries
            # Pattern: keyword followed by whitespace or opening paren
            if re.search(rf"\b{keyword}\s", sql_upper):
                # Allow SELECT ... INTO for temp tables in some contexts
                if keyword == "INTO" and "SELECT" in sql_upper:
                    continue
                span.set_attribute("validation.rejected", keyword)
                return False, f"Statement contains '{keyword}' which is not allowed"

        # Must start with SELECT, WITH (CTE), or EXPLAIN
        if not any(
            sql_upper.startswith(kw) for kw in ["SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE"]
        ):
            span.set_attribute("validation.rejected", "not_select")
            return False, "Query must be a SELECT statement"

        span.set_attribute("validation.passed", True)
        return True, None
