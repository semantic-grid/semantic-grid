"""Migration from legacy storage formats to connection-based structure.

Storage format versions:
- v1: ~/.dbmeta/vault/ + ~/.dbmeta/providers/{id}/ (separate directories)
- v2: ~/.dbmeta/connections/{name}/ (self-contained connection directory)

Handles migration of:
- schema_descriptions.yaml -> schema/descriptions.yaml
- domain_model.md -> domain/model.md
- onboarding_state.yaml -> state.yaml
- query_examples.yaml -> examples/*.yaml (split into individual files)
- feedback_log.yaml -> learnings/failures/*.yaml (split, filter failures only)
- instructions/domain.md -> domain/model.md (if domain_model.md missing)
"""

import logging
import shutil
from pathlib import Path

import yaml

from db_meta_v2.config import STORAGE_VERSION, get_settings

logger = logging.getLogger(__name__)

VERSION_FILE = ".version"


def get_storage_version(path: Path) -> int:
    """Get the storage format version from a directory.

    Args:
        path: Directory to check for version file

    Returns:
        Version number (0 if no version file, format unknown)
    """
    version_file = path / VERSION_FILE
    if version_file.exists():
        try:
            content = version_file.read_text().strip()
            return int(content)
        except (ValueError, OSError):
            return 0
    return 0


def write_storage_version(path: Path, version: int = STORAGE_VERSION) -> None:
    """Write the storage format version to a directory.

    Args:
        path: Directory to write version file to
        version: Version number to write
    """
    version_file = path / VERSION_FILE
    version_file.write_text(str(version))
    logger.debug(f"Wrote version {version} to {version_file}")


def detect_legacy_structure() -> dict | None:
    """Detect if legacy v1 structure exists.

    Looks for the old structure:
    - ~/.dbmeta/vault/
    - ~/.dbmeta/providers/{provider_id}/

    Returns:
        dict with legacy paths if found, None otherwise
    """
    settings = get_settings()
    dbmeta_root = Path.home() / ".dbmeta"

    # Check for legacy vault path (from config or default)
    legacy_vault = None
    if settings.vault_path:
        legacy_vault = Path(settings.vault_path)
    else:
        legacy_vault = dbmeta_root / "vault"

    # Check for legacy providers path
    legacy_providers = None
    if settings.providers_dir:
        legacy_providers = Path(settings.providers_dir)
    else:
        legacy_providers = dbmeta_root / "providers"

    provider_id = settings.get_effective_provider_id()
    legacy_provider_dir = legacy_providers / provider_id if legacy_providers else None

    # Check what exists
    vault_exists = legacy_vault and legacy_vault.exists()
    provider_exists = legacy_provider_dir and legacy_provider_dir.exists()

    if not vault_exists and not provider_exists:
        return None

    # Check if it's actually legacy (no version file in connections dir)
    connections_dir = dbmeta_root / "connections"
    if connections_dir.exists():
        # If connections dir has version file, already migrated
        for conn_dir in connections_dir.iterdir():
            if conn_dir.is_dir() and (conn_dir / VERSION_FILE).exists():
                return None

    return {
        "vault_path": legacy_vault if vault_exists else None,
        "provider_path": legacy_provider_dir if provider_exists else None,
        "provider_id": provider_id,
    }


def _migrate_schema_descriptions(src_path: Path, connection_path: Path) -> bool:
    """Migrate schema_descriptions.yaml to schema/descriptions.yaml.

    Args:
        src_path: Legacy provider or vault directory
        connection_path: New connection directory

    Returns:
        True if migrated
    """
    legacy_file = src_path / "schema_descriptions.yaml"
    if not legacy_file.exists():
        return False

    dest_dir = connection_path / "schema"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "descriptions.yaml"

    if dest_file.exists():
        logger.debug("schema/descriptions.yaml already exists, skipping")
        return False

    shutil.copy2(legacy_file, dest_file)
    logger.info(f"Migrated schema_descriptions.yaml to {dest_file}")
    return True


def _migrate_domain_model(src_path: Path, connection_path: Path) -> bool:
    """Migrate domain_model.md to domain/model.md.

    Args:
        src_path: Legacy provider directory
        connection_path: New connection directory

    Returns:
        True if migrated
    """
    legacy_file = src_path / "domain_model.md"
    if not legacy_file.exists():
        # Also check instructions/domain.md (from vault)
        legacy_file = src_path / "instructions" / "domain.md"
        if not legacy_file.exists():
            return False

    dest_dir = connection_path / "domain"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "model.md"

    if dest_file.exists():
        content = dest_file.read_text()
        # Only skip if it has real content
        if content.strip() and "Generated domain model will be saved here" not in content:
            logger.debug("domain/model.md already has content, skipping")
            return False

    shutil.copy2(legacy_file, dest_file)
    logger.info(f"Migrated domain model to {dest_file}")
    return True


def _migrate_onboarding_state(src_path: Path, connection_path: Path) -> bool:
    """Migrate onboarding_state.yaml to state.yaml.

    Args:
        src_path: Legacy provider directory
        connection_path: New connection directory

    Returns:
        True if migrated
    """
    legacy_file = src_path / "onboarding_state.yaml"
    if not legacy_file.exists():
        return False

    dest_file = connection_path / "state.yaml"

    if dest_file.exists():
        logger.debug("state.yaml already exists, skipping")
        return False

    shutil.copy2(legacy_file, dest_file)
    logger.info(f"Migrated onboarding_state.yaml to {dest_file}")
    return True


