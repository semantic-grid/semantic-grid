import pathlib
from typing import Any, Dict

import yaml
from pydantic import BaseModel, RootModel
from sqlalchemy import inspect, text

from dbmeta_app.api.model import PromptItem, PromptItemType
from dbmeta_app.config import get_settings
from dbmeta_app.prompt_assembler.prompt_packs import assemble_effective_tree, load_yaml
from dbmeta_app.wh_db.db import get_db


class DbColumn(BaseModel):
    name: str
    type: str
    description: str | None = None
    example: str | None = None


class DbTable(BaseModel):
    columns: dict[str, DbColumn]
    description: str | None = None


class DbSchema(RootModel[dict[str, DbTable]]):
    def __setitem__(self, key: str, value: DbTable) -> None:
        self.root[key] = value

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
        for idx, table in enumerate(inspector.get_table_names()):
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

            res = conn.execute(text(f"SELECT * FROM {table} LIMIT 5"))
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

    return PromptItem(
        text=generate_schema_prompt(
            engine,
            settings,
            with_examples=settings.data_examples,
        ),
        prompt_item_type=PromptItemType.db_struct,
        score=100_000,
    )


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

    result: DbSchema = DbSchema({})

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

            res = conn.execute(text(f"SELECT * FROM {table} LIMIT 5"))

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
    engine = get_db()
    with engine.connect() as conn:
        try:
            res = conn.execute(text(f"EXPLAIN ESTIMATE {query}"))
            columns = res.keys()
            rows = [dict(zip(columns, row)) for row in res.fetchall()]
            return PreflightResult(explanation=rows)

        except Exception as e:
            return PreflightResult(error=f"SQL error: {str(e)}")
