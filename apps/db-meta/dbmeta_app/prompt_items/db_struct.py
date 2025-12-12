import logging
import pathlib
from typing import Any, Dict

import yaml
from pydantic import BaseModel, RootModel
from sqlalchemy import inspect, text

from dbmeta_app.api.model import PromptItem, PromptItemType
from dbmeta_app.cache import CACHE_TTL, get_cache
from dbmeta_app.config import get_settings
from dbmeta_app.prompt_assembler.prompt_packs import assemble_effective_tree, load_yaml
from dbmeta_app.wh_db.db import get_db


def get_sample_query(table: str, engine, limit: int = 5) -> str:
    """
    Generate a database-specific optimized sample query.

    Different databases have different optimal approaches for sampling:
    - ClickHouse: SAMPLE clause (very fast, samples data blocks)
    - PostgreSQL: TABLESAMPLE BERNOULLI (fast, row-level sampling)
    - MySQL/MariaDB: Simple LIMIT (ORDER BY RAND() is too slow on large tables)
    - SQLite: Simple LIMIT
    - DuckDB: USING SAMPLE (very fast, similar to ClickHouse)
    - Others: Simple LIMIT (safest fallback)

    Args:
        table: Table name to sample from
        engine: SQLAlchemy engine (used to detect database dialect)
        limit: Number of sample rows to return (default 5)

    Returns:
        SQL query string optimized for the specific database
    """
    dialect = engine.dialect.name.lower()

    if dialect == "clickhouse":
        # ClickHouse: SAMPLE is very efficient (samples data blocks)
        # SAMPLE 0.01 = sample 1% of data blocks
        return f"SELECT * FROM {table} SAMPLE 0.01 LIMIT {limit}"
    elif dialect == "postgresql":
        # PostgreSQL: TABLESAMPLE BERNOULLI samples individual rows
        # BERNOULLI(1) = 1% row-level sampling
        # Note: SYSTEM is faster but may return 0 rows on small tables
        return f"SELECT * FROM {table} TABLESAMPLE BERNOULLI (1) LIMIT {limit}"
    elif dialect == "duckdb":
        # DuckDB: USING SAMPLE is very fast
        return f"SELECT * FROM {table} USING SAMPLE 1% LIMIT {limit}"
    elif dialect in ("mysql", "mariadb"):
        # MySQL: Just use LIMIT (ORDER BY RAND() is extremely slow on large tables)
        # This gets rows in storage order, which is usually fine for sample data
        return f"SELECT * FROM {table} LIMIT {limit}"
    elif dialect == "sqlite":
        # SQLite: Simple LIMIT (RANDOM() is slow, but SQLite typically
        # has small datasets)
        return f"SELECT * FROM {table} LIMIT {limit}"
    elif dialect == "mssql":
        # SQL Server: TABLESAMPLE can be used but syntax is different
        # Using simple LIMIT-style query (TOP in SQL Server)
        return f"SELECT TOP {limit} * FROM {table}"
    elif dialect == "oracle":
        # Oracle: Use SAMPLE clause or ROWNUM
        return f"SELECT * FROM {table} SAMPLE (1) WHERE ROWNUM <= {limit}"
    else:
        # Safe fallback for unknown databases
        return f"SELECT * FROM {table} LIMIT {limit}"


class DbColumn(BaseModel):
    name: str
    type: str
    description: str | None = None
    example: str | None = None


class DbTable(BaseModel):
    columns: dict[str, DbColumn]
    description: str | None = None


class DbSchema(RootModel[Dict[str, DbTable]]):
    pass


class PreflightResult(BaseModel):
    explanation: list[dict[str, Any]] | None = None
    error: str | None = None
    estimated_rows: int | None = None  # Estimated rows from query plan
    estimated_output_size_gb: float | None = None  # Estimated output size in GB


def load_yaml_descriptions(yaml_file):
    """Loads table and column descriptions from a YAML file."""
    with open(yaml_file, "r") as file:
        return yaml.safe_load(file)


def _get_catalogs(engine, conn):
    """
    Get list of catalogs from the database.

    For Trino: Queries all available catalogs via SHOW CATALOGS
    For ClickHouse: Returns the database name from URL as single catalog
    For others: Returns [None]

    Args:
        engine: SQLAlchemy engine
        conn: Active database connection

    Returns:
        list: List of catalog names, or [None] if not applicable
    """
    dialect = engine.dialect.name.lower()

    if dialect == "trino":
        # Query all available catalogs in Trino
        try:
            result = conn.execute(text("SHOW CATALOGS"))
            catalogs = [row[0] for row in result.fetchall()]
            # Filter out system catalogs if needed
            catalogs = [
                c for c in catalogs if c not in ("system", "information_schema")
            ]
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
        # For PostgreSQL and others, no catalog level
        return [None]


