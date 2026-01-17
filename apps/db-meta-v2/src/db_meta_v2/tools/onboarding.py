"""Onboarding MCP tools."""

import logging
import sys

from mcp.server.fastmcp import Context
from sg_models import OnboardingPhase, TableDescriptionStatus

from db_meta_v2.config import get_settings
from db_meta_v2.db.connection import test_connection
from db_meta_v2.db.introspection import (
    get_catalogs,
    get_columns,
    get_schemas,
    get_table_sample,
    get_tables,
)
from db_meta_v2.onboarding.ignore import (
    add_ignore_pattern,
    import_ignore_patterns,
    load_ignore_patterns,
    remove_ignore_pattern,
)
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

logger = logging.getLogger(__name__)


async def _report_progress(ctx: Context | None, progress: float, total: float = 100) -> None:
    """Report progress if context supports it.

    Safe to call even if ctx is None or doesn't support progress.
    """
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress=progress, total=total)
    except Exception:
        pass  # Ignore if context doesn't support progress


def _build_status_guidance(state, tables_described: int) -> dict:
    """Build phase-specific conversational guidance."""
    from sg_models import OnboardingPhase

    phase = state.phase
    remaining = state.tables_total - tables_described

    if phase == OnboardingPhase.INIT:
        return {
            "summary": "Schema discovery completed. Ready to describe tables.",
            "next_steps": [
                "Begin describing tables one by one",
                "Or bulk-approve all tables with auto-generated descriptions",
            ],
            "suggested_response": (
                f"I've discovered {state.tables_total} tables in your database. "
                "Now let's add descriptions to help with SQL generation.\n\n"
                "**Options:**\n"
                "1. **One by one** - I'll show each table with sample data\n"
                "2. **Bulk approve** - Auto-generate descriptions (editable later)\n\n"
                "Which approach would you prefer?"
            ),
        }

    elif phase == OnboardingPhase.SCHEMA:
        if remaining > 0:
            return {
                "summary": f"Describing tables: {tables_described}/{state.tables_total} complete.",
                "next_steps": [
                    f"Continue describing remaining {remaining} tables",
                    "Or bulk-approve remaining tables to move faster",
                ],
                "suggested_response": (
                    f"**Progress: {tables_described}/{state.tables_total} tables described**\n\n"
                    f"You have {remaining} tables left. Would you like to:\n"
                    "- Continue with the next table?\n"
                    "- Bulk-approve the remaining tables?\n\n"
                    "Just say 'next' to continue or 'bulk approve' to finish quickly."
                ),
            }
        else:
            return {
                "summary": "All tables described! Ready for business rules phase.",
                "next_steps": [
                    "Add business rules for SQL generation",
                    "Add query examples",
                ],
                "suggested_response": (
                    "Excellent! All tables are now described. "
                    "Let's move to the **business rules phase**.\n\n"
                    "Business rules help me generate accurate SQL. For example:\n"
                    "- 'Always filter by is_active = true unless asked otherwise'\n"
                    "- 'Use UTC timezone for all date comparisons'\n\n"
                    "Do you have any rules to add? Or would you like to add examples?"
                ),
            }

    elif phase == OnboardingPhase.DOMAIN:
        return {
            "summary": "In domain/business rules phase.",
            "next_steps": [
                "Add business rules that guide SQL generation",
                "Import existing rules from a file",
                "Move to adding query examples",
            ],
            "suggested_response": (
                "We're now in the **business rules phase**.\n\n"
                f"Current status: {state.rules_captured} rules captured\n\n"
                "You can:\n"
                "- Tell me rules in plain English (e.g., 'amounts are stored in cents')\n"
                "- Upload a file with existing rules for me to import\n"
                "- Move on to adding query examples\n\n"
                "What would you like to do?"
            ),
        }

    elif phase == OnboardingPhase.QUERY_TRAINING:
        return {
            "summary": "In query training phase.",
            "next_steps": [
                "Add query examples (natural language → SQL pairs)",
                "Import existing examples from a file",
                "Test SQL generation",
            ],
            "suggested_response": (
                "We're in the **query training phase**.\n\n"
                f"Current status: {state.examples_added} examples added\n\n"
                "You can:\n"
                "- Give me example queries to learn from\n"
                "- Upload a file with existing query examples\n"
                "- Test SQL generation with a natural language question\n\n"
                "What would you like to do?"
            ),
        }

    elif phase == OnboardingPhase.COMPLETE:
        return {
            "summary": "Onboarding complete! Ready for SQL generation.",
            "next_steps": [
                "Generate SQL from natural language queries",
                "Add more examples to improve accuracy",
                "Refine business rules based on feedback",
            ],
            "suggested_response": (
                "🎉 **Onboarding is complete!**\n\n"
                f"Summary:\n"
                f"- {state.tables_total} tables documented\n"
                f"- {state.rules_captured} business rules\n"
                f"- {state.examples_added} query examples\n\n"
                "I'm ready to help generate SQL queries. "
                "Just describe what data you're looking for in plain English!"
            ),
        }

    # Default fallback
    return {
        "summary": f"Current phase: {phase.value}",
        "next_steps": ["Check status and continue onboarding"],
        "suggested_response": f"Currently in {phase.value} phase. How can I help?",
    }


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
            # Conversational guidance
            "guidance": {
                "summary": "Database onboarding has not started yet.",
                "next_steps": [
                    "Start the onboarding process to discover and document database schema",
                ],
                "suggested_response": (
                    "I see that onboarding hasn't started yet for this database. "
                    "Would you like me to begin the onboarding process? This will:\n"
                    "1. Connect to your database and verify access\n"
                    "2. Discover all schemas and tables\n"
                    "3. Guide you through describing each table\n\n"
                    "Just say 'yes' or 'start onboarding' to begin!"
                ),
            },
        }

    # Load schema descriptions to get counts
    schema = load_schema_descriptions(provider_id)
    tables_described = 0
    if schema:
        counts = schema.count_by_status()
        tables_described = counts.get("approved", 0) + counts.get("skipped", 0)

    # Build phase-specific guidance
    guidance = _build_status_guidance(state, tables_described)

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
        "guidance": guidance,
    }


