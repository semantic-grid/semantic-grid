"""Migration from legacy providers/{id}/ structure to flat /data/ structure.

Handles one-time migration of:
- query_examples.yaml -> vault/examples/*.yaml (split into individual files)
- domain_model.md -> vault/instructions/domain.md
- feedback_log.yaml -> vault/learnings/failures/*.yaml (split, filter failures only)
- schema_descriptions.yaml -> /data/schema_descriptions.yaml (move up)
- onboarding_state.yaml -> /data/onboarding_state.yaml (move up)
"""

import logging
import shutil
from pathlib import Path

import yaml

from db_meta_v2.config import get_settings

logger = logging.getLogger(__name__)


def _migrate_query_examples(legacy_file: Path, vault_path: Path) -> int:
    """Migrate query_examples.yaml to individual vault/examples/*.yaml files.

    Args:
        legacy_file: Path to legacy query_examples.yaml
        vault_path: Path to vault root

    Returns:
        Number of examples migrated
    """
    if not legacy_file.exists():
        return 0

    examples_dir = vault_path / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)

    try:
        data = yaml.safe_load(legacy_file.read_text())
    except Exception as e:
        logger.error(f"Failed to parse {legacy_file}: {e}")
        return 0

    examples = data.get("examples", [])
    count = 0

    for example in examples:
        example_id = example.get("id", f"migrated_{count}")

        # Convert to new format
        new_example = {
            "id": example_id,
            "created": example.get("created_at", ""),
            "intent": example.get("natural_language", ""),
            "keywords": example.get("tags", []),
            "sql": example.get("sql", ""),
            "tables": example.get("tables_used", []),
            "validated": True,
            "notes": example.get("notes", ""),
            "migrated_from": "query_examples.yaml",
        }

        # Write individual file
        out_file = examples_dir / f"{example_id}.yaml"
        if not out_file.exists():  # Don't overwrite existing
            out_file.write_text(yaml.dump(new_example, default_flow_style=False, sort_keys=False))
            count += 1

    logger.info(f"Migrated {count} query examples to vault/examples/")
    return count


def _migrate_domain_model(legacy_file: Path, vault_path: Path) -> bool:
    """Migrate domain_model.md to vault/instructions/domain.md.

    Args:
        legacy_file: Path to legacy domain_model.md
        vault_path: Path to vault root

    Returns:
        True if migrated, False otherwise
    """
    if not legacy_file.exists():
        return False

    dest_file = vault_path / "instructions" / "domain.md"
    dest_file.parent.mkdir(parents=True, exist_ok=True)

    # Only migrate if destination is default/empty
    if dest_file.exists():
        content = dest_file.read_text()
        if content.strip() and "Add domain-specific guidance here" not in content:
            logger.debug("domain.md already has content, skipping migration")
            return False

    shutil.copy2(legacy_file, dest_file)
    logger.info("Migrated domain_model.md to vault/instructions/domain.md")
    return True


def _migrate_feedback_log(legacy_file: Path, vault_path: Path) -> int:
    """Migrate feedback_log.yaml to vault/learnings/failures/*.yaml.

    Only migrates entries with feedback_type != 'approved' (i.e., failures/corrections).

    Args:
        legacy_file: Path to legacy feedback_log.yaml
        vault_path: Path to vault root

    Returns:
        Number of failures migrated
    """
    if not legacy_file.exists():
        return 0

    failures_dir = vault_path / "learnings" / "failures"
    failures_dir.mkdir(parents=True, exist_ok=True)

    try:
        data = yaml.safe_load(legacy_file.read_text())
    except Exception as e:
        logger.error(f"Failed to parse {legacy_file}: {e}")
        return 0

    feedback_list = data.get("feedback", [])
    count = 0

    for feedback in feedback_list:
        # Skip approved entries - only migrate failures
        if feedback.get("feedback_type") == "approved":
            continue

        feedback_id = feedback.get("id", f"migrated_{count}")

        # Convert to new format
        new_failure = {
            "id": feedback_id,
            "created": feedback.get("created_at", ""),
            "intent": feedback.get("natural_language", ""),
            "sql": feedback.get("generated_sql", ""),
            "error": feedback.get("feedback_text", ""),
            "resolution": feedback.get("corrected_sql", ""),
            "tables": feedback.get("tables_involved", []),
            "migrated_from": "feedback_log.yaml",
        }

        # Write individual file
        out_file = failures_dir / f"{feedback_id}.yaml"
        if not out_file.exists():  # Don't overwrite existing
            out_file.write_text(yaml.dump(new_failure, default_flow_style=False, sort_keys=False))
            count += 1

    if count > 0:
        logger.info(f"Migrated {count} failure records to vault/learnings/failures/")
    return count


