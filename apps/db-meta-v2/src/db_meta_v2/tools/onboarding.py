"""Onboarding MCP tools."""

from sg_models import OnboardingPhase, TableDescriptionStatus

from db_meta_v2.config import get_settings
from db_meta_v2.db.connection import test_connection
from db_meta_v2.db.introspection import get_columns, get_schemas, get_table_sample, get_tables
from db_meta_v2.onboarding.ignore import load_ignore_patterns
from db_meta_v2.onboarding.schema_store import (
    create_initial_schema,
    get_next_pending_table,
    load_schema_descriptions,
    save_schema_descriptions,
    update_table_description,
)
from db_meta_v2.onboarding.state import (
    create_initial_state,
    delete_state,
    load_state,
    save_state,
)


async def _onboarding_status(provider_id: str | None = None) -> dict:
    """Get current onboarding status for a provider.

    Args:
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Current onboarding state and next action
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    state = load_state(provider_id)

    if state is None:
        return {
            "provider_id": provider_id,
            "status": "not_started",
            "phase": None,
            "progress": 0,
            "next_action": "Call onboarding_start to begin onboarding",
        }

    # Load schema descriptions to get counts
    schema = load_schema_descriptions(provider_id)
    tables_described = 0
    if schema:
        counts = schema.count_by_status()
        tables_described = counts.get("approved", 0) + counts.get("skipped", 0)

    return {
        "provider_id": provider_id,
        "status": state.phase.value,
        "phase": state.phase.value,
        "progress": state.progress_percentage(tables_described),
        "next_action": state.next_action(),
        "tables_total": state.tables_total,
        "tables_described": tables_described,
        "rules_captured": state.rules_captured,
        "examples_added": state.examples_added,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "last_updated_at": state.last_updated_at.isoformat() if state.last_updated_at else None,
    }


async def _onboarding_start(provider_id: str | None = None) -> dict:
    """Start onboarding flow for a provider.

    This will:
    1. Test database connection
    2. Detect SQL dialect
    3. Discover schemas and tables
    4. Create initial schema_descriptions.yaml with all tables
    5. Create onboarding state for progress tracking

    Args:
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Onboarding initialization result
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    # Check if already started
    existing = load_state(provider_id)
    if existing is not None:
        return {
            "started": False,
            "provider_id": provider_id,
            "error": f"Onboarding already started (phase: {existing.phase.value}). "
            "Use onboarding_status to check progress or onboarding_reset to start over.",
        }

    # Test connection
    conn_result = test_connection()
    if not conn_result["connected"]:
        return {
            "started": False,
            "provider_id": provider_id,
            "error": f"Database connection failed: {conn_result['error']}",
        }

    # Create initial state
    state = create_initial_state(provider_id)
    state.database_url_configured = True
    state.connection_verified = True
    state.dialect_detected = conn_result["dialect"]
    state.phase = OnboardingPhase.INIT

    # Load ignore patterns
    ignore = load_ignore_patterns(provider_id)

    # Discover schemas (filter out ignored schemas)
    try:
        schemas = get_schemas()
        schemas = ignore.filter_schemas(schemas)
        state.schemas_discovered = schemas
    except Exception:
        state.schemas_discovered = []

    # Discover tables with columns
    all_tables = []
    try:
        for schema in state.schemas_discovered:
            tables = get_tables(schema)
            tables = ignore.filter_tables(tables)

            for t in tables:
                # Get columns for each table
                try:
                    columns = get_columns(t["name"], schema)
                except Exception:
                    columns = []

                all_tables.append(
                    {
                        "name": t["name"],
                        "schema": schema,
                        "full_name": t["full_name"],
                        "columns": columns,
                    }
                )

        state.tables_discovered = [t["full_name"] for t in all_tables]
        state.tables_total = len(all_tables)
    except Exception:
        state.tables_discovered = []
        state.tables_total = 0

    # Create schema_descriptions.yaml with all discovered tables
    schema = create_initial_schema(
        provider_id=provider_id,
        dialect=state.dialect_detected,
        tables=all_tables,
    )
    schema_result = save_schema_descriptions(schema)
    if not schema_result["saved"]:
        return {
            "started": False,
            "provider_id": provider_id,
            "error": f"Failed to save schema descriptions: {schema_result['error']}",
        }

    # Move to schema phase
    state.phase = OnboardingPhase.SCHEMA

    # Save state
    save_result = save_state(state)
    if not save_result["saved"]:
        return {
            "started": False,
            "provider_id": provider_id,
            "error": f"Failed to save state: {save_result['error']}",
        }

    return {
        "started": True,
        "provider_id": provider_id,
        "dialect": state.dialect_detected,
        "schemas_found": len(state.schemas_discovered),
        "tables_found": state.tables_total,
        "phase": state.phase.value,
        "schema_file": schema_result["file_path"],
        "next_action": state.next_action(),
    }


