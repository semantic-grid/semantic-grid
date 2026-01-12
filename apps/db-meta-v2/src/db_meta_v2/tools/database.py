"""Database MCP tools."""

from db_meta_v2.db.connection import detect_dialect_from_url, test_connection
from db_meta_v2.db.introspection import (
    get_catalogs,
    get_columns,
    get_schemas,
    get_table_sample,
    get_tables,
)
from db_meta_v2.tools.shell import inject_protocol


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


async def _list_catalogs(database_url: str | None = None) -> dict:
    """List all catalogs in the database (Trino 3-level hierarchy).

    Args:
        database_url: Optional database URL.

    Returns:
        List of catalog names
    """
    try:
        catalogs = get_catalogs(database_url)
        # Filter out None values for display
        catalogs_list = [c for c in catalogs if c is not None]
        return inject_protocol(
            {
                "catalogs": catalogs_list,
                "count": len(catalogs_list),
                "has_catalogs": len(catalogs_list) > 0,
                "error": None,
            }
        )
    except Exception as e:
        return inject_protocol(
            {
                "catalogs": [],
                "count": 0,
                "has_catalogs": False,
                "error": str(e),
            }
        )


async def _list_schemas(catalog: str | None = None, database_url: str | None = None) -> dict:
    """List all schemas in the database (or in a specific catalog for Trino).

    Args:
        catalog: Optional catalog name (for Trino 3-level hierarchy).
        database_url: Optional database URL.

    Returns:
        List of schema names
    """
    try:
        schemas = get_schemas(database_url, catalog=catalog)
        # Filter out None values for display
        schemas_list = [s for s in schemas if s is not None]
        return inject_protocol(
            {
                "schemas": schemas_list,
                "count": len(schemas_list),
                "catalog": catalog,
                "error": None,
            }
        )
    except Exception as e:
        return inject_protocol(
            {
                "schemas": [],
                "count": 0,
                "catalog": catalog,
                "error": str(e),
            }
        )


async def _list_tables(
    schema: str | None = None,
    catalog: str | None = None,
    database_url: str | None = None,
) -> dict:
    """List all tables in a schema (and catalog for Trino).

    IMPORTANT: This database uses 3-level hierarchy (catalog.schema.table).
    Always use list_catalogs() first, then list_schemas(catalog='...').

    Before generating SQL, check for existing examples:
        shell(command='grep -ri "keyword" examples/')

    Args:
        schema: Schema name. If None, uses default schema.
        catalog: Catalog name - REQUIRED for Trino databases.
        database_url: Optional database URL.

    Returns:
        List of table info with fully qualified names
    """
    try:
        tables = get_tables(schema=schema, catalog=catalog, database_url=database_url)
        return inject_protocol(
            {
                "tables": tables,
                "count": len(tables),
                "schema": schema,
                "catalog": catalog,
                "error": None,
            }
        )
    except Exception as e:
        return inject_protocol(
            {
                "tables": [],
                "count": 0,
                "schema": schema,
                "catalog": catalog,
                "error": str(e),
            }
        )


def _make_full_name(table_name: str, schema: str | None, catalog: str | None) -> str:
    """Build fully qualified table name."""
    if catalog and schema:
        return f"{catalog}.{schema}.{table_name}"
    elif schema:
        return f"{schema}.{table_name}"
    return table_name


async def _describe_table(
    table_name: str,
    schema: str | None = None,
    catalog: str | None = None,
    database_url: str | None = None,
) -> dict:
    """Get detailed information about a table.

    Before writing SQL, search for existing examples:
        shell(command='grep -ri "table_name" examples/')

    This database uses 3-level hierarchy: catalog.schema.table

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        catalog: Catalog name - REQUIRED for Trino databases.
        database_url: Optional database URL.

    Returns:
        Table info including columns
    """
    full_name = _make_full_name(table_name, schema, catalog)
    try:
        columns = get_columns(
            table_name, schema=schema, catalog=catalog, database_url=database_url
        )
        return inject_protocol(
            {
                "table_name": table_name,
                "schema": schema,
                "catalog": catalog,
                "full_name": full_name,
                "columns": columns,
                "column_count": len(columns),
                "error": None,
            }
        )
    except Exception as e:
        return inject_protocol(
            {
                "table_name": table_name,
                "schema": schema,
                "catalog": catalog,
                "full_name": full_name,
                "columns": [],
                "column_count": 0,
                "error": str(e),
            }
        )


async def _sample_table(
    table_name: str,
    schema: str | None = None,
    catalog: str | None = None,
    limit: int = 5,
    database_url: str | None = None,
) -> dict:
    """Get sample rows from a table.

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        catalog: Optional catalog name (for Trino 3-level hierarchy).
        limit: Maximum rows to return (default 5, max 100)
        database_url: Optional database URL.

    Returns:
        Sample rows from the table
    """
    # Enforce limit bounds
    limit = max(1, min(limit, 100))
    full_name = _make_full_name(table_name, schema, catalog)

    try:
        rows = get_table_sample(
            table_name,
            schema=schema,
            catalog=catalog,
            limit=limit,
            database_url=database_url,
        )
        return inject_protocol(
            {
                "table_name": table_name,
                "schema": schema,
                "catalog": catalog,
                "full_name": full_name,
                "rows": rows,
                "row_count": len(rows),
                "limit": limit,
                "error": None,
            }
        )
    except Exception as e:
        return inject_protocol(
            {
                "table_name": table_name,
                "schema": schema,
                "catalog": catalog,
                "full_name": full_name,
                "rows": [],
                "row_count": 0,
                "limit": limit,
                "error": str(e),
            }
        )
