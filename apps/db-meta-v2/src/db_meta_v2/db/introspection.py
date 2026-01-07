"""Database schema introspection."""

from typing import Any

from sqlalchemy import inspect, text

from db_meta_v2.db.connection import DatabaseError, get_engine


def get_dialect(database_url: str | None = None) -> str:
    """Get the SQL dialect for the database.

    Args:
        database_url: Optional database URL. If not provided, uses settings.

    Returns:
        Dialect name (e.g., 'trino', 'clickhouse', 'postgresql')
    """
    try:
        engine = get_engine(database_url)
        return engine.dialect.name
    except Exception as e:
        raise DatabaseError(f"Failed to get dialect: {e}") from e


def get_catalogs(database_url: str | None = None) -> list[str | None]:
    """Get list of catalogs in the database.

    For Trino: Queries all available catalogs via SHOW CATALOGS
    For ClickHouse: Returns the database name from URL as single catalog
    For PostgreSQL and others: Returns [None] (no catalog level)

    Args:
        database_url: Optional database URL. If not provided, uses settings.

    Returns:
        List of catalog names, or [None] if not applicable
    """
    try:
        engine = get_engine(database_url)
        dialect = engine.dialect.name.lower()

        if dialect == "trino":
            # Query all available catalogs in Trino
            try:
                with engine.connect() as conn:
                    result = conn.execute(text("SHOW CATALOGS"))
                    catalogs = [row[0] for row in result.fetchall()]
                    # Filter out system catalogs
                    catalogs = [c for c in catalogs if c not in ("system", "information_schema")]
                    return catalogs if catalogs else [None]
            except Exception:
                # Fallback to extracting from URL if SHOW CATALOGS fails
                url = engine.url
                if url.database:
                    parts = url.database.split("/")
                    return [parts[0]]
                return [None]
        elif dialect == "clickhouse":
            # For ClickHouse, the database acts as the catalog
            url = engine.url
            return [url.database] if url.database else [None]
        else:
            # PostgreSQL and others don't have catalog level
            return [None]
    except Exception as e:
        raise DatabaseError(f"Failed to get catalogs: {e}") from e


def get_schemas(database_url: str | None = None, catalog: str | None = None) -> list[str | None]:
    """Get list of schemas in the database.

    For Trino with catalog: Executes SHOW SCHEMAS FROM catalog
    For others: Uses SQLAlchemy inspector

    Args:
        database_url: Optional database URL. If not provided, uses settings.
        catalog: Optional catalog name (for Trino 3-level hierarchy)

    Returns:
        List of schema names, or [None] if not applicable
    """
    try:
        engine = get_engine(database_url)
        dialect = engine.dialect.name.lower()

        if dialect == "trino" and catalog:
            # Query schemas within the specific catalog
            try:
                with engine.connect() as conn:
                    result = conn.execute(text(f"SHOW SCHEMAS FROM {catalog}"))
                    schemas = [row[0] for row in result.fetchall()]
                    # Filter out system schemas
                    schemas = [s for s in schemas if s not in ("information_schema",)]
                    return schemas if schemas else [None]
            except Exception:
                # Fallback to inspector if query fails
                try:
                    inspector = inspect(engine)
                    return inspector.get_schema_names()
                except Exception:
                    return [None]
        else:
            # Use SQLAlchemy inspector for other databases
            try:
                inspector = inspect(engine)
                return inspector.get_schema_names()
            except Exception:
                return [None]
    except Exception as e:
        raise DatabaseError(f"Failed to get schemas: {e}") from e