async def _onboarding_reset(provider_id: str | None = None) -> dict:
    """Reset onboarding state for a provider.

    This deletes onboarding progress but keeps schema_descriptions.yaml.
    Use with caution.

    Args:
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Reset result
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    result = delete_state(provider_id)

    if result["deleted"]:
        return {
            "reset": True,
            "provider_id": provider_id,
            "message": "Onboarding state deleted. Call onboarding_start to begin again.",
            "note": "schema_descriptions.yaml was preserved. Delete manually if needed.",
        }
    else:
        return {
            "reset": False,
            "provider_id": provider_id,
            "error": result["error"],
        }


async def _onboarding_next(provider_id: str | None = None) -> dict:
    """Get the next table to describe in the onboarding flow.

    Returns table schema and sample data to help generate a description.

    Args:
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Next table info with columns and sample data
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    state = load_state(provider_id)

    if state is None:
        return {
            "error": "Onboarding not started. Call onboarding_start first.",
        }

    if state.phase != OnboardingPhase.SCHEMA:
        return {
            "error": f"Not in schema phase. Current phase: {state.phase.value}",
            "phase": state.phase.value,
        }

    # Load schema descriptions
    schema = load_schema_descriptions(provider_id)
    if schema is None:
        return {
            "error": "Schema descriptions not found. Call onboarding_start first.",
        }

    # Find next pending table
    next_table = get_next_pending_table(schema)

    if next_table is None:
        # All tables described, move to next phase
        state.phase = OnboardingPhase.DOMAIN
        save_state(state)

        counts = schema.count_by_status()
        return {
            "complete": True,
            "message": "All tables have been described. Moving to domain model phase.",
            "phase": state.phase.value,
            "tables_approved": counts.get("approved", 0),
            "tables_skipped": counts.get("skipped", 0),
        }

    # Update current table in state
    state.current_table = next_table.full_name
    save_state(state)

    # Get sample data
    try:
        sample = get_table_sample(next_table.name, next_table.schema_name, limit=3)
    except Exception:
        sample = []

    # Count progress
    counts = schema.count_by_status()
    described = counts.get("approved", 0) + counts.get("skipped", 0)
    remaining = counts.get("pending", 0)

    return {
        "table_name": next_table.full_name,
        "schema": next_table.schema_name,
        "table": next_table.name,
        "columns": [
            {"name": c.name, "type": c.type, "description": c.description}
            for c in next_table.columns
        ],
        "column_count": len(next_table.columns),
        "sample_rows": sample,
        "progress": f"{described}/{state.tables_total}",
        "remaining": remaining,
        "instruction": "Review this table and provide a description. "
        "Then call onboarding_approve with your description, "
        "or onboarding_skip to skip this table.",
    }


