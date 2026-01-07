"""Query training MCP tools - examples, feedback, and rule distillation."""

from sg_models import FeedbackType

from db_meta_v2.config import get_settings
from db_meta_v2.onboarding.schema_store import load_schema_descriptions
from db_meta_v2.onboarding.state import load_state
from db_meta_v2.training.store import (
    add_example,
    add_feedback,
    add_rule,
    load_examples,
    load_feedback,
    load_instructions,
)


async def _query_status() -> dict:
    """Get query training status - examples, feedback, and rules counts.

    Returns:
        Dict with training phase status
    """
    settings = get_settings()
    provider_id = settings.provider_id

    # Load current state
    state = load_state(provider_id)
    examples = load_examples(provider_id)
    feedback_log = load_feedback(provider_id)
    instructions = load_instructions(provider_id)

    feedback_counts = feedback_log.count_by_type()

    rules_count = len(instructions.rules)
    examples_count = examples.count()

    return {
        "provider_id": provider_id,
        "phase": state.phase.value if state else "unknown",
        "examples": {
            "total": examples_count,
        },
        "feedback": {
            "total": len(feedback_log.feedback),
            "by_type": feedback_counts,
            "undistilled": len(feedback_log.get_undistilled()),
            "corrections": len(feedback_log.get_corrections()),
        },
        "rules": {
            "approved": rules_count,
            "pending": len(instructions.get_pending_candidates()),
        },
        "next_action": "Use query_generate to create a SQL query from natural language",
        "guidance": {
            "summary": f"Training status: {rules_count} rules, {examples_count} examples.",
            "next_steps": [
                "Add business rules with query_add_rule",
                "Add query examples with query_approve",
                "Test SQL generation with query_generate",
                "Import rules/examples from files",
            ],
            "suggested_response": (
                f"**Training Status**\n\n"
                f"- **Business rules:** {rules_count}\n"
                f"- **Query examples:** {examples_count}\n"
                f"- **Feedback entries:** {len(feedback_log.feedback)}\n\n"
                "You can:\n"
                "- Add rules: Tell me business rules in plain English\n"
                "- Add examples: Give me natural language → SQL pairs\n"
                "- Test: Ask me to generate SQL for a question\n"
                "- Import: Upload files with existing rules or examples\n\n"
                "What would you like to do?"
            ),
        },
    }


async def _query_generate(
    natural_language: str,
    tables_hint: list[str] | None = None,
) -> dict:
    """Generate SQL from natural language query.

    This tool generates SQL based on the schema descriptions and any existing
    business rules. The generated SQL should be reviewed and either approved
    (becomes an example) or corrected (becomes feedback for rule distillation).

    Args:
        natural_language: Natural language description of the query
        tables_hint: Optional list of tables to focus on

    Returns:
        Dict with generated SQL and context
    """
    settings = get_settings()
    provider_id = settings.provider_id

    # Load schema for context
    schema = load_schema_descriptions(provider_id)
    if not schema:
        return {
            "error": "No schema descriptions found. Complete the schema phase first.",
            "suggestion": "Run onboarding_start to begin the onboarding process.",
        }

    # Load existing instructions/rules for context
    instructions = load_instructions(provider_id)

    # Build context from schema
    available_tables = []
    for table in schema.tables:
        if tables_hint and table.full_name not in tables_hint:
            continue

        col_info = []
        for col in table.columns:
            desc = f" -- {col.description}" if col.description else ""
            col_info.append(f"  - {col.name}: {col.type or 'unknown'}{desc}")

        table_info = {
            "full_name": table.full_name,
            "description": table.description,
            "columns": col_info,
        }
        available_tables.append(table_info)

    # Build rules context
    rules_context = instructions.rules if instructions.rules else []

    # NOTE: In a real implementation, this would call an LLM to generate SQL.
    # For now, we return a template that the LLM assistant can fill in.
    return {
        "status": "ready_for_generation",
        "natural_language": natural_language,
        "dialect": schema.dialect,
        "context": {
            "tables_available": len(available_tables),
            "tables": available_tables[:10],  # Limit for display
            "business_rules": rules_context,
        },
        "instructions": (
            "Generate SQL for the natural language query above. "
            "Use the provided table schemas and follow any business rules. "
            "After generating SQL, use query_approve if correct, "
            "or query_feedback if corrections are needed."
        ),
        # Placeholder - in production, LLM would fill this
        "generated_sql": None,
        "tables_used": tables_hint or [],
    }


