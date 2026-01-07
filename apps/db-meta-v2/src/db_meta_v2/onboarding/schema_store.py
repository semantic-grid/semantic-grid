"""Schema descriptions file handler."""

from datetime import UTC, datetime
from pathlib import Path

import yaml
from sg_models import (
    ColumnDescription,
    SchemaDescriptions,
    TableDescription,
    TableDescriptionStatus,
)

from db_meta_v2.onboarding.state import get_provider_dir


def get_schema_file_path(provider_id: str) -> Path:
    """Get path to the schema descriptions file."""
    return get_provider_dir(provider_id) / "schema_descriptions.yaml"


def load_schema_descriptions(provider_id: str) -> SchemaDescriptions | None:
    """Load schema descriptions from YAML file.

    Args:
        provider_id: Provider identifier

    Returns:
        SchemaDescriptions if found, None otherwise
    """
    schema_file = get_schema_file_path(provider_id)

    if not schema_file.exists():
        return None

    try:
        with open(schema_file) as f:
            data = yaml.safe_load(f)

        return SchemaDescriptions.model_validate(data)
    except Exception:
        return None


def save_schema_descriptions(schema: SchemaDescriptions) -> dict:
    """Save schema descriptions to YAML file.

    Args:
        schema: SchemaDescriptions to save

    Returns:
        Dict with save status
    """
    try:
        provider_dir = get_provider_dir(schema.provider_id)
        provider_dir.mkdir(parents=True, exist_ok=True)

        schema.generated_at = datetime.now(UTC)

        # Convert to dict for YAML serialization
        schema_dict = schema.model_dump(mode="json", by_alias=True)

        schema_file = get_schema_file_path(schema.provider_id)
        with open(schema_file, "w") as f:
            yaml.dump(
                schema_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        return {
            "saved": True,
            "file_path": str(schema_file),
            "error": None,
        }
    except Exception as e:
        return {
            "saved": False,
            "file_path": None,
            "error": str(e),
        }


def create_initial_schema(
    provider_id: str,
    dialect: str | None,
    tables: list[dict],
) -> SchemaDescriptions:
    """Create initial schema descriptions with discovered tables.

    Args:
        provider_id: Provider identifier
        dialect: SQL dialect
        tables: List of table dicts with 'name', 'schema', 'full_name', 'columns'

    Returns:
        New SchemaDescriptions instance
    """
    table_descriptions = []

    for t in tables:
        columns = []
        for col in t.get("columns", []):
            columns.append(
                ColumnDescription(
                    name=col.get("name", ""),
                    type=col.get("type"),
                    description=None,
                )
            )

        table_descriptions.append(
            TableDescription(
                name=t.get("name", ""),
                schema_name=t.get("schema", "public"),
                full_name=t.get("full_name"),
                description=None,
                status=TableDescriptionStatus.PENDING,
                columns=columns,
            )
        )

    return SchemaDescriptions(
        version="1.0.0",
        provider_id=provider_id,
        dialect=dialect,
        generated_at=datetime.now(UTC),
        tables=table_descriptions,
    )


def update_table_description(
    schema: SchemaDescriptions,
    full_name: str,
    description: str | None,
    column_descriptions: dict[str, str] | None = None,
    status: TableDescriptionStatus = TableDescriptionStatus.APPROVED,
) -> bool:
    """Update a table's description in the schema.

    Args:
        schema: SchemaDescriptions to update
        full_name: Full table name (schema.table)
        description: Table description
        column_descriptions: Optional dict of column_name -> description
        status: New status for the table

    Returns:
        True if table was found and updated
    """
    for table in schema.tables:
        if table.full_name == full_name:
            table.description = description
            table.status = status

            if column_descriptions:
                for col in table.columns:
                    if col.name in column_descriptions:
                        col.description = column_descriptions[col.name]

            return True

    return False


def get_next_pending_table(schema: SchemaDescriptions) -> TableDescription | None:
    """Get the next table that needs description.

    Args:
        schema: SchemaDescriptions to search

    Returns:
        Next pending TableDescription or None if all done
    """
    for table in schema.tables:
        if table.status == TableDescriptionStatus.PENDING:
            return table
    return None
