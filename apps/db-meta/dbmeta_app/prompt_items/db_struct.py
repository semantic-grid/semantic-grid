import pathlib
from typing import Any, Dict

import yaml
from pydantic import BaseModel, RootModel
from sqlalchemy import inspect, text

from dbmeta_app.api.model import PromptItem, PromptItemType
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

    if dialect == 'clickhouse':
        # ClickHouse: SAMPLE is very efficient (samples data blocks)
        # SAMPLE 0.01 = sample 1% of data blocks
        return f"SELECT * FROM {table} SAMPLE 0.01 LIMIT {limit}"
    elif dialect == 'postgresql':
        # PostgreSQL: TABLESAMPLE BERNOULLI samples individual rows
        # BERNOULLI(1) = 1% row-level sampling
        # Note: SYSTEM is faster but may return 0 rows on small tables
        return f"SELECT * FROM {table} TABLESAMPLE BERNOULLI (1) LIMIT {limit}"
    elif dialect == 'duckdb':
        # DuckDB: USING SAMPLE is very fast
        return f"SELECT * FROM {table} USING SAMPLE 1% LIMIT {limit}"
    elif dialect in ('mysql', 'mariadb'):
        # MySQL: Just use LIMIT (ORDER BY RAND() is extremely slow on large tables)
        # This gets rows in storage order, which is usually fine for sample data
        return f"SELECT * FROM {table} LIMIT {limit}"
    elif dialect == 'sqlite':
        # SQLite: Simple LIMIT (RANDOM() is slow, but SQLite typically has small datasets)
        return f"SELECT * FROM {table} LIMIT {limit}"
    elif dialect == 'mssql':
        # SQL Server: TABLESAMPLE can be used but syntax is different
        # Using simple LIMIT-style query (TOP in SQL Server)
        return f"SELECT TOP {limit} * FROM {table}"
    elif dialect == 'oracle':
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


def load_yaml_descriptions(yaml_file):
    """Loads table and column descriptions from a YAML file."""
    with open(yaml_file, "r") as file:
        return yaml.safe_load(file)


def generate_schema_prompt(engine, settings, with_examples=False):
    """Generates a human-readable schema description merged with YAML descriptions,
    including examples."""
    inspector = inspect(engine)
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    client = settings.client
    env = settings.env
    profile = settings.default_profile
    tree = assemble_effective_tree(repo_root, profile, client, env)

    file = load_yaml(tree, "resources/schema_descriptions.yaml")
    descriptions = file["profiles"][profile]
    schema_text = "The database contains the following tables:\n\n"

    with engine.connect() as conn:
        table_names = inspector.get_table_names()
        for idx, table in enumerate(table_names):
            # Skip system/internal tables and temp tables
            if table.startswith("_") or table.startswith("temp_"):
                continue

            # Check if the whitelist mode is enabled
            has_whitelist = descriptions.get("whitelist", False)
            has_table_description = descriptions.get("tables", {}).get(table, False)
            # with whitelist mode, only tables in the descriptions are included
            if has_whitelist and not has_table_description:
                continue

            table_metadata = descriptions.get("tables", {}).get(table, {})
            if table_metadata.get("hidden", False):
                continue

            table_description = table_metadata.get(
                "description", f"Stores {table.replace('_', ' ')} data."
            )
            schema_text += f"Table #{idx + 1}. **{table}** ({table_description})\n"

            columns = inspector.get_columns(table)
            for col in columns:
                col_metadata = table_metadata.get("columns", {}).get(col["name"], {})
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
                # Use database-specific optimized sampling
                sample_query = get_sample_query(table, engine)
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

    return schema_text


def get_schema_prompt_item() -> PromptItem:
    settings = get_settings()
    engine = get_db()

    prompt = generate_schema_prompt(
        engine,
        settings,
        with_examples=settings.data_examples,
    )
    items = PromptItem(
        text=prompt,
        prompt_item_type=PromptItemType.db_struct,
        score=100_000,
    )
    return items


def get_db_schema() -> DbSchema:
    settings = get_settings()
    engine = get_db()
    inspector = inspect(engine)
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    client = settings.client
    env = settings.env
    profile = settings.default_profile
    tree = assemble_effective_tree(repo_root, profile, client, env)

    file = load_yaml(tree, "resources/schema_descriptions.yaml")
    descriptions = file["profiles"][profile]

    result: DbSchema = {}

    with engine.connect():
        for idx, table in enumerate(inspector.get_table_names()):
            if table.startswith("_"):  # Skip system/internal tables
                continue

            table_metadata = descriptions.get("tables", {}).get(table, {})
            if table_metadata.get("hidden", False):
                continue

            db_columns = inspector.get_columns(table)
            columns = {}
            for col in db_columns:
                col_metadata = table_metadata.get("columns", {}).get(col["name"], {})
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

            result[table] = DbTable(
                columns=columns,
                description=table_metadata.get("description", None),
            )

    return result


def get_data_samples() -> dict[str, Any]:
    settings = get_settings()
    engine = get_db()
    inspector = inspect(engine)
    descriptions = load_yaml_descriptions(settings.schema_descriptions_file)

    result = {}

    with engine.connect() as conn:
        for idx, table in enumerate(inspector.get_table_names()):
            if table.startswith("_"):  # Skip system/internal tables
                continue

            table_metadata = descriptions.get("tables", {}).get(table, {})
            if table_metadata.get("hidden", False):
                continue

            try:
                # Use database-specific optimized sampling
                sample_query = get_sample_query(table, engine)
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
                result[table] = rows

    return result


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
        PreflightResult with explanation or error
    """
    engine = get_db()
    dialect = engine.dialect.name.lower()

    # Determine appropriate EXPLAIN command for the dialect
    if dialect == 'clickhouse':
        # Use EXPLAIN instead of EXPLAIN ESTIMATE for better compatibility
        # EXPLAIN SYNTAX would be even safer but doesn't return execution info
        explain_command = "EXPLAIN"
    elif dialect in ('postgresql', 'postgres'):
        # PostgreSQL EXPLAIN
        explain_command = "EXPLAIN"
    elif dialect in ('mysql', 'mariadb'):
        # MySQL EXPLAIN
        explain_command = "EXPLAIN"
    elif dialect == 'sqlite':
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
            return PreflightResult(explanation=rows)

        except Exception as e:
            return PreflightResult(error=f"SQL error: {str(e)}")