async def _onboarding_approve(
    description: str,
    column_descriptions: dict[str, str] | None = None,
    provider_id: str | None = None,
) -> dict:
    """Approve and save a table description.

    Args:
        description: Description of the table
        column_descriptions: Optional dict of column_name -> description
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Approval result
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    state = load_state(provider_id)

    if state is None:
        return {"error": "Onboarding not started."}

    if state.current_table is None:
        return {"error": "No table pending. Call onboarding_next first."}

    # Load and update schema descriptions
    schema = load_schema_descriptions(provider_id)
    if schema is None:
        return {"error": "Schema descriptions not found."}

    updated = update_table_description(
        schema,
        state.current_table,
        description,
        column_descriptions,
        TableDescriptionStatus.APPROVED,
    )

    if not updated:
        return {"error": f"Table {state.current_table} not found in schema."}

    # Save schema descriptions
    save_schema_descriptions(schema)

    # Clear current table
    state.current_table = None
    save_state(state)

    counts = schema.count_by_status()
    tables_described = counts.get("approved", 0) + counts.get("skipped", 0)

    return {
        "approved": True,
        "table_name": state.current_table,
        "tables_described": tables_described,
        "tables_total": state.tables_total,
        "progress": f"{tables_described}/{state.tables_total}",
        "next_action": "Call onboarding_next for the next table.",
    }


async def _onboarding_skip(provider_id: str | None = None) -> dict:
    """Skip the current table without describing it.

    Args:
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Skip result
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    state = load_state(provider_id)

    if state is None:
        return {"error": "Onboarding not started."}

    if state.current_table is None:
        return {"error": "No table pending. Call onboarding_next first."}

    # Load and update schema descriptions
    schema = load_schema_descriptions(provider_id)
    if schema is None:
        return {"error": "Schema descriptions not found."}

    skipped_table = state.current_table

    updated = update_table_description(
        schema,
        state.current_table,
        None,
        None,
        TableDescriptionStatus.SKIPPED,
    )

    if not updated:
        return {"error": f"Table {state.current_table} not found in schema."}

    # Save schema descriptions
    save_schema_descriptions(schema)

    # Clear current table
    state.current_table = None
    save_state(state)

    counts = schema.count_by_status()
    tables_described = counts.get("approved", 0) + counts.get("skipped", 0)

    return {
        "skipped": True,
        "table_name": skipped_table,
        "tables_described": tables_described,
        "tables_total": state.tables_total,
        "next_action": "Call onboarding_next for the next table.",
    }


async def _onboarding_bulk_approve(
    generate_descriptions: bool = True,
    provider_id: str | None = None,
) -> dict:
    """Bulk approve all remaining tables.

    This marks all pending tables as approved, optionally generating
    placeholder descriptions based on table/column names. Users can then
    edit the descriptions later in schema_descriptions.yaml.

    Args:
        generate_descriptions: If True, generate placeholder descriptions
            from table and column names. If False, leave descriptions empty.
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Bulk approval result with count of tables approved
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    state = load_state(provider_id)

    if state is None:
        return {"error": "Onboarding not started. Call onboarding_start first."}

    if state.phase != OnboardingPhase.SCHEMA:
        return {
            "error": f"Not in schema phase. Current phase: {state.phase.value}",
            "phase": state.phase.value,
        }

    # Load schema descriptions
    schema = load_schema_descriptions(provider_id)
    if schema is None:
        return {"error": "Schema descriptions not found."}

    # Count pending before
    counts_before = schema.count_by_status()
    pending_count = counts_before.get("pending", 0)

    if pending_count == 0:
        return {
            "approved": 0,
            "message": "No tables remaining to approve.",
            "tables_described": counts_before.get("approved", 0) + counts_before.get("skipped", 0),
            "tables_total": state.tables_total,
        }

    # Clear current table if set
    state.current_table = None

    # Approve all pending tables
    approved_count = 0
    for table in schema.tables:
        if table.status != TableDescriptionStatus.PENDING:
            continue

        description = None
        column_descriptions = {}

        if generate_descriptions:
            # Generate placeholder description from table name
            readable_name = table.name.replace("_", " ").title()
            description = f"Table: {readable_name}"

            # Generate column descriptions
            for col in table.columns:
                readable_col = col.name.replace("_", " ")
                col_type = col.type or "unknown"
                column_descriptions[col.name] = f"{readable_col} ({col_type})"

        update_table_description(
            schema,
            table.full_name,
            description,
            column_descriptions if generate_descriptions else None,
            TableDescriptionStatus.APPROVED,
        )
        approved_count += 1

    # Save schema descriptions
    schema_result = save_schema_descriptions(schema)

    # Move to next phase
    state.phase = OnboardingPhase.DOMAIN
    save_state(state)

    counts_after = schema.count_by_status()

    return {
        "approved": approved_count,
        "tables_described": counts_after.get("approved", 0) + counts_after.get("skipped", 0),
        "tables_total": state.tables_total,
        "phase": state.phase.value,
        "message": f"Bulk approved {approved_count} tables. "
        "Descriptions can be edited in schema_descriptions.yaml.",
        "schema_file": schema_result.get("file_path"),
    }
