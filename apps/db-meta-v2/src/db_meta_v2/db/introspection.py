"""Database schema introspection."""

from typing import Any

from sqlalchemy import inspect, text

from db_meta_v2.db.connection import DatabaseError, get_engine


def get_schemas(database_url: str | None = None) -> list[str]:
    """Get list of schemas in the database.

    Args:
        database_url: Optional database URL. If not provided, uses settings.

    Returns:
        List of schema names
    """
    try:
        engine = get_engine(database_url)
        inspector = inspect(engine)
        return inspector.get_schema_names()
    except Exception as e:
        raise DatabaseError(f"Failed to get schemas: {e}") from e


def get_tables(schema: str | None = None, database_url: str | None = None) -> list[dict[str, Any]]:
    """Get list of tables in a schema.

    Args:
        schema: Schema name. If None, uses default schema.
        database_url: Optional database URL.

    Returns:
        List of table info dicts with 'name', 'schema', 'type' keys
    """
    try:
        engine = get_engine(database_url)
        inspector = inspect(engine)

        tables = []
        table_names = inspector.get_table_names(schema=schema)
        for name in table_names:
            tables.append(
                {
                    "name": name,
                    "schema": schema,
                    "type": "table",
                    "full_name": f"{schema}.{name}" if schema else name,
                }
            )

        # Also get views
        try:
            view_names = inspector.get_view_names(schema=schema)
            for name in view_names:
                tables.append(
                    {
                        "name": name,
                        "schema": schema,
                        "type": "view",
                        "full_name": f"{schema}.{name}" if schema else name,
                    }
                )
        except Exception:
            # Some databases don't support view introspection
            pass

        return tables
    except Exception as e:
        raise DatabaseError(f"Failed to get tables: {e}") from e


def get_columns(
    table_name: str, schema: str | None = None, database_url: str | None = None
) -> list[dict[str, Any]]:
    """Get column information for a table.

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        database_url: Optional database URL.

    Returns:
        List of column info dicts with name, type, nullable, etc.
    """
    try:
        engine = get_engine(database_url)
        inspector = inspect(engine)

        columns = inspector.get_columns(table_name, schema=schema)

        result = []
        for col in columns:
            result.append(
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "default": str(col.get("default")) if col.get("default") else None,
                    "primary_key": col.get("primary_key", False),
                    "comment": col.get("comment"),
                }
            )

        return result
    except Exception as e:
        raise DatabaseError(f"Failed to get columns for {table_name}: {e}") from e


def get_table_sample(
    table_name: str,
    schema: str | None = None,
    limit: int = 5,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Get sample rows from a table.

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        limit: Maximum number of rows to return
        database_url: Optional database URL.

    Returns:
        List of row dicts
    """
    try:
        engine = get_engine(database_url)

        full_name = f"{schema}.{table_name}" if schema else table_name

        # Use parameterized limit to prevent SQL injection
        # Note: table name should be validated before this point
        query = text(f"SELECT * FROM {full_name} LIMIT :limit")

        with engine.connect() as conn:
            result = conn.execute(query, {"limit": limit})
            columns = result.keys()
            rows = []
            for row in result:
                rows.append(dict(zip(columns, row)))
            return rows
    except Exception as e:
        raise DatabaseError(f"Failed to get sample from {table_name}: {e}") from e


def get_primary_keys(
    table_name: str, schema: str | None = None, database_url: str | None = None
) -> list[str]:
    """Get primary key columns for a table.

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        database_url: Optional database URL.

    Returns:
        List of primary key column names
    """
    try:
        engine = get_engine(database_url)
        inspector = inspect(engine)

        pk = inspector.get_pk_constraint(table_name, schema=schema)
        return pk.get("constrained_columns", [])
    except Exception as e:
        raise DatabaseError(f"Failed to get primary keys for {table_name}: {e}") from e


def get_foreign_keys(
    table_name: str, schema: str | None = None, database_url: str | None = None
) -> list[dict[str, Any]]:
    """Get foreign key constraints for a table.

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        database_url: Optional database URL.

    Returns:
        List of foreign key info dicts
    """
    try:
        engine = get_engine(database_url)
        inspector = inspect(engine)

        fks = inspector.get_foreign_keys(table_name, schema=schema)
        return [
            {
                "name": fk.get("name"),
                "columns": fk.get("constrained_columns", []),
                "referred_schema": fk.get("referred_schema"),
                "referred_table": fk.get("referred_table"),
                "referred_columns": fk.get("referred_columns", []),
            }
            for fk in fks
        ]
    except Exception as e:
        raise DatabaseError(f"Failed to get foreign keys for {table_name}: {e}") from e
