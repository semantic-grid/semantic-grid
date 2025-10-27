"""
Validator for QueryMetadata to ensure column_name consistency with SQL.
"""

import re
from typing import Any, Optional

import sqlglot
from sqlglot import exp

from fm_app.api.model import QueryMetadata
from fm_app.utils import get_cached_warehouse_dialect


class MetadataValidationError(Exception):
    """Raised when QueryMetadata validation fails."""

    pass


class MetadataValidator:
    """Validates QueryMetadata against SQL for consistency."""

    @staticmethod
    def extract_result_columns(sql: str, dialect: Optional[str] = None) -> list[str]:
        """
        Extract the result column names from a SQL query.

        Args:
            sql: The SQL query string
            dialect: SQL dialect (default: auto-detect from warehouse)

        Returns:
            List of column names that will appear in the result set
        """
        if dialect is None:
            dialect = get_cached_warehouse_dialect()
        try:
            # Parse the SQL
            parsed = sqlglot.parse_one(sql, dialect=dialect)

            # Handle CTEs and find the outermost SELECT
            if isinstance(parsed, exp.Select):
                select_node = parsed
            else:
                # Find the outermost SELECT in case of CTEs
                select_node = parsed.find(exp.Select)

            if not select_node:
                raise MetadataValidationError(
                    f"Could not find SELECT statement in SQL: {sql[:100]}..."
                )

            result_columns = []

            # Extract column names from SELECT expressions
            for expression in select_node.expressions:
                # Check if there's an alias
                if expression.alias:
                    # Use the alias as the result column name
                    result_columns.append(expression.alias)
                elif isinstance(expression, exp.Column):
                    # No alias, use the column name
                    result_columns.append(expression.name)
                elif isinstance(expression, exp.Star):
                    # SELECT * - we can't validate this deterministically
                    # Return empty list to signal we can't validate
                    return []
                else:
                    # For expressions without aliases (functions, calculations, etc.)
                    # Try to get a sensible name
                    # In most SQL dialects, this would error without an alias
                    # but let's try to extract something
                    sql_text = expression.sql(dialect=dialect)
                    # Clean up the expression to just get identifier-like parts
                    clean_name = re.sub(r"[^\w]", "_", sql_text)
                    result_columns.append(clean_name)

            return result_columns

        except Exception as e:
            raise MetadataValidationError(
                f"Failed to parse SQL: {str(e)}. SQL: {sql[:200]}..."
            )

    @staticmethod
    def validate_metadata(
        metadata: QueryMetadata, dialect: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Validate QueryMetadata against its SQL.

        Args:
            metadata: The QueryMetadata object to validate
            dialect: SQL dialect (default: auto-detect from warehouse)

        Returns:
            Dict with validation results:
            {
                "valid": bool,
                "errors": list[str],
                "warnings": list[str],
                "sql_columns": list[str],
                "metadata_columns": list[str]
            }
        """
        if dialect is None:
            dialect = get_cached_warehouse_dialect()
        errors = []
        warnings = []

        if not metadata.sql:
            return {
                "valid": False,
                "errors": ["No SQL found in metadata"],
                "warnings": [],
                "sql_columns": [],
                "metadata_columns": [],
            }

        # Extract result columns from SQL
        try:
            sql_columns = MetadataValidator.extract_result_columns(
                metadata.sql, dialect=dialect
            )
        except MetadataValidationError as e:
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": [],
                "sql_columns": [],
                "metadata_columns": [],
            }

        # If we got empty list, it means SELECT * or couldn't parse
        if not sql_columns:
            warnings.append(
                "SQL uses SELECT * or couldn't determine columns - skipping validation"
            )
            return {
                "valid": True,
                "errors": [],
                "warnings": warnings,
                "sql_columns": [],
                "metadata_columns": [],
            }

        # Get metadata column names
        metadata_columns = []
        if metadata.columns:
            for col in metadata.columns:
                if col.column_name:
                    metadata_columns.append(col.column_name)

        # Normalize for comparison (case-insensitive, trim)
        sql_columns_normalized = {col.lower().strip() for col in sql_columns}
        metadata_columns_normalized = {
            col.lower().strip() for col in metadata_columns
        }

        # Check for mismatches
        missing_in_metadata = sql_columns_normalized - metadata_columns_normalized
        extra_in_metadata = metadata_columns_normalized - sql_columns_normalized

        if missing_in_metadata:
            errors.append(
                f"Columns in SQL but missing from metadata: {sorted(missing_in_metadata)}"
            )

        if extra_in_metadata:
            errors.append(
                f"Columns in metadata but not in SQL results: {sorted(extra_in_metadata)}"
            )

        # Check for expressions or table prefixes in column_name (common mistakes)
        if metadata.columns:
            for col in metadata.columns:
                if not col.column_name:
                    warnings.append(f"Column {col.id} has no column_name")
                    continue

                # Check for function calls
                if "(" in col.column_name and ")" in col.column_name:
                    errors.append(
                        f"column_name '{col.column_name}' contains function/expression - should be the alias instead"
                    )

                # Check for table prefixes
                if "." in col.column_name:
                    errors.append(
                        f"column_name '{col.column_name}' contains table prefix - should be just the column name"
                    )

                # Check for non-identifier characters (except underscore)
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", col.column_name):
                    errors.append(
                        f"column_name '{col.column_name}' is not a valid SQL identifier"
                    )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "sql_columns": sql_columns,
            "metadata_columns": metadata_columns,
        }

    @staticmethod
    def validate_and_raise(
        metadata: QueryMetadata, dialect: Optional[str] = None
    ) -> None:
        """
        Validate metadata and raise exception if invalid.

        Args:
            metadata: The QueryMetadata to validate
            dialect: SQL dialect (default: auto-detect from warehouse)

        Raises:
            MetadataValidationError: If validation fails
        """
        if dialect is None:
            dialect = get_cached_warehouse_dialect()
        result = MetadataValidator.validate_metadata(metadata, dialect=dialect)

        if not result["valid"]:
            error_msg = "QueryMetadata validation failed:\n"
            error_msg += "\n".join(f"  - {err}" for err in result["errors"])
            if result["warnings"]:
                error_msg += "\nWarnings:\n"
                error_msg += "\n".join(f"  - {warn}" for warn in result["warnings"])
            raise MetadataValidationError(error_msg)


def validate_metadata_dict(
    metadata_dict: dict[str, Any], dialect: Optional[str] = None
) -> dict[str, Any]:
    """
    Validate a metadata dictionary (useful for API responses).

    Args:
        metadata_dict: Dict representation of QueryMetadata
        dialect: SQL dialect (default: auto-detect from warehouse)

    Returns:
        Validation result dict
    """
    try:
        metadata = QueryMetadata(**metadata_dict)
        return MetadataValidator.validate_metadata(metadata, dialect=dialect)
    except Exception as e:
        return {
            "valid": False,
            "errors": [f"Failed to parse metadata: {str(e)}"],
            "warnings": [],
            "sql_columns": [],
            "metadata_columns": [],
        }