def _get_schemas_for_catalog(engine, inspector, conn, catalog_name):
    """
    Get schemas for a specific catalog.

    For Trino: Executes SHOW SCHEMAS FROM catalog
    For others: Uses inspector.get_schema_names()

    Args:
        engine: SQLAlchemy engine
        inspector: SQLAlchemy inspector
        conn: Active database connection
        catalog_name: Name of the catalog (or None)

    Returns:
        list: List of schema names
    """
    dialect = engine.dialect.name.lower()

    if dialect == "trino" and catalog_name:
        # Query schemas within the specific catalog
        try:
            result = conn.execute(text(f"SHOW SCHEMAS FROM {catalog_name}"))
            schemas = [row[0] for row in result.fetchall()]
            # Filter out system schemas
            schemas = [s for s in schemas if s not in ("information_schema",)]
            return schemas if schemas else [None]
        except Exception:
            # Fallback to inspector if query fails
            try:
                return inspector.get_schema_names()
            except Exception:
                return [None]
    else:
        # Use standard inspector for other databases
        try:
            return inspector.get_schema_names()
        except Exception:
            return [None]


def _get_table_metadata_with_fallback(
    descriptions, table_name, schema_name=None, catalog_name=None
):
    """
    Lookup table metadata from descriptions with fallback from fully
    qualified to short names.

    Tries in order:
    1. catalog.schema.table (if catalog and schema provided)
    2. schema.table (if schema provided)
    3. table (short name)

    Args:
        descriptions: The descriptions dict from schema_descriptions.yaml
        table_name: Table name
        schema_name: Optional schema/database name
        catalog_name: Optional catalog name (Trino)

    Returns:
        dict: Table metadata from descriptions, or empty dict if not found
    """
    tables = descriptions.get("tables", {})

    # Try fully qualified names first (most specific to least specific)
    if catalog_name and schema_name:
        fqn = f"{catalog_name}.{schema_name}.{table_name}"
        if fqn in tables:
            return tables[fqn]

    if schema_name:
        fqn = f"{schema_name}.{table_name}"
        if fqn in tables:
            return tables[fqn]

    # Fallback to short table name
    return tables.get(table_name, {})


def _should_include_table(descriptions, table_metadata):
    """
    Determine if a table should be included based on whitelist/hidden settings.

    Args:
        descriptions: Profile descriptions from schema_descriptions.yaml
        table_metadata: Table metadata dict

    Returns:
        bool: True if table should be included
    """
    has_whitelist = descriptions.get("whitelist", False)
    has_table_description = bool(table_metadata)

    # with whitelist mode, only tables in the descriptions are included
    if has_whitelist and not has_table_description:
        return False

    if table_metadata.get("hidden", False):
        return False

    return True


def filter_structured_schema(schema_data: dict, relevant_tables: set | None) -> dict:
    """
    Filter structured schema to only include relevant tables.

    Args:
        schema_data: Full structured schema dict from get_structured_schema()
        relevant_tables: Set of table names to include, or None for all tables

    Returns:
        dict: Filtered schema data containing only relevant tables
    """
    if not relevant_tables:
        return schema_data

    return {
        table: data for table, data in schema_data.items() if table in relevant_tables
    }


def render_schema_to_text(schema_data: dict, table_counter_start: int = 1) -> str:
    """
    Convert structured schema dict to text prompt format.

    This renders the schema in the same format as generate_schema_prompt()
    to maintain compatibility with existing prompts.

    Args:
        schema_data: Structured schema dict (full or filtered)
        table_counter_start: Starting number for table counter (default: 1)

    Returns:
        str: Human-readable schema text
    """
    schema_text = "The database contains the following tables:\n\n"
    table_counter = table_counter_start - 1

    for full_table_name, table_data in schema_data.items():
        table_counter += 1

        description = table_data.get("description", "")
        schema_text += (
            f"Table #{table_counter}. **{full_table_name}** ({description})\n"
        )

        # Render columns
        columns = table_data.get("columns", [])
        for col in columns:
            if col.get("hidden", False):
                continue

            col_name = col.get("name", "")
            col_type = col.get("type", "")
            col_desc = col.get("description", "")
            col_example = col.get("example", "")

            schema_text += f"   - {col_name} ({col_type})"

            if col_desc:
                schema_text += f" - {col_desc}"
            if col_example:
                schema_text += f" (e.g., {col_example})"

            schema_text += "\n"

        schema_text += "\n"

        # Render sample rows if present
        sample_rows = table_data.get("sample_rows")
        if sample_rows:
            schema_text += (
                "\nSample Data Rows (CSVs):\n"
                + "\n".join(",".join(row) for row in sample_rows)
                + "\n\n"
            )

    return schema_text