def _migrate_top_level_file(legacy_file: Path, data_root: Path, filename: str) -> bool:
    """Move a file from legacy provider dir to /data/ root.

    Args:
        legacy_file: Path to legacy file
        data_root: Path to /data/ root
        filename: Target filename

    Returns:
        True if migrated, False otherwise
    """
    if not legacy_file.exists():
        return False

    dest_file = data_root / filename

    # Don't overwrite existing
    if dest_file.exists():
        logger.debug(f"{filename} already exists in data root, skipping")
        return False

    shutil.copy2(legacy_file, dest_file)
    logger.info(f"Migrated {legacy_file.name} to {dest_file}")
    return True


def migrate_legacy_provider_data() -> dict:
    """Migrate data from legacy providers/{id}/ structure.

    Checks if legacy structure exists and migrates to new flat structure.
    Does not delete original files (safe migration).

    Returns:
        dict with migration statistics
    """
    settings = get_settings()

    if not settings.vault_migrate_legacy:
        logger.debug("Legacy migration disabled via config")
        return {"skipped": True, "reason": "disabled"}

    # Determine paths
    providers_dir = Path(settings.providers_dir)
    provider_id = settings.provider_id
    legacy_provider_path = providers_dir / provider_id

    # Also check for flat providers_dir (K8s case where providers_dir IS the provider dir)
    # e.g., /data/providers might contain files directly if provider_id isn't a subdir
    if not legacy_provider_path.exists():
        # Try providers_dir itself
        legacy_provider_path = providers_dir

    if not legacy_provider_path.exists():
        logger.debug(f"No legacy provider data found at {legacy_provider_path}")
        return {"skipped": True, "reason": "no_legacy_data"}

    # Check if there's actually legacy data
    legacy_files = list(legacy_provider_path.glob("*.yaml")) + list(
        legacy_provider_path.glob("*.md")
    )
    if not legacy_files:
        logger.debug("No legacy files found to migrate")
        return {"skipped": True, "reason": "no_legacy_files"}

    vault_path = Path(settings.vault_path)
    data_root = vault_path.parent  # /data

    logger.info(f"Starting migration from {legacy_provider_path}")

    stats = {
        "examples": 0,
        "domain_model": False,
        "failures": 0,
        "schema_descriptions": False,
        "onboarding_state": False,
    }

    # Migrate each type
    stats["examples"] = _migrate_query_examples(
        legacy_provider_path / "query_examples.yaml", vault_path
    )

    stats["domain_model"] = _migrate_domain_model(
        legacy_provider_path / "domain_model.md", vault_path
    )

    stats["failures"] = _migrate_feedback_log(
        legacy_provider_path / "feedback_log.yaml", vault_path
    )

    stats["schema_descriptions"] = _migrate_top_level_file(
        legacy_provider_path / "schema_descriptions.yaml", data_root, "schema_descriptions.yaml"
    )

    stats["onboarding_state"] = _migrate_top_level_file(
        legacy_provider_path / "onboarding_state.yaml", data_root, "onboarding_state.yaml"
    )

    logger.info(f"Migration complete: {stats}")
    return stats
