"""
Fast SQL syntax pre-validation using sqlglot.

This is a FAST PRE-CHECK before explain_analyze, not a replacement.
Always run explain_analyze as the source of truth.
"""

from typing import Optional

import sqlglot


class SqlValidationResult:
    """Result of SQL validation."""

    def __init__(
        self,
        valid: bool,
        error: Optional[str] = None,
        warning: Optional[str] = None,
    ):
        self.valid = valid
        self.error = error
        self.warning = warning


def validate_sql_syntax(
    sql: str,
    dialect: str = "clickhouse",
    strict: bool = False,
) -> SqlValidationResult:
    """
    Fast syntax validation using sqlglot.

    Args:
        sql: SQL query to validate
        dialect: SQL dialect (default: clickhouse)
        strict: If False, warnings don't fail validation (recommended)

    Returns:
        SqlValidationResult with validation status

    Note:
        This is a FAST PRE-CHECK. Always run explain_analyze after this
        as the source of truth. sqlglot may have false positives/negatives.
    """
    try:
        # Parse the SQL
        parsed = sqlglot.parse_one(sql, dialect=dialect, error_level=None)

        if parsed is None:
            return SqlValidationResult(
                valid=False,
                error="Failed to parse SQL - invalid syntax",
            )

        # Check for parsing errors
        # sqlglot collects errors during parsing
        errors = parsed.errors if hasattr(parsed, "errors") else []

        if errors:
            error_msg = "; ".join(str(e) for e in errors)
            return SqlValidationResult(
                valid=False,
                error=f"SQL syntax errors: {error_msg}",
            )

        # Try to transpile back to the dialect (catches some issues)
        try:
            transpiled = parsed.sql(dialect=dialect)
            if not transpiled:
                return SqlValidationResult(
                    valid=False,
                    error="Failed to transpile SQL back to dialect",
                )
        except Exception as e:
            # If transpilation fails, it might indicate issues
            # But don't fail validation - just warn
            warning_msg = f"Transpilation warning: {str(e)}"
            if strict:
                return SqlValidationResult(valid=False, error=warning_msg)
            else:
                return SqlValidationResult(valid=True, warning=warning_msg)

        # Success
        return SqlValidationResult(valid=True)

    except Exception as e:
        error_msg = f"SQL parsing error: {str(e)}"

        # Check if it's a known ClickHouse-specific feature
        clickhouse_features = [
            "SAMPLE",  # SAMPLE clause
            "ARRAY JOIN",  # Array joins
            "GLOBAL",  # GLOBAL joins
            "cityHash",  # ClickHouse hash functions
            "JSONExtract",  # ClickHouse JSON functions
            "ENGINE",  # CREATE TABLE engine syntax
        ]

        # If error mentions ClickHouse-specific features, treat as warning
        if any(feature.lower() in str(e).lower() for feature in clickhouse_features):
            if strict:
                return SqlValidationResult(valid=False, error=error_msg)
            else:
                return SqlValidationResult(
                    valid=True,
                    warning=f"{error_msg} (may be ClickHouse-specific syntax)",
                )

        return SqlValidationResult(valid=False, error=error_msg)


def should_skip_sqlglot_validation(sql: str) -> bool:
    """
    Determine if we should skip sqlglot validation for this SQL.

    Returns True if SQL contains known ClickHouse-specific features
    that sqlglot might not handle well.
    """
    # List of ClickHouse-specific keywords/patterns
    clickhouse_specific = [
        "SAMPLE ",  # SAMPLE clause
        "ARRAY JOIN",  # Array joins
        "ENGINE =",  # CREATE TABLE with engine
        "cityHash",  # ClickHouse hash functions
        "JSONExtract",  # ClickHouse JSON functions
        "FINAL",  # FINAL modifier
        "PREWHERE",  # PREWHERE instead of WHERE
    ]

    sql_upper = sql.upper()
    return any(pattern.upper() in sql_upper for pattern in clickhouse_specific)


# Example usage
if __name__ == "__main__":
    # Test cases
    test_cases = [
        # Valid SQL
        (
            "SELECT wallet, SUM(amount) FROM trades GROUP BY wallet",
            "Valid SQL",
            True,
        ),
        # Syntax error
        (
            "SELECT wallet SUM(amount) FROM trades",  # Missing comma
            "Missing comma",
            False,
        ),
        # ClickHouse-specific (might warn but pass)
        (
            "SELECT * FROM trades SAMPLE 0.1",
            "ClickHouse SAMPLE",
            True,  # Should pass with warning
        ),
    ]

    for sql, description, expected_valid in test_cases:
        print(f"\n{description}:")
        print(f"SQL: {sql[:60]}...")
        result = validate_sql_syntax(sql, strict=False)
        print(f"Valid: {result.valid} (expected: {expected_valid})")
        if result.error:
            print(f"Error: {result.error}")
        if result.warning:
            print(f"Warning: {result.warning}")