def get_structured_schema(engine, settings, with_examples=False):
    """
    Generate structured schema data (dict format) suitable for caching.

    This function performs the expensive DB introspection and returns structured data
    that can be easily cached, filtered, and rendered.

    Args:
        engine: SQLAlchemy engine
        settings: Application settings
        with_examples: Whether to include sample data rows

    Returns:
        dict: {table_name: {description, columns, sample_rows}}
    """
    # Try to get from cache first
    cache = get_cache()
    profile = settings.default_profile
    client = settings.client
    env = settings.env

    cache_key_args = (profile, client, env, with_examples)
    cached_result = cache.get("schema_structured", *cache_key_args)
    if cached_result is not None:
        logging.info(
            f"Structured schema cache HIT for profile={profile}, "
            f"client={client}, env={env}"
        )
        return cached_result

    logging.info(
        f"Structured schema cache MISS for profile={profile}, "
        f"client={client}, env={env}"
    )

    # Build structured schema
    inspector = inspect(engine)
    dialect = engine.dialect.name.lower()
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    tree = assemble_effective_tree(repo_root, profile, client, env)

    file = load_yaml(tree, "resources/schema_descriptions.yaml")

    # Defensive: handle missing 'profiles' key or missing profile
    if "profiles" not in file:
        raise ValueError(
            f"schema_descriptions.yaml missing 'profiles' key. File content: {file}"
        )
    if profile not in file["profiles"]:
        available_profiles = list(file["profiles"].keys())
        raise ValueError(
            f"Profile '{profile}' not found in schema_descriptions.yaml. "
            f"Available profiles: {available_profiles}"
        )

    descriptions = file["profiles"][profile]

    # Store tables as dict
    tables_data = {}

    with engine.connect() as conn:
        catalog_names = _get_catalogs(engine, conn)

        for catalog_name in catalog_names:
            schema_names = _get_schemas_for_catalog(
                engine, inspector, conn, catalog_name
            )

            # Filter out system schemas
            if dialect == "clickhouse":
                schema_names = [
                    s
                    for s in schema_names
                    if s
                    and not s.startswith("_")
                    and s not in ("system", "information_schema", "INFORMATION_SCHEMA")
                ]
            elif dialect in ("postgresql", "postgres"):
                schema_names = [
                    s
                    for s in schema_names
                    if s
                    and s
                    not in ("information_schema", "pg_catalog", "pg_toast", "pg_temp_1")
                ]
            elif dialect == "trino":
                schema_names = [
                    s for s in schema_names if s and s not in ("information_schema",)
                ]

            if not schema_names:
                schema_names = [None]

            for schema_name in schema_names:
                try:
                    if dialect == "trino" and catalog_name and schema_name:
                        result = conn.execute(
                            text(f"SHOW TABLES FROM {catalog_name}.{schema_name}")
                        )
                        table_names = [row[0] for row in result.fetchall()]
                    elif schema_name:
                        table_names = inspector.get_table_names(schema=schema_name)
                    else:
                        table_names = inspector.get_table_names()
                except Exception:
                    continue

                for table in table_names:
                    # Skip system/internal tables
                    if table.startswith("_") or table.startswith("temp_"):
                        continue

                    # Build fully qualified table name
                    if dialect == "trino" and catalog_name and schema_name:
                        full_table_name = f"{catalog_name}.{schema_name}.{table}"
                    elif schema_name:
                        full_table_name = f"{schema_name}.{table}"
                    else:
                        full_table_name = table

                    # Get table metadata
                    table_metadata = _get_table_metadata_with_fallback(
                        descriptions, table, schema_name, catalog_name
                    )

                    if not _should_include_table(descriptions, table_metadata):
                        continue

                    table_description = table_metadata.get(
                        "description", f"Stores {table.replace('_', ' ')} data."
                    )

                    # Get columns
                    try:
                        if dialect == "trino" and catalog_name and schema_name:
                            result = conn.execute(
                                text(f"DESCRIBE {catalog_name}.{schema_name}.{table}")
                            )
                            columns = []
                            for row in result.fetchall():
                                columns.append(
                                    {
                                        "name": row[0],
                                        "type": str(row[1]),
                                        "nullable": True,
                                        "default": None,
                                    }
                                )
                        elif schema_name:
                            columns = inspector.get_columns(table, schema=schema_name)
                        else:
                            columns = inspector.get_columns(table)
                    except Exception as e:
                        logging.warning(
                            f"Failed to get columns for {full_table_name}: {e}"
                        )
                        continue

                    # Build column data with metadata
                    columns_data = []
                    for col in columns:
                        col_metadata = table_metadata.get("columns", {}).get(
                            col["name"], {}
                        )
                        col_hidden = col_metadata.get("hidden", False)

                        if not col_hidden:
                            columns_data.append(
                                {
                                    "name": col["name"],
                                    "type": str(col["type"]),
                                    "nullable": col.get("nullable", True),
                                    "default": col.get("default"),
                                    "description": col_metadata.get("description", ""),
                                    "example": col_metadata.get("example", ""),
                                    "hidden": col_hidden,
                                }
                            )

                    # Get sample rows if requested
                    sample_rows = None
                    if with_examples:
                        try:
                            query_table_name = full_table_name if schema_name else table
                            sample_query = get_sample_query(query_table_name, engine)
                            result = conn.execute(text(sample_query))
                            rows = result.fetchall()
                            if rows:
                                sample_rows = [[str(v) for v in row] for row in rows]
                        except Exception as e:
                            logging.warning(
                                f"Failed to get sample rows for {full_table_name}: {e}"
                            )

                    # Store structured data
                    tables_data[full_table_name] = {
                        "table_name": table,
                        "full_table_name": full_table_name,
                        "description": table_description,
                        "columns": columns_data,
                        "sample_rows": sample_rows,
                    }

    # Cache the structured data
    cache.set("schema_structured", tables_data, CACHE_TTL["schema"], *cache_key_args)
    logging.info(
        f"Structured schema cached for profile={profile}, client={client}, env={env}"
    )

    return tables_data