def get_tables(
    schema: str | None = None,
    catalog: str | None = None,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Get list of tables in a schema.

    For Trino with catalog: Executes SHOW TABLES FROM catalog.schema
    For others: Uses SQLAlchemy inspector

    Args:
        schema: Schema name. If None, uses default schema.
        catalog: Optional catalog name (for Trino 3-level hierarchy)
        database_url: Optional database URL.

    Returns:
        List of table info dicts with 'name', 'schema', 'catalog', 'type' keys
    """
    try:
        engine = get_engine(database_url)
        dialect = engine.dialect.name.lower()

        tables = []

        # Build full_name based on hierarchy level
        def make_full_name(table_name: str) -> str:
            if catalog and schema:
                return f"{catalog}.{schema}.{table_name}"
            elif schema:
                return f"{schema}.{table_name}"
            return table_name

        if dialect == "trino" and catalog and schema:
            # For Trino with both catalog and schema, query directly
            with engine.connect() as conn:
                result = conn.execute(text(f"SHOW TABLES FROM {catalog}.{schema}"))
                table_names = [row[0] for row in result.fetchall()]

                for name in table_names:
                    tables.append(
                        {
                            "name": name,
                            "schema": schema,
                            "catalog": catalog,
                            "type": "table",
                            "full_name": make_full_name(name),
                        }
                    )
        elif dialect == "trino" and catalog:
            # For Trino with catalog only, iterate all schemas in that catalog
            with engine.connect() as conn:
                # Get schemas in this catalog
                schema_result = conn.execute(text(f"SHOW SCHEMAS FROM {catalog}"))
                schemas = [row[0] for row in schema_result.fetchall()]
                schemas = [s for s in schemas if s not in ("information_schema",)]

                for schema_name in schemas:
                    try:
                        table_result = conn.execute(
                            text(f"SHOW TABLES FROM {catalog}.{schema_name}")
                        )
                        table_names = [row[0] for row in table_result.fetchall()]

                        for name in table_names:
                            tables.append(
                                {
                                    "name": name,
                                    "schema": schema_name,
                                    "catalog": catalog,
                                    "type": "table",
                                    "full_name": f"{catalog}.{schema_name}.{name}",
                                }
                            )
                    except Exception:
                        # Skip schemas that error
                        continue
        else:
            # Use SQLAlchemy inspector for other databases
            inspector = inspect(engine)

            table_names = inspector.get_table_names(schema=schema)
            for name in table_names:
                tables.append(
                    {
                        "name": name,
                        "schema": schema,
                        "catalog": catalog,
                        "type": "table",
                        "full_name": make_full_name(name),
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
                            "catalog": catalog,
                            "type": "view",
                            "full_name": make_full_name(name),
                        }
                    )
            except Exception:
                # Some databases don't support view introspection
                pass

        return tables
    except Exception as e:
        raise DatabaseError(f"Failed to get tables: {e}") from e


def get_columns(
    table_name: str,
    schema: str | None = None,
    catalog: str | None = None,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Get column information for a table.

    For Trino with catalog: Uses DESCRIBE catalog.schema.table
    For others: Uses SQLAlchemy inspector

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        catalog: Optional catalog name (for Trino 3-level hierarchy)
        database_url: Optional database URL.

    Returns:
        List of column info dicts with name, type, nullable, etc.
    """
    try:
        engine = get_engine(database_url)
        dialect = engine.dialect.name.lower()

        if dialect == "trino" and catalog and schema:
            # For Trino, use DESCRIBE to get column info
            try:
                with engine.connect() as conn:
                    result = conn.execute(text(f"DESCRIBE {catalog}.{schema}.{table_name}"))
                    columns = []
                    for row in result.fetchall():
                        columns.append(
                            {
                                "name": row[0],
                                "type": row[1],
                                "nullable": True,  # Trino DESCRIBE doesn't show nullable
                                "default": None,
                                "primary_key": False,
                                "comment": row[2] if len(row) > 2 else None,
                            }
                        )
                    return columns
            except Exception:
                # Fallback to inspector
                pass

        # Use SQLAlchemy inspector for other databases or as fallback
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
    catalog: str | None = None,
    limit: int = 5,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Get sample rows from a table.

    Args:
        table_name: Name of the table
        schema: Schema name. If None, uses default schema.
        catalog: Optional catalog name (for Trino 3-level hierarchy)
        limit: Maximum number of rows to return
        database_url: Optional database URL.

    Returns:
        List of row dicts
    """
    try:
        engine = get_engine(database_url)

        # Build full table name based on hierarchy
        if catalog and schema:
            full_name = f"{catalog}.{schema}.{table_name}"
        elif schema:
            full_name = f"{schema}.{table_name}"
        else:
            full_name = table_name

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