def _migrate_query_examples(src_path: Path, connection_path: Path) -> int:
    """Migrate query_examples.yaml to examples/*.yaml.

    Args:
        src_path: Legacy provider directory
        connection_path: New connection directory

    Returns:
        Number of examples migrated
    """
    legacy_file = src_path / "query_examples.yaml"
    if not legacy_file.exists():
        return 0

    examples_dir = connection_path / "examples"
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

        out_file = examples_dir / f"{example_id}.yaml"
        if not out_file.exists():
            out_file.write_text(yaml.dump(new_example, default_flow_style=False, sort_keys=False))
            count += 1

    if count > 0:
        logger.info(f"Migrated {count} query examples to examples/")
    return count


def _migrate_feedback_log(src_path: Path, connection_path: Path) -> int:
    """Migrate feedback_log.yaml to learnings/failures/*.yaml.

    Args:
        src_path: Legacy provider directory
        connection_path: New connection directory

    Returns:
        Number of failures migrated
    """
    legacy_file = src_path / "feedback_log.yaml"
    if not legacy_file.exists():
        return 0

    failures_dir = connection_path / "learnings" / "failures"
    failures_dir.mkdir(parents=True, exist_ok=True)

    try:
        data = yaml.safe_load(legacy_file.read_text())
    except Exception as e:
        logger.error(f"Failed to parse {legacy_file}: {e}")
        return 0

    feedback_list = data.get("feedback", [])
    count = 0

    for feedback in feedback_list:
        if feedback.get("feedback_type") == "approved":
            continue

        feedback_id = feedback.get("id", f"migrated_{count}")

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

        out_file = failures_dir / f"{feedback_id}.yaml"
        if not out_file.exists():
            out_file.write_text(yaml.dump(new_failure, default_flow_style=False, sort_keys=False))
            count += 1

    if count > 0:
        logger.info(f"Migrated {count} failures to learnings/failures/")
    return count


def _migrate_vault_files(vault_path: Path, connection_path: Path) -> dict:
    """Migrate vault structure files (instructions, examples, learnings).

    Args:
        vault_path: Legacy vault directory
        connection_path: New connection directory

    Returns:
        dict with migration counts
    """
    stats = {"instructions": 0, "examples": 0, "learnings": 0}

    # Copy instructions (except domain.md which goes to domain/)
    src_instructions = vault_path / "instructions"
    if src_instructions.exists():
        dest_instructions = connection_path / "instructions"
        dest_instructions.mkdir(parents=True, exist_ok=True)

        for file in src_instructions.iterdir():
            if file.is_file() and file.name != "domain.md":
                dest_file = dest_instructions / file.name
                if not dest_file.exists():
                    shutil.copy2(file, dest_file)
                    stats["instructions"] += 1

    # Copy examples
    src_examples = vault_path / "examples"
    if src_examples.exists():
        dest_examples = connection_path / "examples"
        dest_examples.mkdir(parents=True, exist_ok=True)

        for file in src_examples.iterdir():
            if file.is_file():
                dest_file = dest_examples / file.name
                if not dest_file.exists():
                    shutil.copy2(file, dest_file)
                    stats["examples"] += 1

    # Copy learnings
    src_learnings = vault_path / "learnings"
    if src_learnings.exists():
        dest_learnings = connection_path / "learnings"
        shutil.copytree(src_learnings, dest_learnings, dirs_exist_ok=True)
        stats["learnings"] = sum(1 for _ in src_learnings.rglob("*") if _.is_file())

    return stats


def migrate_to_connection_structure(connection_name: str | None = None) -> dict:
    """Migrate from legacy v1 structure to v2 connection structure.

    Args:
        connection_name: Name for the new connection (defaults to provider_id)

    Returns:
        dict with migration statistics
    """
    settings = get_settings()

    if not settings.vault_migrate_legacy:
        logger.debug("Legacy migration disabled via config")
        return {"skipped": True, "reason": "disabled"}

    legacy = detect_legacy_structure()
    if not legacy:
        logger.debug("No legacy structure detected")
        return {"skipped": True, "reason": "no_legacy_data"}

    # Determine connection name and path
    if not connection_name:
        connection_name = legacy["provider_id"] or "default"

    connection_path = settings.get_effective_connection_path()

    # Check if already at v2
    if get_storage_version(connection_path) >= 2:
        logger.debug(f"Connection {connection_name} already at v2")
        return {"skipped": True, "reason": "already_migrated"}

    logger.info(f"Migrating to connection structure: {connection_path}")

    # Ensure connection directory exists
    connection_path.mkdir(parents=True, exist_ok=True)

    stats = {
        "connection_name": connection_name,
        "connection_path": str(connection_path),
        "schema_descriptions": False,
        "domain_model": False,
        "onboarding_state": False,
        "query_examples": 0,
        "failures": 0,
        "vault_files": {},
    }

    # Migrate from provider directory
    if legacy["provider_path"]:
        provider_path = legacy["provider_path"]
        stats["schema_descriptions"] = _migrate_schema_descriptions(provider_path, connection_path)
        stats["domain_model"] = _migrate_domain_model(provider_path, connection_path)
        stats["onboarding_state"] = _migrate_onboarding_state(provider_path, connection_path)
        stats["query_examples"] = _migrate_query_examples(provider_path, connection_path)
        stats["failures"] = _migrate_feedback_log(provider_path, connection_path)

    # Migrate from vault directory
    if legacy["vault_path"]:
        vault_path = legacy["vault_path"]
        # Domain model might be in vault/instructions/
        if not stats["domain_model"]:
            stats["domain_model"] = _migrate_domain_model(vault_path, connection_path)
        stats["vault_files"] = _migrate_vault_files(vault_path, connection_path)

    # Write version file
    write_storage_version(connection_path, STORAGE_VERSION)

    logger.info(f"Migration complete: {stats}")
    return stats


# Backward compatibility alias
def migrate_legacy_provider_data() -> dict:
    """Deprecated: Use migrate_to_connection_structure instead."""
    return migrate_to_connection_structure()