def generate_schema_prompt(engine, settings, with_examples=False, filter_tables=None):
    """Generates a human-readable schema description merged with YAML descriptions,
    including examples. Iterates through catalog/schema/table hierarchy.

    Args:
        engine: SQLAlchemy engine
        settings: Application settings
        with_examples: Whether to include data examples
        filter_tables: Optional set of table names to include (for semantic filtering)
    """
    # Try to get from cache first (only if not filtering)
    # We cache the FULL schema, not filtered versions
    cache = get_cache()
    profile = settings.default_profile
    client = settings.client
    env = settings.env

    cache_key_args = (profile, client, env, with_examples)

    # Only use cache if we're not filtering (filter_tables is None)
    if filter_tables is None:
        cached_result = cache.get("schema", *cache_key_args)
        if cached_result is not None:
            logging.info(
                f"Schema cache HIT for profile={profile}, client={client}, env={env}"
            )
            return cached_result

        logging.info(
            f"Schema cache MISS for profile={profile}, client={client}, env={env}"
        )

    inspector = inspect(engine)
    dialect = engine.dialect.name.lower()
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    tree = assemble_effective_tree(repo_root, profile, client, env)

    file = load_yaml(tree, "resources/schema_descriptions.yaml")

    # Defensive: handle missing 'profiles' key or missing profile
    if "profiles" not in file:
        raise ValueError(
            f"schema_descriptions.yaml missing 'profiles' key. File content: {file}"
        )
    if profile not in file["profiles"]:
        available_profiles = list(file["profiles"].keys())
        raise ValueError(
            f"Profile '{profile}' not found in schema_descriptions.yaml. "
            f"Available profiles: {available_profiles}"
        )

    descriptions = file["profiles"][profile]
    schema_text = "The database contains the following tables:\n\n"

    with engine.connect() as conn:
        # Get all catalogs (Trino: multiple, others: single or None)
        catalog_names = _get_catalogs(engine, conn)

        table_counter = 0

        # Iterate through catalogs (outer loop for Trino 3-level hierarchy)
        for catalog_name in catalog_names:
            # Get schemas for this catalog
            schema_names = _get_schemas_for_catalog(
                engine, inspector, conn, catalog_name
            )

            # Filter out system schemas based on dialect
            if dialect == "clickhouse":
                # Skip ClickHouse system databases
                schema_names = [
                    s
                    for s in schema_names
                    if s
                    and not s.startswith("_")
                    and s not in ("system", "information_schema", "INFORMATION_SCHEMA")
                ]
            elif dialect in ("postgresql", "postgres"):
                # Skip PostgreSQL system schemas
                schema_names = [
                    s
                    for s in schema_names
                    if s
                    and s
                    not in (
                        "information_schema",
                        "pg_catalog",
                        "pg_toast",
                        "pg_temp_1",
                    )
                ]
            elif dialect == "trino":
                # For Trino, filtering already done in _get_schemas_for_catalog
                # but apply additional safety filter here
                schema_names = [
                    s for s in schema_names if s and s not in ("information_schema",)
                ]

            # If no schemas found, use None
            if not schema_names:
                schema_names = [None]

            for schema_name in schema_names:
                try:
                    if dialect == "trino" and catalog_name and schema_name:
                        # For Trino, use raw SQL to query tables from catalog.schema
                        result = conn.execute(
                            text(f"SHOW TABLES FROM {catalog_name}.{schema_name}")
                        )
                        table_names = [row[0] for row in result.fetchall()]
                    elif schema_name:
                        table_names = inspector.get_table_names(schema=schema_name)
                    else:
                        table_names = inspector.get_table_names()
                except Exception:
                    # Skip schemas that error out
                    continue
            logging.info(
                "got table_names", extra={"schema": schema_name, "tables": table_names}
            )

            for table in table_names:
                # Skip system/internal tables and temp tables
                if table.startswith("_") or table.startswith("temp_"):
                    continue

                # Build fully qualified table name for filtering
                # For Trino, use catalog.schema.table (3-level)
                if dialect == "trino" and catalog_name and schema_name:
                    full_table_name = f"{catalog_name}.{schema_name}.{table}"
                elif schema_name:
                    full_table_name = f"{schema_name}.{table}"
                else:
                    full_table_name = table

                # Apply semantic filtering if filter_tables is provided
                if filter_tables is not None and full_table_name not in filter_tables:
                    continue

                # Lookup table metadata with fallback (supports 3-level hierarchy)
                table_metadata = _get_table_metadata_with_fallback(
                    descriptions, table, schema_name, catalog_name
                )

                # Check if table should be included
                if not _should_include_table(descriptions, table_metadata):
                    continue

                table_counter += 1

                table_description = table_metadata.get(
                    "description", f"Stores {table.replace('_', ' ')} data."
                )
                schema_text += (
                    f"Table #{table_counter}. **{full_table_name}** "
                    f"({table_description})\n"
                )

                try:
                    # For Trino, query columns using raw SQL to support
                    # cross-catalog access
                    if dialect == "trino" and catalog_name and schema_name:
                        # Use DESCRIBE or SHOW COLUMNS for Trino federated queries
                        result = conn.execute(
                            text(f"DESCRIBE {catalog_name}.{schema_name}.{table}")
                        )
                        # Convert Trino DESCRIBE output to inspector-like format
                        columns = []
                        for row in result.fetchall():
                            columns.append(
                                {
                                    "name": row[0],  # Column name
                                    "type": str(row[1]),  # Data type
                                    # Trino doesn't return nullable in DESCRIBE
                                    "nullable": True,
                                    "default": None,
                                }
                            )
                    elif schema_name:
                        columns = inspector.get_columns(table, schema=schema_name)
                    else:
                        columns = inspector.get_columns(table)
                except Exception as e:
                    # Skip tables that error during column introspection
                    logging.warning(f"Failed to get columns for {full_table_name}: {e}")
                    schema_text += "   (Unable to retrieve column information)\n\n"
                    continue

                for col in columns:
                    col_metadata = table_metadata.get("columns", {}).get(
                        col["name"], {}
                    )
                    col_desc = col_metadata.get("description", "")
                    col_example = col_metadata.get("example", "")
                    col_hidden = col_metadata.get("hidden", False)

                    if not col_hidden:
                        col_type = str(col["type"])
                        schema_text += f"   - {col['name']} ({col_type})"

                        if col_desc:
                            schema_text += f" - {col_desc}"
                        if col_example:
                            schema_text += f" (e.g., {col_example})"

                        schema_text += "\n"

                schema_text += "\n"

                # Fetch sample rows
                if not with_examples:
                    continue

                try:
                    # Build qualified table name for query
                    query_table_name = full_table_name if schema_name else table
                    # Use database-specific optimized sampling
                    sample_query = get_sample_query(query_table_name, engine)
                    res = conn.execute(text(sample_query))
                except Exception:
                    # Skip tables that timeout or fail to query
                    continue

                # skip columns which are marked as hidden in descriptions
                columns = res.keys()
                # Filter out hidden columns
                visible_columns = [
                    col
                    for col in columns
                    if not table_metadata.get("columns", {})
                    .get(col, {})
                    .get("hidden", False)
                ]

                # Get indexes of visible columns to filter row values
                visible_indexes = [
                    i for i, col in enumerate(columns) if col in visible_columns
                ]

                # Fetch sample rows with only visible columns
                rows = [
                    {col: row[i] for col, i in zip(visible_columns, visible_indexes)}
                    for row in res.fetchall()
                ]
                if rows:
                    # rows_str = [{k: str(v) for k, v in row.items()} for row in rows]
                    schema_text += (
                        "\nSample Data Rows (CSVs):\n"
                        + "\n".join(",".join(map(str, row.values())) for row in rows)
                        + "\n\n"
                    )

    # Cache the result (only if we generated the full schema, not a filtered version)
    if filter_tables is None:
        cache.set("schema", schema_text, CACHE_TTL["schema"], *cache_key_args)
        logging.info(f"Schema cached for profile={profile}, client={client}, env={env}")

    return schema_text


