"""
Table details introspection for granular schema exploration.

This module provides functions to fetch detailed metadata for specific tables,
including:
- Primary key and foreign key relationships
- Column cardinality and distinct values
- Min/max ranges for numeric/date columns
- Index information

These functions are designed to be called on-demand for specific tables,
rather than fetching all metadata upfront.
"""

import logging
from typing import Any

from sqlalchemy import inspect, text

from dbmeta_app.api.model import (
    ColumnDetails,
    ForeignKeyInfo,
    GetTableDetailsRequest,
    GetTableDetailsResponse,
    IndexInfo,
    TableDetails,
    TableDetailsInclude,
)
from dbmeta_app.cache import CACHE_TTL, get_cache
from dbmeta_app.config import get_settings
from dbmeta_app.prompt_items.db_struct import (
    _get_table_metadata_with_fallback,
    get_structured_schema,
)
from dbmeta_app.prompt_items.utils import compute_content_hash
from dbmeta_app.wh_db.db import get_db


def _parse_table_name(full_table_name: str) -> tuple[str | None, str | None, str]:
    """
    Parse a fully qualified table name into catalog, schema, and table parts.

    Args:
        full_table_name: Table name like "catalog.schema.table" or "schema.table"

    Returns:
        Tuple of (catalog, schema, table)
    """
    parts = full_table_name.split(".")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        return None, parts[0], parts[1]
    else:
        return None, None, full_table_name


def _get_primary_key(
    engine, inspector, conn, catalog: str | None, schema: str | None, table: str
) -> list[str] | None:
    """
    Get primary key columns for a table.

    Args:
        engine: SQLAlchemy engine
        inspector: SQLAlchemy inspector
        conn: Active database connection
        catalog: Catalog name (for Trino)
        schema: Schema name
        table: Table name

    Returns:
        List of primary key column names, or None if no PK defined
    """
    dialect = engine.dialect.name.lower()

    try:
        if dialect == "trino" and catalog and schema:
            # Trino doesn't expose PK via inspector, try information_schema
            # Note: Trino may not have this info for all connectors
            return None
        elif dialect == "clickhouse":
            # ClickHouse: Query system.tables for primary key
            result = conn.execute(
                text(
                    f"""
                SELECT primary_key
                FROM system.tables
                WHERE database = '{schema or "default"}'
                  AND name = '{table}'
                """
                )
            )
            row = result.fetchone()
            if row and row[0]:
                # primary_key is a comma-separated string
                return [col.strip() for col in row[0].split(",")]
            return None
        else:
            # Standard SQLAlchemy inspector
            pk_info = inspector.get_pk_constraint(table, schema=schema)
            if pk_info and pk_info.get("constrained_columns"):
                return pk_info["constrained_columns"]
            return None
    except Exception as e:
        logging.warning(f"Failed to get primary key for {table}: {e}")
        return None


def _get_foreign_keys(
    engine, inspector, conn, catalog: str | None, schema: str | None, table: str
) -> list[ForeignKeyInfo]:
    """
    Get foreign key relationships for a table.

    Args:
        engine: SQLAlchemy engine
        inspector: SQLAlchemy inspector
        conn: Active database connection
        catalog: Catalog name (for Trino)
        schema: Schema name
        table: Table name

    Returns:
        List of ForeignKeyInfo objects
    """
    dialect = engine.dialect.name.lower()
    foreign_keys = []

    try:
        if dialect == "trino" and catalog and schema:
            # Trino doesn't expose FK via inspector for most connectors
            return []
        elif dialect == "clickhouse":
            # ClickHouse doesn't have traditional foreign keys
            return []
        else:
            # Standard SQLAlchemy inspector
            fk_list = inspector.get_foreign_keys(table, schema=schema)
            for fk in fk_list:
                # Build referred table name
                ref_schema = fk.get("referred_schema")
                ref_table = fk.get("referred_table")
                if ref_schema:
                    referred_table = f"{ref_schema}.{ref_table}"
                else:
                    referred_table = ref_table

                foreign_keys.append(
                    ForeignKeyInfo(
                        columns=fk.get("constrained_columns", []),
                        referred_table=referred_table,
                        referred_columns=fk.get("referred_columns", []),
                        constraint_name=fk.get("name"),
                    )
                )
    except Exception as e:
        logging.warning(f"Failed to get foreign keys for {table}: {e}")

    return foreign_keys


