"""Training data persistence - examples and feedback."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sg_models import (
    FeedbackLog,
    FeedbackType,
    PromptInstructions,
    QueryExample,
    QueryExamples,
    QueryFeedback,
)

from db_meta_v2.onboarding.state import get_provider_dir


def get_examples_file_path(provider_id: str) -> Path:
    """Get path to query examples file."""
    return get_provider_dir(provider_id) / "query_examples.yaml"


def get_feedback_file_path(provider_id: str) -> Path:
    """Get path to feedback log file."""
    return get_provider_dir(provider_id) / "feedback_log.yaml"


def get_instructions_file_path(provider_id: str) -> Path:
    """Get path to prompt instructions file."""
    return get_provider_dir(provider_id) / "prompt_instructions.yaml"


# =============================================================================
# Query Examples
# =============================================================================


def load_examples(provider_id: str) -> QueryExamples:
    """Load query examples from YAML file.

    Args:
        provider_id: Provider identifier

    Returns:
        QueryExamples (empty if file doesn't exist)
    """
    examples_file = get_examples_file_path(provider_id)

    if not examples_file.exists():
        return QueryExamples(provider_id=provider_id)

    try:
        with open(examples_file) as f:
            data = yaml.safe_load(f)
        return QueryExamples.model_validate(data)
    except Exception:
        return QueryExamples(provider_id=provider_id)


def save_examples(examples: QueryExamples) -> dict:
    """Save query examples to YAML file.

    Args:
        examples: QueryExamples to save

    Returns:
        Dict with save status
    """
    try:
        provider_dir = get_provider_dir(examples.provider_id)
        provider_dir.mkdir(parents=True, exist_ok=True)

        examples_dict = examples.model_dump(mode="json")

        examples_file = get_examples_file_path(examples.provider_id)
        with open(examples_file, "w") as f:
            yaml.dump(
                examples_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        return {"saved": True, "file_path": str(examples_file), "error": None}
    except Exception as e:
        return {"saved": False, "file_path": None, "error": str(e)}


def add_example(
    provider_id: str,
    natural_language: str,
    sql: str,
    tables_used: list[str] | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict:
    """Add a new query example.

    Args:
        provider_id: Provider identifier
        natural_language: Natural language query
        sql: Correct SQL
        tables_used: Tables referenced in the query
        tags: Tags for categorization
        notes: Additional notes

    Returns:
        Dict with example ID and status
    """
    examples = load_examples(provider_id)

    example = QueryExample(
        id=str(uuid.uuid4())[:8],
        natural_language=natural_language,
        sql=sql,
        tables_used=tables_used or [],
        tags=tags or [],
        notes=notes,
        created_at=datetime.now(UTC),
    )

    examples.add_example(example)
    result = save_examples(examples)

    if result["saved"]:
        return {
            "added": True,
            "example_id": example.id,
            "total_examples": examples.count(),
            "file_path": result["file_path"],
        }
    else:
        return {"added": False, "error": result["error"]}


# =============================================================================
# Feedback Log
# =============================================================================


def load_feedback(provider_id: str) -> FeedbackLog:
    """Load feedback log from YAML file.

    Args:
        provider_id: Provider identifier

    Returns:
        FeedbackLog (empty if file doesn't exist)
    """
    feedback_file = get_feedback_file_path(provider_id)

    if not feedback_file.exists():
        return FeedbackLog(provider_id=provider_id)

    try:
        with open(feedback_file) as f:
            data = yaml.safe_load(f)
        return FeedbackLog.model_validate(data)
    except Exception:
        return FeedbackLog(provider_id=provider_id)


def save_feedback(feedback_log: FeedbackLog) -> dict:
    """Save feedback log to YAML file.

    Args:
        feedback_log: FeedbackLog to save

    Returns:
        Dict with save status
    """
    try:
        provider_dir = get_provider_dir(feedback_log.provider_id)
        provider_dir.mkdir(parents=True, exist_ok=True)

        feedback_dict = feedback_log.model_dump(mode="json")

        feedback_file = get_feedback_file_path(feedback_log.provider_id)
        with open(feedback_file, "w") as f:
            yaml.dump(
                feedback_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        return {"saved": True, "file_path": str(feedback_file), "error": None}
    except Exception as e:
        return {"saved": False, "file_path": None, "error": str(e)}


def add_feedback(
    provider_id: str,
    natural_language: str,
    generated_sql: str,
    feedback_type: FeedbackType,
    corrected_sql: str | None = None,
    feedback_text: str | None = None,
    tables_involved: list[str] | None = None,
) -> dict:
    """Add a new feedback record.

    Args:
        provider_id: Provider identifier
        natural_language: Original natural language query
        generated_sql: SQL that was generated
        feedback_type: Type of feedback
        corrected_sql: User-provided correction (if any)
        feedback_text: User explanation
        tables_involved: Tables referenced

    Returns:
        Dict with feedback ID and status
    """
    feedback_log = load_feedback(provider_id)

    fb = QueryFeedback(
        id=str(uuid.uuid4())[:8],
        natural_language=natural_language,
        generated_sql=generated_sql,
        feedback_type=feedback_type,
        corrected_sql=corrected_sql,
        feedback_text=feedback_text,
        tables_involved=tables_involved or [],
        created_at=datetime.now(UTC),
    )

    feedback_log.add_feedback(fb)
    result = save_feedback(feedback_log)

    if result["saved"]:
        return {
            "added": True,
            "feedback_id": fb.id,
            "feedback_type": feedback_type.value,
            "total_feedback": len(feedback_log.feedback),
        }
    else:
        return {"added": False, "error": result["error"]}


# =============================================================================
# Prompt Instructions
# =============================================================================


def load_instructions(provider_id: str) -> PromptInstructions:
    """Load prompt instructions from YAML file.

    Args:
        provider_id: Provider identifier

    Returns:
        PromptInstructions (empty if file doesn't exist)
    """
    instructions_file = get_instructions_file_path(provider_id)

    if not instructions_file.exists():
        return PromptInstructions(provider_id=provider_id)

    try:
        with open(instructions_file) as f:
            data = yaml.safe_load(f)
        return PromptInstructions.model_validate(data)
    except Exception:
        return PromptInstructions(provider_id=provider_id)


def save_instructions(instructions: PromptInstructions) -> dict:
    """Save prompt instructions to YAML file.

    Args:
        instructions: PromptInstructions to save

    Returns:
        Dict with save status
    """
    try:
        provider_dir = get_provider_dir(instructions.provider_id)
        provider_dir.mkdir(parents=True, exist_ok=True)

        instructions_dict = instructions.model_dump(mode="json")

        instructions_file = get_instructions_file_path(instructions.provider_id)
        with open(instructions_file, "w") as f:
            yaml.dump(
                instructions_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        return {"saved": True, "file_path": str(instructions_file), "error": None}
    except Exception as e:
        return {"saved": False, "file_path": None, "error": str(e)}


def add_rule(provider_id: str, rule: str) -> dict:
    """Add a business rule to prompt instructions.

    Args:
        provider_id: Provider identifier
        rule: Business rule text

    Returns:
        Dict with status
    """
    instructions = load_instructions(provider_id)
    instructions.add_rule(rule)
    result = save_instructions(instructions)

    if result["saved"]:
        return {
            "added": True,
            "total_rules": len(instructions.rules),
            "file_path": result["file_path"],
        }
    else:
        return {"added": False, "error": result["error"]}


# =============================================================================
# Bulk Import Functions
# =============================================================================


def import_instructions_from_legacy(provider_id: str, yaml_content: str) -> dict:
    """Import instructions from legacy format YAML.

    Legacy format:
        version: 1.0.0
        profiles:
            wh_v2:
                - "rule 1"
                - "rule 2"

    Args:
        provider_id: Provider identifier
        yaml_content: YAML string in legacy format

    Returns:
        Dict with import status
    """
    try:
        data = yaml.safe_load(yaml_content)

        if not data or "profiles" not in data:
            return {"imported": False, "error": "Invalid format: missing 'profiles' key"}

        profiles = data.get("profiles", {})
        all_rules = []

        # Collect rules from all profiles
        for profile_name, rules in profiles.items():
            if isinstance(rules, list):
                for rule in rules:
                    if isinstance(rule, str) and rule.strip():
                        all_rules.append(rule.strip())

        if not all_rules:
            return {"imported": False, "error": "No rules found in profiles"}

        # Load existing or create new
        instructions = load_instructions(provider_id)

        # Add rules (avoiding duplicates)
        added_count = 0
        for rule in all_rules:
            if rule not in instructions.rules:
                instructions.add_rule(rule)
                added_count += 1

        result = save_instructions(instructions)

        if result["saved"]:
            return {
                "imported": True,
                "rules_found": len(all_rules),
                "rules_added": added_count,
                "rules_skipped": len(all_rules) - added_count,
                "total_rules": len(instructions.rules),
                "file_path": result["file_path"],
            }
        else:
            return {"imported": False, "error": result["error"]}

    except yaml.YAMLError as e:
        return {"imported": False, "error": f"YAML parse error: {e}"}
    except Exception as e:
        return {"imported": False, "error": str(e)}


def import_examples_from_legacy(provider_id: str, yaml_content: str) -> dict:
    """Import examples from legacy format YAML.

    Legacy format:
        version: 1.0.0
        profiles:
            wh_v2:
                examples:
                    - request: "natural language"
                      response: |
                          SELECT ...
                      db: wh_v2

    Args:
        provider_id: Provider identifier
        yaml_content: YAML string in legacy format

    Returns:
        Dict with import status
    """
    try:
        data = yaml.safe_load(yaml_content)

        if not data or "profiles" not in data:
            return {"imported": False, "error": "Invalid format: missing 'profiles' key"}

        profiles = data.get("profiles", {})
        all_examples = []

        # Collect examples from all profiles
        for profile_name, profile_data in profiles.items():
            if isinstance(profile_data, dict):
                examples = profile_data.get("examples", [])
            elif isinstance(profile_data, list):
                # Some formats have examples directly as list
                examples = profile_data
            else:
                continue

            for ex in examples:
                if isinstance(ex, dict):
                    request = ex.get("request", "").strip()
                    response = ex.get("response", "").strip()
                    if request and response:
                        all_examples.append(
                            {
                                "natural_language": request,
                                "sql": response,
                                "profile": profile_name,
                                "db": ex.get("db", profile_name),
                            }
                        )

        if not all_examples:
            return {"imported": False, "error": "No examples found in profiles"}

        # Load existing or create new
        examples_store = load_examples(provider_id)

        # Check for duplicates by natural language
        existing_nl = {e.natural_language for e in examples_store.examples}

        added_count = 0
        for ex in all_examples:
            if ex["natural_language"] not in existing_nl:
                example = QueryExample(
                    id=str(uuid.uuid4())[:8],
                    natural_language=ex["natural_language"],
                    sql=ex["sql"],
                    tables_used=[],
                    tags=[ex.get("db", ""), ex.get("profile", "")],
                    notes=f"Imported from legacy format (profile: {ex.get('profile', 'unknown')})",
                    created_at=datetime.now(UTC),
                )
                examples_store.add_example(example)
                existing_nl.add(ex["natural_language"])
                added_count += 1

        result = save_examples(examples_store)

        if result["saved"]:
            return {
                "imported": True,
                "examples_found": len(all_examples),
                "examples_added": added_count,
                "examples_skipped": len(all_examples) - added_count,
                "total_examples": examples_store.count(),
                "file_path": result["file_path"],
            }
        else:
            return {"imported": False, "error": result["error"]}

    except yaml.YAMLError as e:
        return {"imported": False, "error": f"YAML parse error: {e}"}
    except Exception as e:
        return {"imported": False, "error": str(e)}
