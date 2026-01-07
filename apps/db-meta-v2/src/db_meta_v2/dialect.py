"""SQL dialect management."""

from pathlib import Path

import yaml

from db_meta_v2.config import get_settings
from db_meta_v2.db.connection import detect_dialect_from_url


def get_dialect_file_path(dialect: str) -> Path | None:
    """Get path to dialect file.

    Args:
        dialect: Dialect name (trino, postgresql, clickhouse)

    Returns:
        Path to dialect file, or None if not found
    """
    settings = get_settings()
    resources_dir = Path(settings.resources_dir)

    # Check in sql-dialects directory
    dialect_file = resources_dir / "sql-dialects" / f"{dialect}.yaml"
    if dialect_file.exists():
        return dialect_file

    return None


def load_dialect_rules(dialect: str) -> dict:
    """Load dialect rules from YAML file.

    Args:
        dialect: Dialect name (trino, postgresql, clickhouse)

    Returns:
        Dict with dialect info and rules
    """
    dialect_path = get_dialect_file_path(dialect)

    if dialect_path is None:
        return {
            "dialect": dialect,
            "found": False,
            "rules": [],
            "error": f"No dialect file found for '{dialect}'",
        }

    try:
        with open(dialect_path) as f:
            data = yaml.safe_load(f)

        return {
            "dialect": dialect,
            "found": True,
            "version": data.get("version", "unknown"),
            "description": data.get("description", ""),
            "rules": data.get("rules", []),
            "rule_count": len(data.get("rules", [])),
            "file_path": str(dialect_path),
            "error": None,
        }
    except Exception as e:
        return {
            "dialect": dialect,
            "found": True,
            "rules": [],
            "error": f"Failed to load dialect file: {e}",
        }


def get_dialect_for_connection(database_url: str | None = None) -> dict:
    """Detect dialect from connection and load rules.

    Args:
        database_url: Optional database URL. Uses settings if not provided.

    Returns:
        Dict with detected dialect and rules
    """
    if database_url is None:
        settings = get_settings()
        database_url = settings.database_url

    if not database_url:
        return {
            "detected": False,
            "dialect": None,
            "rules": [],
            "error": "No database URL configured",
        }

    dialect = detect_dialect_from_url(database_url)
    rules = load_dialect_rules(dialect)

    return {
        "detected": True,
        "dialect": dialect,
        **rules,
    }