def _get_indexes(
    engine, inspector, conn, catalog: str | None, schema: str | None, table: str
) -> list[IndexInfo]:
    """
    Get index information for a table.

    Args:
        engine: SQLAlchemy engine
        inspector: SQLAlchemy inspector
        conn: Active database connection
        catalog: Catalog name (for Trino)
        schema: Schema name
        table: Table name

    Returns:
        List of IndexInfo objects
    """
    dialect = engine.dialect.name.lower()
    indexes = []

    try:
        if dialect == "trino" and catalog and schema:
            # Trino doesn't expose indexes via inspector
            return []
        elif dialect == "clickhouse":
            # ClickHouse indexes are in system.data_skipping_indices
            result = conn.execute(
                text(
                    f"""
                SELECT name, expr, type
                FROM system.data_skipping_indices
                WHERE database = '{schema or "default"}'
                  AND table = '{table}'
                """
                )
            )
            for row in result.fetchall():
                indexes.append(
                    IndexInfo(
                        name=row[0],
                        columns=[row[1]],  # expr is the column expression
                        is_unique=False,  # ClickHouse skip indices aren't unique
                        is_primary=False,
                    )
                )
        else:
            # Standard SQLAlchemy inspector
            idx_list = inspector.get_indexes(table, schema=schema)
            for idx in idx_list:
                indexes.append(
                    IndexInfo(
                        name=idx.get("name", ""),
                        columns=idx.get("column_names", []),
                        is_unique=idx.get("unique", False),
                        is_primary=False,
                    )
                )
    except Exception as e:
        logging.warning(f"Failed to get indexes for {table}: {e}")

    return indexes


def _get_row_count_estimate(
    engine, conn, catalog: str | None, schema: str | None, table: str
) -> int | None:
    """
    Get estimated row count for a table.

    Uses database-specific system tables for fast estimates.
    """
    dialect = engine.dialect.name.lower()

    try:
        if dialect == "clickhouse":
            result = conn.execute(
                text(
                    f"""
                SELECT total_rows
                FROM system.tables
                WHERE database = '{schema or "default"}'
                  AND name = '{table}'
                """
                )
            )
            row = result.fetchone()
            return int(row[0]) if row and row[0] else None
        elif dialect in ("postgresql", "postgres"):
            # Use pg_stat_user_tables for estimate
            result = conn.execute(
                text(
                    f"""
                SELECT n_live_tup
                FROM pg_stat_user_tables
                WHERE schemaname = '{schema or "public"}'
                  AND relname = '{table}'
                """
                )
            )
            row = result.fetchone()
            return int(row[0]) if row and row[0] else None
        elif dialect == "trino":
            # Trino: Try to get from system stats (may not be available)
            return None
        else:
            return None
    except Exception as e:
        logging.warning(f"Failed to get row count estimate for {table}: {e}")
        return None


def _get_column_cardinality(
    engine,
    conn,
    full_table_name: str,
    column_name: str,
    sample_size: int,
) -> int | None:
    """
    Get approximate distinct value count for a column.

    Uses sampling for large tables to avoid full table scans.
    """
    dialect = engine.dialect.name.lower()

    try:
        if dialect == "clickhouse":
            # ClickHouse: Use uniqExact with SAMPLE for efficiency
            query = f"""
                SELECT uniqExact({column_name})
                FROM {full_table_name}
                SAMPLE {min(sample_size, 100000)}
            """
        elif dialect in ("postgresql", "postgres"):
            # PostgreSQL: Use pg_stats for pre-computed stats if available
            parts = full_table_name.split(".")
            schema = parts[0] if len(parts) > 1 else "public"
            table = parts[-1]

            # First try pg_stats
            result = conn.execute(
                text(
                    f"""
                SELECT n_distinct
                FROM pg_stats
                WHERE schemaname = '{schema}'
                  AND tablename = '{table}'
                  AND attname = '{column_name}'
                """
                )
            )
            row = result.fetchone()
            if row and row[0]:
                n_distinct = row[0]
                if n_distinct > 0:
                    return int(n_distinct)
                elif n_distinct < 0:
                    # Negative means fraction of rows, need row count
                    # For now, return None
                    return None

            # Fallback to query with limit
            query = f"""
                SELECT COUNT(DISTINCT {column_name})
                FROM (
                    SELECT {column_name} FROM {full_table_name} LIMIT {sample_size}
                ) sub
            """
        elif dialect == "trino":
            # Trino: Use approx_distinct for efficiency
            query = f"""
                SELECT approx_distinct({column_name})
                FROM {full_table_name}
            """
        else:
            # Generic fallback
            query = f"""
                SELECT COUNT(DISTINCT {column_name})
                FROM (
                    SELECT {column_name} FROM {full_table_name} LIMIT {sample_size}
                ) sub
            """

        result = conn.execute(text(query))
        row = result.fetchone()
        return int(row[0]) if row and row[0] else None

    except Exception as e:
        logging.warning(
            f"Failed to get cardinality for {full_table_name}.{column_name}: {e}"
        )
        return None


