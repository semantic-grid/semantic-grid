"""Database MCP tools."""

from db_meta_v2.db.connection import detect_dialect_from_url, test_connection
from db_meta_v2.db.introspection import get_columns, get_schemas, get_table_sample, get_tables


async def _test_connection(database_url: str | None = None) -> dict:
    """Test database connection.

    Args:
        database_url: Optional database URL. If not provided, uses configured URL.

    Returns:
        Connection status and info
    """
    return test_connection(database_url)


async def _detect_dialect(database_url: str) -> dict:
    """Detect SQL dialect from database URL.

    Args:
        database_url: Database connection URL

    Returns:
        Detected dialect info
    """
    dialect = detect_dialect_from_url(database_url)
    return {
        "dialect": dialect,
        "database_url_prefix": database_url.split("://")[0] if "://" in database_url else None,
    }


async def _list_schemas(database_url: str | None = None) -> dict:
    """List all schemas in the database.

    Args:
        database_url: Optional database URL.

    Returns:
        List of schema names
    """
    try:
        schemas = get_schemas(database_url)
        return {
            "schemas": schemas,
            "count": len(schemas),
            "error": None,
        }
    except Exception as e:
        return {
            "schemas": [],
            "count": 0,
            "error": str(e),
        }


async def _list_tables(schema: str | None = None, database_url: str | None = None) -> dict:
    """List all tables in a schema.

    Args:
        schema: Schema name. If None, uses default schema.
        database_url: Optional database URL.

    Returns:
        List of table info
    """
    try:
        tables = get_tables(schema, database_url)
        return {
            "tables": tables,
            "count": len(tables),
            "schema": schema,
            "error": None,
        }
    except Exception as e:
        return {
            "tables": [],
            "count": 0,
            "schema": schema,
            "error": str(e),
        }


async def _describe_table(
    table_name: str, schema: str | None = None, database_url: str | None = None
) -> dict:
    """Get detailed information about a table.

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        database_url: Optional database URL.

    Returns:
        Table info including columns
    """
    try:
        columns = get_columns(table_name, schema, database_url)
        return {
            "table_name": table_name,
            "schema": schema,
            "full_name": f"{schema}.{table_name}" if schema else table_name,
            "columns": columns,
            "column_count": len(columns),
            "error": None,
        }
    except Exception as e:
        return {
            "table_name": table_name,
            "schema": schema,
            "full_name": f"{schema}.{table_name}" if schema else table_name,
            "columns": [],
            "column_count": 0,
            "error": str(e),
        }


async def _sample_table(
    table_name: str,
    schema: str | None = None,
    limit: int = 5,
    database_url: str | None = None,
) -> dict:
    """Get sample rows from a table.

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        limit: Maximum rows to return (default 5, max 100)
        database_url: Optional database URL.

    Returns:
        Sample rows from the table
    """
    # Enforce limit bounds
    limit = max(1, min(limit, 100))

    try:
        rows = get_table_sample(table_name, schema, limit, database_url)
        return {
            "table_name": table_name,
            "schema": schema,
            "rows": rows,
            "row_count": len(rows),
            "limit": limit,
            "error": None,
        }
    except Exception as e:
        return {
            "table_name": table_name,
            "schema": schema,
            "rows": [],
            "row_count": 0,
            "limit": limit,
            "error": str(e),
        }