def get_schema_prompt_item(
    user_request: str | None = None, top_k: int = 10
) -> PromptItem:
    """
    Get schema prompt item, optionally filtered by semantic relevance to user request.

    This function uses a two-layer optimization strategy:
    1. Redis cache: Fast lookup of full structured schema (dict format)
    2. Semantic filtering: Filter cached schema to relevant tables using Milvus

    Args:
        user_request: Optional user's natural language query for semantic filtering
        top_k: Number of most relevant tables to include when filtering (default: 10)

    Returns:
        PromptItem containing schema information
    """
    settings = get_settings()
    engine = get_db()

    # Step 1: Get structured schema (from cache or DB introspection)
    structured_schema = get_structured_schema(
        engine,
        settings,
        with_examples=settings.data_examples,
    )

    # Step 2: Apply semantic filtering if user_request provided
    relevant_tables = None
    if user_request:
        # Use semantic search to filter tables
        from dbmeta_app.vector_db.milvus import search_relevant_tables

        table_matches = search_relevant_tables(
            query=user_request,
            profile=settings.default_profile,
            top_k=top_k,
            client=settings.client,
            env=settings.env,
        )

        # Extract table names for filtering
        if table_matches:
            relevant_tables = {match.table_name for match in table_matches}
            logging.info(
                f"Semantic filtering: selected {len(relevant_tables)} tables "
                f"for query: {user_request[:100]}"
            )

    # Step 3: Filter structured schema
    filtered_schema = filter_structured_schema(structured_schema, relevant_tables)

    # Step 4: Render to text
    prompt = render_schema_to_text(filtered_schema)

    # Compute hash and metadata for lineage tracking
    from dbmeta_app.prompt_items.utils import compute_content_hash

    content_hash = compute_content_hash(prompt)
    metadata = {
        "profile": settings.default_profile,
        "top_k": top_k,
        "tables_selected": sorted(relevant_tables) if relevant_tables else None,
        "user_request_provided": user_request is not None,
    }

    items = PromptItem(
        text=prompt,
        prompt_item_type=PromptItemType.db_struct,
        score=100_000,
        content_hash=content_hash,
        metadata=metadata,
    )
    return items