async def _query_approve(
    natural_language: str,
    sql: str,
    tables_used: list[str] | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict:
    """Approve a query and save it as an example.

    Use this after query_generate when the SQL is correct, or to manually
    add a known-good example.

    Args:
        natural_language: Natural language description
        sql: The correct SQL query
        tables_used: Tables referenced in the query
        tags: Tags for categorization (e.g., "aggregation", "join", "filter")
        notes: Additional notes about this example

    Returns:
        Dict with approval status
    """
    settings = get_settings()
    provider_id = settings.provider_id

    result = add_example(
        provider_id=provider_id,
        natural_language=natural_language,
        sql=sql,
        tables_used=tables_used,
        tags=tags,
        notes=notes,
    )

    if result.get("added"):
        # Also log as approved feedback for tracking
        add_feedback(
            provider_id=provider_id,
            natural_language=natural_language,
            generated_sql=sql,
            feedback_type=FeedbackType.APPROVED,
            tables_involved=tables_used,
        )

        total = result["total_examples"]
        return {
            "status": "approved",
            "example_id": result["example_id"],
            "total_examples": total,
            "file_path": result["file_path"],
            "message": f"Example added successfully. Total examples: {total}",
            "guidance": {
                "summary": f"Example saved. You now have {total} examples.",
                "next_steps": [
                    "Add more examples to improve accuracy",
                    "Test SQL generation with a new question",
                    "Add business rules if needed",
                ],
                "suggested_response": (
                    f"✓ **Example saved!** Total: {total} examples\n\n"
                    "More examples help me generate better SQL. Would you like to:\n"
                    "- Add another example?\n"
                    "- Test SQL generation with a question?\n"
                    "- Add some business rules?"
                ),
            },
        }
    else:
        return {
            "status": "error",
            "error": result.get("error", "Unknown error"),
        }


async def _query_feedback(
    natural_language: str,
    generated_sql: str,
    feedback_type: str,
    corrected_sql: str | None = None,
    feedback_text: str | None = None,
    tables_involved: list[str] | None = None,
) -> dict:
    """Provide feedback on generated SQL.

    Use this when generated SQL needs correction or is rejected.
    Corrections can be distilled into business rules.

    Args:
        natural_language: Original natural language query
        generated_sql: The SQL that was generated
        feedback_type: One of "corrected" or "rejected"
        corrected_sql: The correct SQL (required if feedback_type is "corrected")
        feedback_text: Explanation of what was wrong
        tables_involved: Tables referenced

    Returns:
        Dict with feedback status
    """
    settings = get_settings()
    provider_id = settings.provider_id

    # Validate feedback type
    try:
        fb_type = FeedbackType(feedback_type.lower())
    except ValueError:
        return {
            "status": "error",
            "error": f"Invalid feedback_type: {feedback_type}. Use 'corrected' or 'rejected'.",
        }

    # Corrected feedback requires corrected_sql
    if fb_type == FeedbackType.CORRECTED and not corrected_sql:
        return {
            "status": "error",
            "error": "corrected_sql is required when feedback_type is 'corrected'",
        }

    result = add_feedback(
        provider_id=provider_id,
        natural_language=natural_language,
        generated_sql=generated_sql,
        feedback_type=fb_type,
        corrected_sql=corrected_sql,
        feedback_text=feedback_text,
        tables_involved=tables_involved,
    )

    if result.get("added"):
        # If corrected, also add as an example
        example_added = None
        if fb_type == FeedbackType.CORRECTED and corrected_sql:
            example_result = add_example(
                provider_id=provider_id,
                natural_language=natural_language,
                sql=corrected_sql,
                tables_used=tables_involved,
                notes=f"Corrected from: {generated_sql[:100]}...",
            )
            if example_result.get("added"):
                example_added = example_result["example_id"]

        return {
            "status": "recorded",
            "feedback_id": result["feedback_id"],
            "feedback_type": result["feedback_type"],
            "total_feedback": result["total_feedback"],
            "example_added": example_added,
            "message": (
                f"Feedback recorded. "
                f"{'Correction also saved as example.' if example_added else ''}"
            ),
        }
    else:
        return {
            "status": "error",
            "error": result.get("error", "Unknown error"),
        }


async def _query_add_rule(
    rule: str,
    category: str | None = None,
) -> dict:
    """Add a business rule to the prompt instructions.

    Business rules guide SQL generation. They can be added manually or
    distilled from feedback patterns.

    Args:
        rule: The business rule in plain English
        category: Optional category (e.g., "naming", "filter", "join")

    Returns:
        Dict with rule addition status
    """
    settings = get_settings()
    provider_id = settings.provider_id

    result = add_rule(provider_id, rule)

    if result.get("added"):
        total = result["total_rules"]
        return {
            "status": "added",
            "total_rules": total,
            "file_path": result["file_path"],
            "message": f"Rule added. Total rules: {total}",
            "guidance": {
                "summary": f"Rule saved. You now have {total} business rules.",
                "next_steps": [
                    "Add more rules",
                    "Add query examples",
                    "Test SQL generation",
                ],
                "suggested_response": (
                    f"✓ **Rule added!** Total: {total} rules\n\n"
                    "Would you like to:\n"
                    "- Add another rule?\n"
                    "- Move on to adding query examples?\n"
                    "- Test SQL generation with a question?"
                ),
            },
        }
    else:
        return {
            "status": "error",
            "error": result.get("error", "Unknown error"),
        }


async def _query_list_examples(
    limit: int = 10,
    tags: list[str] | None = None,
) -> dict:
    """List saved query examples.

    Args:
        limit: Maximum number of examples to return
        tags: Filter by tags

    Returns:
        Dict with examples list
    """
    settings = get_settings()
    provider_id = settings.provider_id

    examples = load_examples(provider_id)

    filtered = examples.examples
    if tags:
        filtered = [ex for ex in filtered if any(t in ex.tags for t in tags)]

    # Sort by created_at descending and limit
    filtered = sorted(filtered, key=lambda x: x.created_at, reverse=True)[:limit]

    return {
        "provider_id": provider_id,
        "total_examples": examples.count(),
        "showing": len(filtered),
        "examples": [
            {
                "id": ex.id,
                "natural_language": ex.natural_language,
                "sql": ex.sql,
                "tables_used": ex.tables_used,
                "tags": ex.tags,
            }
            for ex in filtered
        ],
    }


async def _query_list_rules() -> dict:
    """List business rules for SQL generation.

    Returns:
        Dict with rules list
    """
    settings = get_settings()
    provider_id = settings.provider_id

    instructions = load_instructions(provider_id)

    return {
        "provider_id": provider_id,
        "approved_rules": instructions.rules,
        "pending_candidates": [
            {
                "id": c.id,
                "rule_text": c.rule_text,
                "category": c.category,
                "confidence": c.confidence,
                "evidence_count": c.evidence_count,
            }
            for c in instructions.get_pending_candidates()
        ],
    }


# =============================================================================
# Import Tools (LLM-assisted)
# =============================================================================


async def _import_instructions(rules: list[str]) -> dict:
    """Import business rules/instructions.

    The LLM should read the uploaded file (any format), extract, dedupe,
    and distill the rules, then pass them as a list to this tool.

    Args:
        rules: List of business rule strings extracted by the LLM

    Returns:
        Dict with import status and counts
    """
    settings = get_settings()
    provider_id = settings.provider_id

    if not rules:
        return {"status": "error", "error": "No rules provided"}

    instructions = load_instructions(provider_id)
    existing_rules = set(instructions.rules)

    added_count = 0
    skipped_count = 0

    for rule in rules:
        rule = rule.strip()
        if rule and rule not in existing_rules:
            instructions.add_rule(rule)
            existing_rules.add(rule)
            added_count += 1
        else:
            skipped_count += 1

    from db_meta_v2.training.store import save_instructions

    result = save_instructions(instructions)

    if result["saved"]:
        total = len(instructions.rules)
        return {
            "status": "success",
            "provider_id": provider_id,
            "rules_added": added_count,
            "rules_skipped": skipped_count,
            "total_rules": total,
            "file_path": result["file_path"],
            "message": (
                f"Imported {added_count} rules "
                f"({skipped_count} duplicates skipped). "
                f"Total rules: {total}"
            ),
            "guidance": {
                "summary": f"Imported {added_count} rules. Total: {total}.",
                "next_steps": [
                    "Review imported rules with query_list_rules",
                    "Add more rules manually",
                    "Import query examples",
                    "Test SQL generation",
                ],
                "suggested_response": (
                    f"✓ **Imported {added_count} rules!**\n"
                    f"({skipped_count} duplicates skipped)\n\n"
                    f"Total rules: {total}\n\n"
                    "Would you like to:\n"
                    "- Review the imported rules?\n"
                    "- Import query examples as well?\n"
                    "- Test SQL generation with a question?"
                ),
            },
        }
    else:
        return {"status": "error", "error": result.get("error", "Save failed")}


async def _import_examples(examples: list[dict]) -> dict:
    """Import query examples.

    The LLM should read the uploaded file (any format), extract and dedupe
    examples, then pass them as a list to this tool.

    Each example should be a dict with:
        - natural_language: The natural language query
        - sql: The SQL query
        - tables_used: Optional list of table names
        - tags: Optional list of tags

    Args:
        examples: List of example dicts extracted by the LLM

    Returns:
        Dict with import status and counts
    """
    settings = get_settings()
    provider_id = settings.provider_id

    if not examples:
        return {"status": "error", "error": "No examples provided"}

    examples_store = load_examples(provider_id)
    existing_nl = {e.natural_language for e in examples_store.examples}

    added_count = 0
    skipped_count = 0

    for ex in examples:
        nl = ex.get("natural_language", "").strip()
        sql = ex.get("sql", "").strip()

        if not nl or not sql:
            skipped_count += 1
            continue

        if nl in existing_nl:
            skipped_count += 1
            continue

        result = add_example(
            provider_id=provider_id,
            natural_language=nl,
            sql=sql,
            tables_used=ex.get("tables_used"),
            tags=ex.get("tags"),
            notes=ex.get("notes", "Imported via LLM extraction"),
        )

        if result.get("added"):
            existing_nl.add(nl)
            added_count += 1
        else:
            skipped_count += 1

    total = load_examples(provider_id).count()
    return {
        "status": "success",
        "provider_id": provider_id,
        "examples_added": added_count,
        "examples_skipped": skipped_count,
        "total_examples": total,
        "message": (
            f"Imported {added_count} examples "
            f"({skipped_count} duplicates/invalid skipped). "
            f"Total examples: {total}"
        ),
        "guidance": {
            "summary": f"Imported {added_count} examples. Total: {total}.",
            "next_steps": [
                "Review imported examples with query_list_examples",
                "Add more examples manually",
                "Import business rules",
                "Test SQL generation",
            ],
            "suggested_response": (
                f"✓ **Imported {added_count} examples!**\n"
                f"({skipped_count} duplicates/invalid skipped)\n\n"
                f"Total examples: {total}\n\n"
                "Would you like to:\n"
                "- Review the imported examples?\n"
                "- Import business rules as well?\n"
                "- Test SQL generation with a question?"
            ),
        },
    }
