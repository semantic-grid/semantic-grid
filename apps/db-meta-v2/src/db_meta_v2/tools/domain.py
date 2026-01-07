"""Domain model MCP tools."""

import re
from collections import defaultdict
from pathlib import Path

from sg_models import OnboardingPhase, SchemaDescriptions, TableDescriptionStatus

from db_meta_v2.config import get_settings
from db_meta_v2.onboarding.schema_store import load_schema_descriptions
from db_meta_v2.onboarding.state import load_state, save_state


def _extract_table_prefix(table_name: str) -> str | None:
    """Extract common prefix from table name (e.g., 'aw_' from 'aw_award')."""
    match = re.match(r"^([a-z]+_)", table_name.lower())
    return match.group(1) if match else None


def _infer_entity_groups(tables: list[dict]) -> dict[str, list[dict]]:
    """Group tables into logical entity groups based on naming patterns."""
    groups: dict[str, list[dict]] = defaultdict(list)
    ungrouped = []

    for table in tables:
        name = table["name"].lower()
        prefix = _extract_table_prefix(name)

        if prefix and len(prefix) > 2:
            # Group by prefix
            group_name = prefix.rstrip("_")
            groups[group_name].append(table)
        else:
            ungrouped.append(table)

    # Only keep groups with 2+ tables
    valid_groups = {k: v for k, v in groups.items() if len(v) >= 2}

    # Add ungrouped tables to "other"
    remaining = ungrouped + [t for k, v in groups.items() if len(v) < 2 for t in v]
    if remaining:
        valid_groups["other"] = remaining

    return valid_groups


def _detect_relationships(tables: list[dict]) -> list[dict]:
    """Detect potential relationships based on column naming patterns."""
    relationships = []
    table_names = {t["name"].lower() for t in tables}

    for table in tables:
        for col in table.get("columns", []):
            col_name = col.get("name", "")
            col_lower = col_name.lower()

            # Pattern: *_id columns that match another table name
            if col_lower.endswith("_id"):
                potential_ref = col_lower[:-3]  # Remove '_id'
                # Check singular and plural forms
                for ref in [potential_ref, potential_ref + "s", potential_ref.rstrip("s")]:
                    if ref in table_names and ref != table["name"].lower():
                        relationships.append(
                            {
                                "from_table": table["name"],
                                "to_table": ref,
                                "column": col_name,
                                "type": "many-to-one",
                            }
                        )
                        break

            # Pattern: foreign key naming like 'fk_*' or '*_fk'
            if "fk" in col_lower or "foreign" in col_lower:
                relationships.append(
                    {
                        "from_table": table["name"],
                        "to_table": "unknown",
                        "column": col_name,
                        "type": "foreign_key",
                    }
                )

    return relationships


def _detect_time_columns(tables: list[dict]) -> list[dict]:
    """Detect time-series columns for data characteristics."""
    time_patterns = [
        "created_at",
        "updated_at",
        "timestamp",
        "date",
        "datetime",
        "created",
        "modified",
        "time",
        "_at",
        "_date",
        "_time",
    ]
    time_columns = []

    for table in tables:
        for col in table.get("columns", []):
            col_name = col.get("name", "")
            col_desc = col.get("description") or ""
            col_lower = col_name.lower()
            desc_lower = col_desc.lower()

            if any(p in col_lower or p in desc_lower for p in time_patterns):
                time_columns.append(
                    {
                        "table": table["name"],
                        "column": col_name,
                        "description": col_desc,
                    }
                )

    return time_columns


def _infer_query_patterns(entity_groups: dict, relationships: list) -> list[str]:
    """Infer common query patterns from entity structure."""
    patterns = []

    # Pattern: Entity lookups
    for group_name, tables in entity_groups.items():
        if group_name != "other" and len(tables) >= 2:
            table_names = [t["name"] for t in tables]
            patterns.append(
                f"**{group_name.replace('_', ' ').title()} queries**: "
                f"Query across related tables: {', '.join(table_names[:3])}"
                + ("..." if len(table_names) > 3 else "")
            )

    # Pattern: Join patterns from relationships
    join_tables = set()
    for rel in relationships:
        if rel["to_table"] != "unknown":
            join_tables.add((rel["from_table"], rel["to_table"]))

    if join_tables:
        patterns.append(
            "**Common joins**: " + ", ".join(f"`{a}` → `{b}`" for a, b in list(join_tables)[:5])
        )

    # Default patterns if none detected
    if not patterns:
        patterns.append("*Analyze table usage to identify common query patterns.*")

    return patterns