def _get_distinct_values(
    engine,
    conn,
    full_table_name: str,
    column_name: str,
    limit: int,
) -> list[str] | None:
    """
    Get distinct values for a low-cardinality column.
    """
    try:
        query = f"""
            SELECT DISTINCT {column_name}
            FROM {full_table_name}
            LIMIT {limit}
        """
        result = conn.execute(text(query))
        values = [str(row[0]) for row in result.fetchall() if row[0] is not None]
        return values if values else None
    except Exception as e:
        logging.warning(
            f"Failed to get distinct values for {full_table_name}.{column_name}: {e}"
        )
        return None


def _get_column_range(
    engine,
    conn,
    full_table_name: str,
    column_name: str,
    column_type: str,
) -> tuple[str | None, str | None]:
    """
    Get min/max values for numeric or date columns.

    Args:
        engine: SQLAlchemy engine
        conn: Active database connection
        full_table_name: Fully qualified table name
        column_name: Column name
        column_type: Column data type (to determine if range is applicable)

    Returns:
        Tuple of (min_value, max_value) as strings, or (None, None)
    """
    # Determine if column type supports min/max
    type_lower = column_type.lower()
    supports_range = any(
        t in type_lower
        for t in (
            "int",
            "float",
            "double",
            "decimal",
            "numeric",
            "date",
            "time",
            "timestamp",
            "datetime",
        )
    )

    if not supports_range:
        return None, None

    try:
        query = f"""
            SELECT MIN({column_name}), MAX({column_name})
            FROM {full_table_name}
        """
        result = conn.execute(text(query))
        row = result.fetchone()
        if row:
            min_val = str(row[0]) if row[0] is not None else None
            max_val = str(row[1]) if row[1] is not None else None
            return min_val, max_val
        return None, None
    except Exception as e:
        logging.warning(f"Failed to get range for {full_table_name}.{column_name}: {e}")
        return None, None


def _is_column_stat_enabled(column_metadata: dict[str, Any], column_type: str) -> bool:
    """
    Determine if stats should be collected for a column based on YAML config.

    Default behavior:
    - Auto-fetch for timestamp, date, int, float types
    - Skip for text, varchar(>256), blob types
    - Override with explicit `stats: true/false` in YAML
    """
    # Check explicit YAML override
    if "stats" in column_metadata:
        return column_metadata["stats"]

    # Default based on type
    type_lower = column_type.lower()

    # Skip for text/blob types
    skip_types = ("text", "blob", "bytea", "binary", "json", "xml")
    if any(t in type_lower for t in skip_types):
        return False

    # Skip for large varchar
    if "varchar" in type_lower or "char" in type_lower:
        # Try to extract size
        import re

        match = re.search(r"\((\d+)\)", type_lower)
        if match:
            size = int(match.group(1))
            if size > 256:
                return False

    # Enable for numeric/date types
    stat_types = (
        "int",
        "float",
        "double",
        "decimal",
        "numeric",
        "date",
        "time",
        "timestamp",
        "datetime",
    )
    if any(t in type_lower for t in stat_types):
        return True

    return False