async def _onboarding_start(provider_id: str | None = None, force: bool = False) -> dict:
    """Start onboarding flow for a provider.

    This will:
    1. Test database connection
    2. Detect SQL dialect
    3. Show ignore patterns for user review before discovery

    After reviewing patterns, call onboarding_discover to run schema discovery.

    Args:
        provider_id: Provider ID. Uses configured default if not provided.
        force: If True, restart onboarding even if already started

    Returns:
        Connection result with ignore patterns for review
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    # Check if already started - return current status instead of error
    # This makes the tool idempotent and avoids ChatGPT retrying
    existing = load_state(provider_id)
    if existing is not None and not force:
        # Load schema to get progress
        schema = load_schema_descriptions(provider_id)
        tables_described = 0
        if schema:
            counts = schema.count_by_status()
            tables_described = counts.get("approved", 0) + counts.get("skipped", 0)

        return {
            "started": True,  # Already started = success (idempotent)
            "already_in_progress": True,
            "provider_id": provider_id,
            "phase": existing.phase.value,
            "dialect": existing.dialect_detected,
            "tables_total": existing.tables_total,
            "tables_described": tables_described,
            "message": f"Onboarding already in progress (phase: {existing.phase.value}). "
            "Use onboarding_status for details, onboarding_reset to clear, "
            "or force=True to restart.",
            "next_action": existing.next_action(),
        }

    # If force=True, clean up existing state and schema files
    if force and existing is not None:
        from db_meta_v2.onboarding.schema_store import get_schema_file_path

        # Delete existing state
        delete_state(provider_id)

        # Delete existing schema descriptions
        schema_file = get_schema_file_path(provider_id)
        if schema_file.exists():
            try:
                schema_file.unlink()
            except Exception:
                pass

    # Test connection
    conn_result = test_connection()
    if not conn_result["connected"]:
        return {
            "started": False,
            "provider_id": provider_id,
            "error": f"Database connection failed: {conn_result['error']}",
        }

    # Create initial state (INIT phase - before discovery)
    state = create_initial_state(provider_id)
    state.database_url_configured = True
    state.connection_verified = True
    state.dialect_detected = conn_result["dialect"]
    state.phase = OnboardingPhase.INIT

    # Save state
    save_result = save_state(state)
    if not save_result["saved"]:
        return {
            "started": False,
            "provider_id": provider_id,
            "error": f"Failed to save state: {save_result['error']}",
        }

    # Load ignore patterns for review
    ignore = load_ignore_patterns(provider_id)
    patterns_display = "\n".join([f"  - {p}" for p in ignore.patterns[:20]])
    if len(ignore.patterns) > 20:
        patterns_display += f"\n  ... and {len(ignore.patterns) - 20} more"

    return {
        "started": True,
        "provider_id": provider_id,
        "dialect": state.dialect_detected,
        "phase": state.phase.value,
        "ignore_patterns": ignore.patterns,
        "pattern_count": len(ignore.patterns),
        "next_action": "Review ignore patterns, then call onboarding_discover(phase='structure')",
        "guidance": {
            "summary": f"Connected to {state.dialect_detected} database. Review ignore patterns.",
            "next_steps": [
                "Review the ignore patterns below",
                "Add patterns with onboarding_add_ignore_pattern",
                "Remove patterns with onboarding_remove_ignore_pattern",
                "Import from file with onboarding_import_ignore_patterns",
                "Call onboarding_discover(phase='structure') to discover catalogs/schemas",
                "Review schemas, add more ignore patterns if needed",
                "Call onboarding_discover(phase='tables') to scan tables",
            ],
            "suggested_response": (
                f"**Database connected successfully!**\n\n"
                f"- **Dialect:** {state.dialect_detected}\n\n"
                "Before scanning the database, please review the **ignore patterns**. "
                "These filter out system schemas, internal tables, etc.\n\n"
                f"**Current patterns ({len(ignore.patterns)}):**\n{patterns_display}\n\n"
                "You can:\n"
                "- **Add** a pattern: tell me what to ignore (e.g., 'ignore test_*')\n"
                "- **Remove** a pattern: tell me what to include\n"
                "- **Upload** a file with patterns for me to import\n\n"
                "When you're ready, say **'discover'** to scan the database structure.\n"
                "(I'll show you schemas first, then you can add more patterns before table scan)"
            ),
        },
    }


async def _onboarding_discover(
    ctx: Context | None = None,
    provider_id: str | None = None,
    phase: str = "structure",
) -> dict:
    """Run schema discovery after reviewing ignore patterns.

    Discovery is split into two phases to allow users to add ignore patterns
    after seeing the database structure but before the slow table scan:

    - phase="structure": Discover catalogs and schemas only (fast)
    - phase="tables": Discover tables in non-ignored schemas (slow, with progress)

    Typical flow:
    1. onboarding_discover(phase="structure") - see catalogs/schemas
    2. User reviews and adds ignore patterns for schemas they don't need
    3. onboarding_discover(phase="tables") - scan tables in remaining schemas

    Args:
        ctx: MCP Context for progress reporting (optional)
        provider_id: Provider ID. Uses configured default if not provided.
        phase: Discovery phase - "structure" (catalogs/schemas) or "tables"

    Returns:
        Discovery result with counts
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    # Validate phase parameter
    if phase not in ("structure", "tables"):
        return {
            "discovered": False,
            "error": f"Invalid phase '{phase}'. Must be 'structure' or 'tables'.",
        }

    # Load state - must be in INIT phase
    state = load_state(provider_id)
    if state is None:
        return {
            "discovered": False,
            "error": "Onboarding not started. Call onboarding_start first.",
        }

    # For structure phase, must be in INIT
    # For tables phase, can be in INIT (if structure already done) or INIT
    if phase == "structure" and state.phase != OnboardingPhase.INIT:
        return {
            "discovered": False,
            "error": f"Already discovered (phase: {state.phase.value}). "
            "Use onboarding_start with force=True to rediscover.",
            "phase": state.phase.value,
        }

    if phase == "tables" and state.phase not in (OnboardingPhase.INIT,):
        return {
            "discovered": False,
            "error": f"Already discovered tables (phase: {state.phase.value}). "
            "Use onboarding_start with force=True to rediscover.",
            "phase": state.phase.value,
        }

    # For tables phase, check that structure discovery was done first
    if phase == "tables" and not state.schemas_discovered:
        return {
            "discovered": False,
            "error": "Structure discovery not done yet. "
            "Call onboarding_discover(phase='structure') first.",
        }

    # Load ignore patterns
    ignore = load_ignore_patterns(provider_id)
    print(
        f"[DISCOVERY] Loaded {len(ignore.patterns)} ignore patterns", file=sys.stderr, flush=True
    )

    # ============================================================
    # PHASE: STRUCTURE - Discover catalogs and schemas only (fast)
    # ============================================================
    if phase == "structure":
        # Discover catalogs first (for Trino 3-level hierarchy)
        try:
            print("[DISCOVERY] Discovering catalogs...", file=sys.stderr, flush=True)
            catalogs = get_catalogs()
            print(
                f"[DISCOVERY] Found catalogs (before filter): {catalogs}",
                file=sys.stderr,
                flush=True,
            )
            catalogs = ignore.filter_catalogs(catalogs)
            print(
                f"[DISCOVERY] Found catalogs (after filter): {catalogs}",
                file=sys.stderr,
                flush=True,
            )
            state.catalogs_discovered = [c for c in catalogs if c is not None]
        except Exception as e:
            print(f"[DISCOVERY] Error discovering catalogs: {e}", file=sys.stderr, flush=True)
            catalogs = [None]
            state.catalogs_discovered = []

        # Discover schemas for each catalog
        all_schemas = []
        all_schemas_with_catalog = []  # For display: list of {"catalog": ..., "schema": ...}
        try:
            for catalog in catalogs:
                print(
                    f"[DISCOVERY] Discovering schemas for catalog: {catalog}",
                    file=sys.stderr,
                    flush=True,
                )
                schemas = get_schemas(catalog=catalog)
                print(
                    f"[DISCOVERY] Found schemas in {catalog} (before filter): {schemas}",
                    file=sys.stderr,
                    flush=True,
                )
                schemas = ignore.filter_schemas(schemas)
                print(
                    f"[DISCOVERY] Found schemas in {catalog} (after filter): {schemas}",
                    file=sys.stderr,
                    flush=True,
                )
                for schema in schemas:
                    if schema is not None:
                        all_schemas.append(schema)
                        all_schemas_with_catalog.append(
                            {
                                "catalog": catalog,
                                "schema": schema,
                                "full_name": f"{catalog}.{schema}" if catalog else schema,
                            }
                        )
            state.schemas_discovered = all_schemas
            print(
                f"[DISCOVERY] Total schemas discovered: {len(all_schemas)}",
                file=sys.stderr,
                flush=True,
            )
        except Exception as e:
            print(f"[DISCOVERY] Error discovering schemas: {e}", file=sys.stderr, flush=True)
            state.schemas_discovered = []

        # Save state (still in INIT phase, waiting for tables discovery)
        save_result = save_state(state)
        if not save_result["saved"]:
            return {
                "discovered": False,
                "provider_id": provider_id,
                "error": f"Failed to save state: {save_result['error']}",
            }

        # Format schemas for display
        schemas_display = "\n".join(
            [f"  - {s['full_name']}" for s in all_schemas_with_catalog[:20]]
        )
        if len(all_schemas_with_catalog) > 20:
            schemas_display += f"\n  ... and {len(all_schemas_with_catalog) - 20} more"

        return {
            "discovered": True,
            "discovery_phase": "structure",
            "provider_id": provider_id,
            "dialect": state.dialect_detected,
            "catalogs_found": len(state.catalogs_discovered),
            "catalogs": state.catalogs_discovered,
            "schemas_found": len(state.schemas_discovered),
            "schemas": all_schemas_with_catalog,
            "phase": state.phase.value,
            "next_action": "Review schemas, add ignore patterns if needed, "
            "then call onboarding_discover(phase='tables')",
            "guidance": {
                "summary": (
                    f"Found {len(state.schemas_discovered)} schemas"
                    + (
                        f" in {len(state.catalogs_discovered)} catalogs"
                        if state.catalogs_discovered
                        else ""
                    )
                    + ". Review before table discovery."
                ),
                "next_steps": [
                    "Review the discovered schemas",
                    "Add ignore patterns for schemas you don't need (e.g., test_*, staging_*)",
                    "Then call onboarding_discover(phase='tables') to scan tables",
                ],
                "suggested_response": (
                    "**Structure discovery complete!**\n\n"
                    + (
                        f"**Catalogs ({len(state.catalogs_discovered)}):** "
                        f"{', '.join(state.catalogs_discovered)}\n\n"
                        if state.catalogs_discovered
                        else ""
                    )
                    + f"**Schemas ({len(state.schemas_discovered)}):**\n{schemas_display}\n\n"
                    "**Before I scan for tables**, please review the schemas above.\n\n"
                    "Table discovery can be slow for large databases. "
                    "To speed this up, you can add **ignore patterns** for schemas "
                    "you don't need:\n"
                    "- `test_*` - skip test schemas\n"
                    "- `staging_*` - skip staging schemas\n"
                    "- `*_backup` - skip backup schemas\n\n"
                    "Tell me any patterns to ignore, or say **'continue'** to scan tables."
                ),
            },
        }

    # ============================================================
    # PHASE: TABLES - Discover tables in non-ignored schemas (slow)
    # ============================================================
    await _report_progress(ctx, 0, 100)  # 0% - Starting tables phase

    # Re-filter schemas in case new ignore patterns were added
    all_schemas_filtered = []
    catalogs = state.catalogs_discovered if state.catalogs_discovered else [None]

    for catalog in catalogs:
        schemas = get_schemas(catalog=catalog)
        schemas = ignore.filter_schemas(schemas)
        for schema in schemas:
            if schema is not None:
                all_schemas_filtered.append({"catalog": catalog, "schema": schema})

    # Update state with filtered schemas
    state.schemas_discovered = [s["schema"] for s in all_schemas_filtered]
    total_schemas = len(all_schemas_filtered)

    print(
        f"[DISCOVERY] Schemas after re-filtering: {total_schemas}",
        file=sys.stderr,
        flush=True,
    )

    await _report_progress(ctx, 5, 100)  # 5% - Schemas filtered

    # Discover tables with columns (iterate catalog -> schema -> table)
    all_tables = []
    try:
        for schema_idx, schema_info in enumerate(all_schemas_filtered):
            catalog = schema_info["catalog"]
            schema = schema_info["schema"]

            # Report progress: 5% to 90% for schema discovery
            if total_schemas > 0:
                schema_progress = 5 + (85 * schema_idx / total_schemas)
                await _report_progress(ctx, schema_progress, 100)

            print(
                f"[DISCOVERY] Discovering tables for {catalog}.{schema}...",
                file=sys.stderr,
                flush=True,
            )
            tables = get_tables(schema=schema, catalog=catalog)
            print(
                f"[DISCOVERY] Found {len(tables)} tables in {catalog}.{schema} (pre-filter)",
                file=sys.stderr,
                flush=True,
            )
            tables = ignore.filter_tables(tables)
            print(
                f"[DISCOVERY] Found {len(tables)} tables in {catalog}.{schema} (after filter)",
                file=sys.stderr,
                flush=True,
            )

            for t in tables:
                # Get columns for each table
                try:
                    columns = get_columns(t["name"], schema=schema, catalog=catalog)
                except Exception as e:
                    print(
                        f"[DISCOVERY] Error getting columns for {t['name']}: {e}",
                        file=sys.stderr,
                        flush=True,
                    )
                    columns = []

                all_tables.append(
                    {
                        "name": t["name"],
                        "schema": schema,
                        "catalog": catalog,
                        "full_name": t["full_name"],
                        "columns": columns,
                    }
                )

        state.tables_discovered = [t["full_name"] for t in all_tables]
        state.tables_total = len(all_tables)
        print(
            f"[DISCOVERY] Total tables discovered: {len(all_tables)}", file=sys.stderr, flush=True
        )
    except Exception as e:
        print(f"[DISCOVERY] Error discovering tables: {e}", file=sys.stderr, flush=True)
        state.tables_discovered = []
        state.tables_total = 0

    await _report_progress(ctx, 90, 100)  # 90% - Tables discovered, saving

    # Create schema_descriptions.yaml with all discovered tables
    schema = create_initial_schema(
        provider_id=provider_id,
        dialect=state.dialect_detected,
        tables=all_tables,
    )
    schema_result = save_schema_descriptions(schema)
    if not schema_result["saved"]:
        return {
            "discovered": False,
            "provider_id": provider_id,
            "error": f"Failed to save schema descriptions: {schema_result['error']}",
        }

    # Move to schema phase
    state.phase = OnboardingPhase.SCHEMA

    # Save state
    save_result = save_state(state)
    if not save_result["saved"]:
        return {
            "discovered": False,
            "provider_id": provider_id,
            "error": f"Failed to save state: {save_result['error']}",
        }

    await _report_progress(ctx, 100, 100)  # 100% - Complete

    return {
        "discovered": True,
        "discovery_phase": "tables",
        "provider_id": provider_id,
        "dialect": state.dialect_detected,
        "catalogs_found": len(state.catalogs_discovered) if state.catalogs_discovered else 0,
        "schemas_found": len(state.schemas_discovered),
        "tables_found": state.tables_total,
        "phase": state.phase.value,
        "schema_file": schema_result["file_path"],
        "next_action": state.next_action(),
        "guidance": {
            "summary": (
                f"Discovered {state.tables_total} tables "
                f"across {len(state.schemas_discovered)} schemas"
                + (
                    f" in {len(state.catalogs_discovered)} catalogs"
                    if state.catalogs_discovered
                    else ""
                )
                + "."
            ),
            "next_steps": [
                "Describe tables one by one with onboarding_next",
                "Or bulk-approve all tables with onboarding_bulk_approve",
            ],
            "suggested_response": (
                "**Discovery complete!**\n\n"
                "I found:\n"
                + (
                    f"- **Catalogs:** {len(state.catalogs_discovered)}\n"
                    if state.catalogs_discovered
                    else ""
                )
                + f"- **Schemas:** {len(state.schemas_discovered)}\n"
                f"- **Tables:** {state.tables_total}\n\n"
                "Now let's add descriptions to your tables. This helps me understand "
                "your data and generate accurate SQL queries.\n\n"
                "**How would you like to proceed?**\n"
                "1. **One by one** - I'll show each table with sample data\n"
                "2. **Bulk approve** - Auto-generate descriptions (editable later)\n\n"
                "Which option works best for you?"
            ),
        },
    }