def _generate_domain_model_content(schema: SchemaDescriptions) -> str:
    """Generate domain model markdown from schema descriptions.

    This creates a structured document describing the business domain
    based on the schema descriptions.
    """
    provider_id = schema.provider_id
    dialect = schema.dialect or "Unknown"

    # Convert schema tables to dicts for analysis
    all_tables = []
    tables_by_schema: dict[str, list] = {}

    for td in schema.tables:
        if td.status == TableDescriptionStatus.SKIPPED:
            continue

        table_info = {
            "name": td.name,
            "full_name": td.full_name or f"{td.schema_name}.{td.name}",
            "schema": td.schema_name,
            "description": td.description,
            "columns": [
                {"name": c.name, "type": c.type, "description": c.description} for c in td.columns
            ],
        }

        all_tables.append(table_info)

        if td.schema_name not in tables_by_schema:
            tables_by_schema[td.schema_name] = []
        tables_by_schema[td.schema_name].append(table_info)

    # Analyze structure
    entity_groups = _infer_entity_groups(all_tables)
    relationships = _detect_relationships(all_tables)
    time_columns = _detect_time_columns(all_tables)
    query_patterns = _infer_query_patterns(entity_groups, relationships)

    # Build markdown content
    lines = [
        f"# Domain Model: {provider_id}",
        "",
        "## Overview",
        "",
        f"This document describes the business domain for the **{provider_id}** database.",
        f"- **SQL Dialect**: {dialect}",
        f"- **Schemas**: {len(tables_by_schema)}",
        f"- **Tables**: {len(all_tables)}",
        f"- **Entity Groups**: {len([g for g in entity_groups if g != 'other'])}",
        "",
        "---",
        "",
    ]

    # Key Entities section (generated from groupings)
    lines.extend(
        [
            "## Key Entities",
            "",
        ]
    )

    for group_name, tables in sorted(entity_groups.items()):
        if group_name == "other":
            continue

        readable_name = group_name.replace("_", " ").title()
        table_list = ", ".join(f"`{t['name']}`" for t in tables[:5])
        if len(tables) > 5:
            table_list += f" (+{len(tables) - 5} more)"

        lines.append(f"### {readable_name}")
        lines.append("")
        lines.append(f"**Tables**: {table_list}")
        lines.append("")

        # Add description from first table with one
        for t in tables:
            if t["description"] and not t["description"].startswith("Table:"):
                lines.append(f"*{t['description']}*")
                lines.append("")
                break

    if "other" in entity_groups and entity_groups["other"]:
        lines.append("### Other Tables")
        lines.append("")
        other_list = ", ".join(f"`{t['name']}`" for t in entity_groups["other"][:10])
        if len(entity_groups["other"]) > 10:
            other_list += f" (+{len(entity_groups['other']) - 10} more)"
        lines.append(other_list)
        lines.append("")

    # Relationships section
    lines.extend(
        [
            "---",
            "",
            "## Relationships",
            "",
        ]
    )

    if relationships:
        seen = set()
        for rel in relationships:
            if rel["to_table"] == "unknown":
                continue
            key = (rel["from_table"], rel["to_table"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"- `{rel['from_table']}` → `{rel['to_table']}` "
                f"(via `{rel['column']}`, {rel['type']})"
            )
        if not seen:
            lines.append(
                "*No explicit relationships detected. Review foreign key columns manually.*"
            )
        lines.append("")
    else:
        lines.append("*No relationships detected from column naming patterns.*")
        lines.append("")

    # Common Query Patterns section
    lines.extend(
        [
            "---",
            "",
            "## Common Query Patterns",
            "",
        ]
    )

    for pattern in query_patterns:
        lines.append(f"- {pattern}")
    lines.append("")

    # Data Characteristics section
    lines.extend(
        [
            "---",
            "",
            "## Data Characteristics",
            "",
        ]
    )

    if time_columns:
        lines.append("### Time-Series Columns")
        lines.append("")
        # Group by table
        by_table: dict[str, list] = defaultdict(list)
        for tc in time_columns:
            by_table[tc["table"]].append(tc["column"])

        for table, cols in list(by_table.items())[:10]:
            lines.append(f"- `{table}`: {', '.join(cols)}")
        lines.append("")

    lines.extend(
        [
            "### Notes",
            "",
            "- Review data freshness and update frequencies",
            "- Identify primary time dimensions for analytics",
            "- Document any data retention policies",
            "",
        ]
    )

    # Schemas and Tables (detailed reference)
    lines.extend(
        [
            "---",
            "",
            "## Schema Reference",
            "",
        ]
    )

    for schema_name, tables in sorted(tables_by_schema.items()):
        lines.append(f"### Schema: `{schema_name}`")
        lines.append("")

        for table in sorted(tables, key=lambda t: t["name"]):
            lines.append(f"#### {table['name']}")
            lines.append("")
            if table["description"]:
                lines.append(table["description"])
            else:
                lines.append("*No description available.*")
            lines.append("")

            if table["columns"]:
                lines.append("**Columns:**")
                lines.append("")
                for col in table["columns"]:
                    col_desc = col.get("description") or col.get("type") or "unknown"
                    lines.append(f"- `{col['name']}`: {col_desc}")
                lines.append("")

    return "\n".join(lines)


async def _domain_status(provider_id: str | None = None) -> dict:
    """Get current domain model status.

    Args:
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Domain model status and content if available
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    state = load_state(provider_id)

    if state is None:
        return {"error": "Onboarding not started."}

    # Check if domain model file exists
    settings = get_settings()
    domain_file = Path(settings.providers_dir) / provider_id / "domain_model.md"

    result = {
        "provider_id": provider_id,
        "phase": state.phase.value,
        "domain_model_generated": state.domain_model_generated,
        "domain_model_approved": state.domain_model_approved,
        "pending_domain_model": state.pending_domain_model is not None,
    }

    if domain_file.exists():
        result["domain_model_file"] = str(domain_file)
        result["domain_model_exists"] = True
    else:
        result["domain_model_exists"] = False

    return result


async def _domain_generate(provider_id: str | None = None) -> dict:
    """Generate domain model from schema descriptions.

    Creates a markdown document describing the business domain based on
    the schema_descriptions.yaml file.

    Args:
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Generated domain model content for review
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    state = load_state(provider_id)

    if state is None:
        return {"error": "Onboarding not started. Call onboarding_start first."}

    if state.phase != OnboardingPhase.DOMAIN:
        return {
            "error": f"Not in domain phase. Current phase: {state.phase.value}",
            "phase": state.phase.value,
            "hint": "Complete schema descriptions first, or use onboarding_bulk_approve.",
        }

    # Load schema descriptions
    schema = load_schema_descriptions(provider_id)
    if schema is None:
        return {"error": "Schema descriptions not found. Complete schema phase first."}

    if not schema.tables:
        return {"error": "No table descriptions available."}

    # Generate domain model content
    content = _generate_domain_model_content(schema)

    # Store as pending for approval
    state.pending_domain_model = content
    state.domain_model_generated = True
    save_state(state)

    counts = schema.count_by_status()

    return {
        "generated": True,
        "provider_id": provider_id,
        "content": content,
        "tables_included": counts.get("approved", 0),
        "instruction": "Review the domain model above. "
        "Call domain_approve to save it, or domain_generate to regenerate.",
    }


async def _domain_approve(
    content: str | None = None,
    provider_id: str | None = None,
) -> dict:
    """Approve and save the domain model.

    Args:
        content: Optional edited content. If not provided, uses the pending content.
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Approval result with file path
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    state = load_state(provider_id)

    if state is None:
        return {"error": "Onboarding not started."}

    # Use provided content or pending content
    final_content = content or state.pending_domain_model

    if not final_content:
        return {"error": "No domain model to approve. Call domain_generate first."}

    # Save to file
    settings = get_settings()
    provider_dir = Path(settings.providers_dir) / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)

    domain_file = provider_dir / "domain_model.md"
    domain_file.write_text(final_content)

    # Update state
    state.pending_domain_model = None
    state.domain_model_approved = True
    state.phase = OnboardingPhase.BUSINESS_RULES
    save_state(state)

    return {
        "approved": True,
        "provider_id": provider_id,
        "file": str(domain_file),
        "phase": state.phase.value,
        "next_action": "Domain model saved. Next phase: Business Rules. "
        "This phase is not yet implemented.",
    }


async def _domain_skip(provider_id: str | None = None) -> dict:
    """Skip domain model generation and move to next phase.

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

    if state.phase != OnboardingPhase.DOMAIN:
        return {"error": f"Not in domain phase. Current phase: {state.phase.value}"}

    # Skip to next phase
    state.pending_domain_model = None
    state.phase = OnboardingPhase.BUSINESS_RULES
    save_state(state)

    return {
        "skipped": True,
        "provider_id": provider_id,
        "phase": state.phase.value,
        "message": "Domain model skipped. You can generate it later.",
    }