def get_db_schema() -> DbSchema:
    settings = get_settings()
    engine = get_db()
    inspector = inspect(engine)
    dialect = engine.dialect.name.lower()
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    client = settings.client
    env = settings.env
    profile = settings.default_profile
    tree = assemble_effective_tree(repo_root, profile, client, env)

    file = load_yaml(tree, "resources/schema_descriptions.yaml")

    # Defensive: handle missing 'profiles' key or missing profile
    if "profiles" not in file:
        raise ValueError(
            f"schema_descriptions.yaml missing 'profiles' key. File content: {file}"
        )
    if profile not in file["profiles"]:
        available_profiles = list(file["profiles"].keys())
        raise ValueError(
            f"Profile '{profile}' not found in schema_descriptions.yaml. "
            f"Available profiles: {available_profiles}"
        )

    descriptions = file["profiles"][profile]

    result: DbSchema = {}

    with engine.connect() as conn:
        # Get all catalogs (Trino: multiple, others: single or None)
        catalog_names = _get_catalogs(engine, conn)

        # Iterate through catalogs (outer loop for Trino 3-level hierarchy)
        for catalog_name in catalog_names:
            # Get schemas for this catalog
            schema_names = _get_schemas_for_catalog(
                engine, inspector, conn, catalog_name
            )

            # Filter out system schemas based on dialect
            if dialect == "clickhouse":
                schema_names = [
                    s
                    for s in schema_names
                    if s
                    and not s.startswith("_")
                    and s not in ("system", "information_schema", "INFORMATION_SCHEMA")
                ]
            elif dialect in ("postgresql", "postgres"):
                schema_names = [
                    s
                    for s in schema_names
                    if s
                    and s
                    not in (
                        "information_schema",
                        "pg_catalog",
                        "pg_toast",
                        "pg_temp_1",
                    )
                ]
            elif dialect == "trino":
                # For Trino, filtering already done in _get_schemas_for_catalog
                # but apply additional safety filter here
                schema_names = [
                    s for s in schema_names if s and s not in ("information_schema",)
                ]

            # If no schemas found, use None
            if not schema_names:
                schema_names = [None]

            for schema_name in schema_names:
                try:
                    if dialect == "trino" and catalog_name and schema_name:
                        # For Trino, use raw SQL to query tables from catalog.schema
                        result = conn.execute(
                            text(f"SHOW TABLES FROM {catalog_name}.{schema_name}")
                        )
                        table_names = [row[0] for row in result.fetchall()]
                    elif schema_name:
                        table_names = inspector.get_table_names(schema=schema_name)
                    else:
                        table_names = inspector.get_table_names()
                except Exception:
                    continue

                for table in table_names:
                    if table.startswith("_") or table.startswith("temp_"):
                        continue

                    # Lookup table metadata with fallback (supports 3-level hierarchy)
                    table_metadata = _get_table_metadata_with_fallback(
                        descriptions, table, schema_name, catalog_name
                    )

                    # Check if table should be included
                    if not _should_include_table(descriptions, table_metadata):
                        continue

                    try:
                        # For Trino, query columns using raw SQL to support
                        # cross-catalog access
                        if dialect == "trino" and catalog_name and schema_name:
                            result = conn.execute(
                                text(f"DESCRIBE {catalog_name}.{schema_name}.{table}")
                            )
                            # Convert Trino DESCRIBE output to inspector-like format
                            db_columns = []
                            for row in result.fetchall():
                                db_columns.append(
                                    {
                                        "name": row[0],
                                        "type": str(row[1]),
                                        "nullable": True,
                                        "default": None,
                                    }
                                )
                        elif schema_name:
                            db_columns = inspector.get_columns(
                                table, schema=schema_name
                            )
                        else:
                            db_columns = inspector.get_columns(table)
                    except Exception:
                        continue

                    columns = {}
                    for col in db_columns:
                        col_metadata = table_metadata.get("columns", {}).get(
                            col["name"], {}
                        )
                        col_desc = col_metadata.get("description", "")
                        col_example = col_metadata.get("example", "")
                        col_hidden = col_metadata.get("hidden", False)

                        if not col_hidden:
                            columns[col["name"]] = DbColumn(
                                name=col["name"],
                                type=str(col["type"]),
                                description=col_desc,
                                example=col_example,
                            )

                    # Build fully qualified table name for result key
                    # For Trino, use catalog.schema.table (3-level)
                    if dialect == "trino" and catalog_name and schema_name:
                        full_table_name = f"{catalog_name}.{schema_name}.{table}"
                    elif schema_name:
                        full_table_name = f"{schema_name}.{table}"
                    else:
                        full_table_name = table

                    result[full_table_name] = DbTable(
                        columns=columns,
                        description=table_metadata.get("description", None),
                    )

    return result