async def _onboarding_add_ignore_pattern(pattern: str, provider_id: str | None = None) -> dict:
    """Add an ignore pattern for schema discovery.

    Patterns support wildcards: * matches any characters, ? matches single character.
    Examples: 'test_*', 'tmp_*', '*_backup', 'pg_*'

    Args:
        pattern: Pattern to add (e.g., 'test_*', 'staging_*')
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Result with updated pattern list
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    result = add_ignore_pattern(provider_id, pattern)

    if result.get("added"):
        patterns_display = "\n".join([f"  - {p}" for p in result["patterns"][:15]])
        if len(result["patterns"]) > 15:
            patterns_display += f"\n  ... and {len(result['patterns']) - 15} more"

        return {
            **result,
            "guidance": {
                "summary": f"Added pattern '{pattern}'. Total: {result['total_patterns']}.",
                "next_steps": [
                    "Add more patterns if needed",
                    "Remove patterns with onboarding_remove_ignore_pattern",
                    "Call onboarding_discover when ready",
                ],
                "suggested_response": (
                    f"✓ **Added:** `{pattern}`\n\n"
                    f"**Current patterns ({result['total_patterns']}):**\n"
                    f"{patterns_display}\n\n"
                    "Add more patterns, or say **'discover'** when ready to scan."
                ),
            },
        }
    return result


async def _onboarding_remove_ignore_pattern(pattern: str, provider_id: str | None = None) -> dict:
    """Remove an ignore pattern.

    Args:
        pattern: Pattern to remove
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Result with updated pattern list
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    result = remove_ignore_pattern(provider_id, pattern)

    if result.get("removed"):
        patterns_display = "\n".join([f"  - {p}" for p in result["patterns"][:15]])
        if len(result["patterns"]) > 15:
            patterns_display += f"\n  ... and {len(result['patterns']) - 15} more"

        return {
            **result,
            "guidance": {
                "summary": f"Removed pattern '{pattern}'. Total: {result['total_patterns']}.",
                "next_steps": [
                    "Remove more patterns if needed",
                    "Add patterns with onboarding_add_ignore_pattern",
                    "Call onboarding_discover when ready",
                ],
                "suggested_response": (
                    f"✓ **Removed:** `{pattern}`\n\n"
                    f"**Current patterns ({result['total_patterns']}):**\n"
                    f"{patterns_display}\n\n"
                    "Make more changes, or say **'discover'** when ready to scan."
                ),
            },
        }
    return result