def get_table_details(request: GetTableDetailsRequest) -> GetTableDetailsResponse:
    """
    Get detailed metadata for specific tables.

    This is the main entry point for granular schema exploration.
    Fetches on-demand metadata including relationships, cardinality, and ranges.

    Args:
        request: GetTableDetailsRequest with tables and options

    Returns:
        GetTableDetailsResponse with detailed table metadata
    """
    settings = get_settings()
    engine = get_db()
    inspector = inspect(engine)

    # Check cache first
    cache = get_cache()
    profile = settings.default_profile
    include_key = ",".join(sorted(i.value for i in request.include))
    cache_key_args = (
        profile,
        ",".join(sorted(request.tables)),
        include_key,
        request.cardinality_threshold,
    )

    cached_result = cache.get("table_details", *cache_key_args)
    if cached_result is not None:
        logging.info(f"Table details cache HIT for tables={request.tables}")
        return GetTableDetailsResponse(**cached_result)

    logging.info(f"Table details cache MISS for tables={request.tables}")

    # Get structured schema for column info
    structured_schema = get_structured_schema(engine, settings, with_examples=False)

    # Load YAML descriptions for additional metadata
    import pathlib

    from dbmeta_app.prompt_assembler.prompt_packs import (
        assemble_effective_tree,
        load_yaml,
    )

    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    tree = assemble_effective_tree(repo_root, profile, settings.client, settings.env)
    yaml_file = load_yaml(tree, "resources/schema_descriptions.yaml")
    descriptions = yaml_file.get("profiles", {}).get(profile, {})

    tables_result = []

    with engine.connect() as conn:
        for full_table_name in request.tables:
            # Check if table exists in schema
            if full_table_name not in structured_schema:
                logging.warning(f"Table {full_table_name} not found in schema")
                continue

            table_schema = structured_schema[full_table_name]
            catalog, schema, table = _parse_table_name(full_table_name)

            # Get table metadata from YAML
            table_metadata = _get_table_metadata_with_fallback(
                descriptions, table, schema, catalog
            )

            # Collect table details based on include options
            primary_key = None
            foreign_keys = []
            indexes = []
            row_count = None

            if TableDetailsInclude.relationships in request.include:
                primary_key = _get_primary_key(
                    engine, inspector, conn, catalog, schema, table
                )
                foreign_keys = _get_foreign_keys(
                    engine, inspector, conn, catalog, schema, table
                )

            if TableDetailsInclude.indexes in request.include:
                indexes = _get_indexes(engine, inspector, conn, catalog, schema, table)

            # Get row count estimate (always useful)
            row_count = _get_row_count_estimate(engine, conn, catalog, schema, table)

            # Build column details with stats
            columns_details = []
            pk_columns = set(primary_key) if primary_key else set()
            fk_columns = set()
            for fk in foreign_keys:
                fk_columns.update(fk.columns)

            for col_data in table_schema.get("columns", []):
                col_name = col_data.get("name", "")
                col_type = col_data.get("type", "")
                col_metadata = table_metadata.get("columns", {}).get(col_name, {})

                col_detail = ColumnDetails(
                    name=col_name,
                    type=col_type,
                    nullable=col_data.get("nullable", True),
                    description=col_data.get("description"),
                    example=col_data.get("example"),
                    is_primary_key=col_name in pk_columns,
                    is_foreign_key=col_name in fk_columns,
                )

                # Collect stats based on include options
                should_get_stats = _is_column_stat_enabled(col_metadata, col_type)

                if (
                    TableDetailsInclude.cardinality in request.include
                    and should_get_stats
                ):
                    cardinality = _get_column_cardinality(
                        engine, conn, full_table_name, col_name, request.sample_size
                    )
                    if cardinality is not None:
                        col_detail.distinct_count = cardinality
                        col_detail.is_low_cardinality = (
                            cardinality <= request.cardinality_threshold
                        )

                        # Get distinct values for low-cardinality columns
                        if (
                            TableDetailsInclude.low_cardinality_values
                            in request.include
                            and col_detail.is_low_cardinality
                        ):
                            distinct_values = _get_distinct_values(
                                engine,
                                conn,
                                full_table_name,
                                col_name,
                                request.cardinality_threshold,
                            )
                            col_detail.distinct_values = distinct_values

                if TableDetailsInclude.ranges in request.include and should_get_stats:
                    min_val, max_val = _get_column_range(
                        engine, conn, full_table_name, col_name, col_type
                    )
                    col_detail.min_value = min_val
                    col_detail.max_value = max_val

                columns_details.append(col_detail)

            table_details = TableDetails(
                table_name=full_table_name,
                description=table_schema.get("description"),
                row_count_estimate=row_count,
                primary_key=primary_key,
                foreign_keys=foreign_keys,
                indexes=indexes,
                columns=columns_details,
            )
            tables_result.append(table_details)

    # Compute content hash for lineage
    import json

    content_str = json.dumps(
        [t.model_dump(mode="json") for t in tables_result], sort_keys=True
    )
    content_hash = compute_content_hash(content_str)

    response = GetTableDetailsResponse(
        tables=tables_result,
        content_hash=content_hash,
        metadata={
            "profile": profile,
            "include": [i.value for i in request.include],
            "cardinality_threshold": request.cardinality_threshold,
            "sample_size": request.sample_size,
        },
    )

    # Cache the result
    cache.set(
        "table_details",
        response.model_dump(mode="json"),
        CACHE_TTL.get("table_details", 3600),
        *cache_key_args,
    )
    logging.info(f"Table details cached for tables={request.tables}")

    return response