def get_data_samples() -> dict[str, Any]:
    settings = get_settings()
    engine = get_db()
    inspector = inspect(engine)
    dialect = engine.dialect.name.lower()
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    client = settings.client
    env = settings.env
    profile = settings.default_profile
    tree = assemble_effective_tree(repo_root, profile, client, env)

    file = load_yaml(tree, "resources/schema_descriptions.yaml")

    # Defensive: handle missing 'profiles' key or missing profile
    if "profiles" not in file:
        raise ValueError(
            f"schema_descriptions.yaml missing 'profiles' key. File content: {file}"
        )
    if profile not in file["profiles"]:
        available_profiles = list(file["profiles"].keys())
        raise ValueError(
            f"Profile '{profile}' not found in schema_descriptions.yaml. "
            f"Available profiles: {available_profiles}"
        )

    descriptions = file["profiles"][profile]

    result = {}

    with engine.connect() as conn:
        # Get all catalogs (Trino: multiple, others: single or None)
        catalog_names = _get_catalogs(engine, conn)

        # Iterate through catalogs (outer loop for Trino 3-level hierarchy)
        for catalog_name in catalog_names:
            # Get schemas for this catalog
            schema_names = _get_schemas_for_catalog(
                engine, inspector, conn, catalog_name
            )

            # Filter out system schemas based on dialect
            if dialect == "clickhouse":
                schema_names = [
                    s
                    for s in schema_names
                    if s
                    and not s.startswith("_")
                    and s not in ("system", "information_schema", "INFORMATION_SCHEMA")
                ]
            elif dialect in ("postgresql", "postgres"):
                schema_names = [
                    s
                    for s in schema_names
                    if s
                    and s
                    not in (
                        "information_schema",
                        "pg_catalog",
                        "pg_toast",
                        "pg_temp_1",
                    )
                ]
            elif dialect == "trino":
                # For Trino, filtering already done in _get_schemas_for_catalog
                # but apply additional safety filter here
                schema_names = [
                    s for s in schema_names if s and s not in ("information_schema",)
                ]

            # If no schemas found, use None
            if not schema_names:
                schema_names = [None]

            for schema_name in schema_names:
                try:
                    if dialect == "trino" and catalog_name and schema_name:
                        # For Trino, use raw SQL to query tables from catalog.schema
                        result = conn.execute(
                            text(f"SHOW TABLES FROM {catalog_name}.{schema_name}")
                        )
                        table_names = [row[0] for row in result.fetchall()]
                    elif schema_name:
                        table_names = inspector.get_table_names(schema=schema_name)
                    else:
                        table_names = inspector.get_table_names()
                except Exception:
                    continue

                for table in table_names:
                    if table.startswith("_") or table.startswith("temp_"):
                        continue

                    # Lookup table metadata with fallback (supports 3-level hierarchy)
                    table_metadata = _get_table_metadata_with_fallback(
                        descriptions, table, schema_name, catalog_name
                    )

                    # Check if table should be included
                    if not _should_include_table(descriptions, table_metadata):
                        continue

                    try:
                        # Build qualified table name for query
                        if schema_name:
                            full_table_name = f"{schema_name}.{table}"
                        else:
                            full_table_name = table

                        # Use database-specific optimized sampling
                        sample_query = get_sample_query(full_table_name, engine)
                        res = conn.execute(text(sample_query))
                    except Exception:
                        # Skip tables that timeout or fail to query
                        continue

                    # skip columns which are marked as hidden in descriptions
                    columns = res.keys()
                    # Filter out hidden columns
                    visible_columns = [
                        col
                        for col in columns
                        if not table_metadata.get("columns", {})
                        .get(col, {})
                        .get("hidden", False)
                    ]

                    # Get indexes of visible columns to filter row values
                    visible_indexes = [
                        i for i, col in enumerate(columns) if col in visible_columns
                    ]

                    # Fetch sample rows with only visible columns
                    rows = [
                        {
                            col: row[i]
                            for col, i in zip(visible_columns, visible_indexes)
                        }
                        for row in res.fetchall()
                    ]

                    if rows:
                        # Use fully qualified name as key
                        if schema_name:
                            full_table_name = f"{schema_name}.{table}"
                        else:
                            full_table_name = table
                        result[full_table_name] = rows

    return result


def parse_clickhouse_estimates(
    explanation_rows: list[dict[str, Any]],
) -> tuple[int | None, float | None]:
    """
    Parse ClickHouse EXPLAIN output to extract row and size estimates.

    ClickHouse EXPLAIN output can be in different formats:
    - EXPLAIN ESTIMATE: Returns structured data with 'rows', 'marks',
      'parts', 'database', 'table'
      Example: {"database": "ct", "marks": 285084, "parts": 268,
                "rows": 1608837646, "table": "enriched_trades"}
    - EXPLAIN: Returns execution plan as text string

    Returns:
        tuple of (estimated_rows, estimated_size_gb)
    """
    import re

    max_rows = None
    max_size_gb = None

    for row in explanation_rows:
        # First check if this is EXPLAIN ESTIMATE output
        # (structured data with 'rows' field)
        if "rows" in row and isinstance(row.get("rows"), (int, float)):
            rows = int(row["rows"])
            if max_rows is None or rows > max_rows:
                max_rows = rows
            continue

        # Otherwise, try to parse text-based EXPLAIN output
        # Try different possible column names
        explanation_text = (
            row.get("explain")
            or row.get("plan")
            or row.get("EXPLAIN")
            or list(row.values())[0]
            if row
            else ""
        )

        if not explanation_text or not isinstance(explanation_text, str):
            continue

        # Look for row count patterns in text
        # Pattern: "ReadFromStorage ... rows: 1000000"
        rows_pattern = r"rows?:\s*([\d,]+)"
        rows_matches = re.findall(rows_pattern, explanation_text, re.IGNORECASE)

        for rows_str in rows_matches:
            rows = int(rows_str.replace(",", ""))
            if max_rows is None or rows > max_rows:
                max_rows = rows

    # Estimate size based on row count (rough approximation: ~1KB per row)
    if max_rows is not None:
        max_size_gb = (max_rows * 1024) / (1024 * 1024 * 1024)  # Convert bytes to GB

    return max_rows, max_size_gb