async def _onboarding_import_ignore_patterns(
    patterns: list[str], replace: bool = False, provider_id: str | None = None
) -> dict:
    """Import ignore patterns from a list (LLM extracts from uploaded file).

    The LLM should read the uploaded file and extract patterns, then pass
    them as a list to this tool.

    Args:
        patterns: List of patterns to import
        replace: If True, replace all patterns. If False, merge with existing.
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        Result with updated pattern list
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    result = import_ignore_patterns(provider_id, patterns, replace=replace)

    if result.get("imported"):
        patterns_display = "\n".join([f"  - {p}" for p in result["patterns"][:15]])
        if len(result["patterns"]) > 15:
            patterns_display += f"\n  ... and {len(result['patterns']) - 15} more"

        return {
            **result,
            "guidance": {
                "summary": f"Imported patterns. Total: {result['total_patterns']}.",
                "next_steps": [
                    "Review the patterns",
                    "Add/remove patterns as needed",
                    "Call onboarding_discover when ready",
                ],
                "suggested_response": (
                    f"✓ **Imported patterns!**\n\n"
                    f"**Current patterns ({result['total_patterns']}):**\n"
                    f"{patterns_display}\n\n"
                    "Review the patterns above. Make changes if needed, "
                    "or say **'discover'** when ready to scan."
                ),
            },
        }
    return result


async def _onboarding_reset(provider_id: str | None = None, hard: bool = False) -> dict:
    """Reset onboarding state for a provider.

    Args:
        provider_id: Provider ID. Uses configured default if not provided.
        hard: If True, also delete schema_descriptions.yaml (full reset)

    Returns:
        Reset result
    """
    if provider_id is None:
        settings = get_settings()
        provider_id = settings.provider_id

    result = delete_state(provider_id)
    state_deleted = result.get("deleted", False)
    schema_deleted = False

    # Hard reset: also delete schema descriptions
    if hard:
        from db_meta_v2.onboarding.schema_store import get_schema_file_path

        schema_file = get_schema_file_path(provider_id)
        if schema_file.exists():
            try:
                schema_file.unlink()
                schema_deleted = True
            except Exception:
                pass

    # Return success if either file was deleted, or if hard reset was requested
    # (even if files didn't exist, we've "reset" to a clean state)
    if state_deleted or schema_deleted or hard:
        if hard:
            return {
                "reset": True,
                "provider_id": provider_id,
                "state_deleted": result["deleted"],
                "schema_deleted": schema_deleted,
                "message": "Hard reset complete. All onboarding data deleted. "
                "Call onboarding_start to begin fresh.",
            }
        else:
            return {
                "reset": True,
                "provider_id": provider_id,
                "message": "Onboarding state deleted. Call onboarding_start to begin again.",
                "note": "schema_descriptions.yaml was preserved. Use hard=True for full reset.",
            }
    else:
        return {
            "reset": False,
            "provider_id": provider_id,
            "error": result.get("error", "Nothing to reset"),
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
            "guidance": {
                "summary": "Schema phase complete! All tables documented.",
                "next_steps": [
                    "Add business rules for SQL generation",
                    "Add query examples",
                    "Import existing rules/examples from files",
                ],
                "suggested_response": (
                    "🎉 **Schema phase complete!**\n\n"
                    f"- {counts.get('approved', 0)} tables described\n"
                    f"- {counts.get('skipped', 0)} tables skipped\n\n"
                    "Now let's move to **business rules**. These help generate accurate SQL.\n\n"
                    "Examples of business rules:\n"
                    "- 'Prices are stored in cents, divide by 100 for dollars'\n"
                    "- 'Always exclude deleted records unless asked'\n\n"
                    "Do you have any rules to add? Or import from a file?"
                ),
            },
        }

    # Update current table in state
    state.current_table = next_table.full_name
    save_state(state)

    # Get sample data
    try:
        sample = get_table_sample(
            next_table.name,
            schema=next_table.schema_name,
            catalog=next_table.catalog_name,
            limit=3,
        )
    except Exception:
        sample = []

    # Count progress
    counts = schema.count_by_status()
    described = counts.get("approved", 0) + counts.get("skipped", 0)
    remaining = counts.get("pending", 0)

    # Format columns for display
    columns_display = "\n".join([f"  - {c.name} ({c.type})" for c in next_table.columns[:15]])
    if len(next_table.columns) > 15:
        columns_display += f"\n  ... and {len(next_table.columns) - 15} more columns"

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
        "guidance": {
            "summary": f"Table {next_table.full_name} ({len(next_table.columns)} columns).",
            "next_steps": [
                "Review the table structure and sample data",
                "Provide a description using onboarding_approve",
                "Or skip with onboarding_skip if not needed",
            ],
            "suggested_response": (
                f"**Table {described + 1} of {state.tables_total}: `{next_table.full_name}`**\n\n"
                f"**Columns ({len(next_table.columns)}):**\n{columns_display}\n\n"
                f"**Sample data:** {len(sample)} rows shown above\n\n"
                "Based on the structure and data, this table appears to store "
                "[your analysis here].\n\n"
                "**Suggested description:** [generate based on columns/data]\n\n"
                "Does this look correct? Say 'approve' to save, 'skip' to skip, "
                "or provide your own description."
            ),
        },
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
    remaining = state.tables_total - tables_described

    return {
        "approved": True,
        "table_name": state.current_table,
        "tables_described": tables_described,
        "tables_total": state.tables_total,
        "progress": f"{tables_described}/{state.tables_total}",
        "next_action": "Call onboarding_next for the next table.",
        "guidance": {
            "summary": f"Table description saved. {remaining} tables remaining.",
            "next_steps": [
                "Continue to the next table",
                "Or bulk-approve remaining tables",
            ]
            if remaining > 0
            else [
                "Move to business rules phase",
                "Add query examples",
            ],
            "suggested_response": (
                f"✓ **Saved!** Progress: {tables_described}/{state.tables_total}\n\n"
                + (
                    f"{remaining} tables to go. Ready for the next one?"
                    if remaining > 0
                    else "All tables are now described! Let's move to business rules."
                )
            ),
        },
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
    remaining = state.tables_total - tables_described

    return {
        "skipped": True,
        "table_name": skipped_table,
        "tables_described": tables_described,
        "tables_total": state.tables_total,
        "next_action": "Call onboarding_next for the next table.",
        "guidance": {
            "summary": f"Table skipped. {remaining} tables remaining.",
            "next_steps": [
                "Continue to the next table",
                "Or bulk-approve remaining tables",
            ]
            if remaining > 0
            else [
                "Move to business rules phase",
            ],
            "suggested_response": (
                f"↷ **Skipped.** Progress: {tables_described}/{state.tables_total}\n\n"
                + (
                    f"{remaining} tables to go. Ready for the next one?"
                    if remaining > 0
                    else "All tables processed! Let's move to business rules."
                )
            ),
        },
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
        "guidance": {
            "summary": f"Bulk approved {approved_count} tables. Schema phase complete!",
            "next_steps": [
                "Add business rules for SQL generation",
                "Add query examples",
                "Import existing rules/examples from files",
            ],
            "suggested_response": (
                f"✓ **Bulk approved {approved_count} tables!**\n\n"
                "Auto-generated descriptions have been saved. You can refine them later "
                "by editing the `schema_descriptions.yaml` file.\n\n"
                "Now let's move to **business rules**. These help me generate accurate SQL.\n\n"
                "Examples:\n"
                "- 'Prices are stored in cents'\n"
                "- 'Always exclude soft-deleted records'\n"
                "- 'User IDs in table X reference table Y'\n\n"
                "Do you have any rules to add? Or would you like to import from a file?"
            ),
        },
    }