def parse_trino_estimates(
    explanation_rows: list[dict[str, Any]],
) -> tuple[int | None, float | None]:
    """
    Parse Trino EXPLAIN output to extract row and size estimates.

    Trino's EXPLAIN output contains lines like:
    "Estimates: {rows: 811699256 (7.00GB), cpu: 7.00G, memory: ?, network: 0B}"

    We want to extract the maximum estimated rows and output size from the plan.

    Returns:
        tuple of (estimated_rows, estimated_size_gb)
    """
    import re

    max_rows = None
    max_size_gb = None

    for row in explanation_rows:
        # The explanation is typically in a "Query Plan" column
        query_plan = row.get("Query Plan", "")
        if not query_plan:
            continue

        # Find all Estimates blocks
        # Pattern: Estimates: {rows: NUMBER (SIZE), ...}
        estimate_pattern = r"Estimates:\s*\{rows:\s*([\d,]+)\s*\(([\d.]+)([KMGT]?B)\)"
        matches = re.findall(estimate_pattern, query_plan)

        for match in matches:
            rows_str, size_str, size_unit = match

            # Parse rows (remove commas)
            rows = int(rows_str.replace(",", ""))
            if max_rows is None or rows > max_rows:
                max_rows = rows

            # Parse size to GB
            size = float(size_str)
            if size_unit == "KB":
                size_gb = size / (1024 * 1024)
            elif size_unit == "MB":
                size_gb = size / 1024
            elif size_unit == "GB":
                size_gb = size
            elif size_unit == "TB":
                size_gb = size * 1024
            elif size_unit == "B":
                size_gb = size / (1024 * 1024 * 1024)
            else:
                size_gb = size / (1024 * 1024 * 1024)  # Assume bytes

            if max_size_gb is None or size_gb > max_size_gb:
                max_size_gb = size_gb

    return max_rows, max_size_gb


def query_preflight(query: str) -> PreflightResult:
    """
    Validate SQL query using database-specific EXPLAIN commands.

    Different databases support different EXPLAIN syntax:
    - ClickHouse: EXPLAIN (general), EXPLAIN SYNTAX (syntax only)
    - PostgreSQL: EXPLAIN
    - MySQL: EXPLAIN
    - SQLite: EXPLAIN QUERY PLAN

    Args:
        query: SQL query to validate

    Returns:
        PreflightResult with explanation or errors
    """
    # Try to get from cache first
    cache = get_cache()
    cached_result = cache.get("explain", query)
    if cached_result is not None:
        logging.info("Query preflight cache HIT")
        # Reconstruct PreflightResult from cached dict
        return PreflightResult(**cached_result)

    logging.info("Query preflight cache MISS")

    engine = get_db()
    dialect = engine.dialect.name.lower()

    # Determine appropriate EXPLAIN command for the dialect
    if dialect == "clickhouse":
        # Use EXPLAIN ESTIMATE as ClickHouse's EXPLAIN
        explain_command = "EXPLAIN ESTIMATE"
    elif dialect in ("postgresql", "postgres"):
        # PostgreSQL EXPLAIN
        explain_command = "EXPLAIN"
    elif dialect in ("mysql", "mariadb"):
        # MySQL EXPLAIN
        explain_command = "EXPLAIN"
    elif dialect == "sqlite":
        # SQLite uses EXPLAIN QUERY PLAN
        explain_command = "EXPLAIN QUERY PLAN"
    else:
        # For unknown dialects, try standard EXPLAIN
        explain_command = "EXPLAIN"

    with engine.connect() as conn:
        try:
            # Execute EXPLAIN to validate query
            res = conn.execute(text(f"{explain_command} {query}"))
            columns = res.keys()
            rows = [dict(zip(columns, row)) for row in res.fetchall()]

            # Try to parse estimates based on database dialect
            estimated_rows, estimated_size_gb = None, None
            if dialect == "trino":
                estimated_rows, estimated_size_gb = parse_trino_estimates(rows)
            elif dialect == "clickhouse":
                estimated_rows, estimated_size_gb = parse_clickhouse_estimates(rows)

            result = PreflightResult(
                explanation=rows,
                estimated_rows=estimated_rows,
                estimated_output_size_gb=estimated_size_gb,
            )

            # Cache the result
            cache.set("explain", result.model_dump(), CACHE_TTL["explain"], query)
            logging.info("Query preflight cached")

            return result

        except Exception as e:
            error_result = PreflightResult(error=f"SQL error: {str(e)}")
            # Also cache errors (with shorter TTL) to avoid repeated
            # validation of bad queries
            cache.set("explain", error_result.model_dump(), 60, query)
            return error_result
