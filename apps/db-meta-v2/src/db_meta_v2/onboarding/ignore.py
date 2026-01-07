"""Handle .dbmetaignore file for filtering schemas and tables during onboarding."""

import fnmatch
from pathlib import Path

from db_meta_v2.config import get_settings

# Default ignore patterns (built-in system schemas/tables/catalogs)
DEFAULT_IGNORE_PATTERNS = """
# PostgreSQL system schemas
information_schema
pg_catalog
pg_toast
pg_temp_*

# ClickHouse system schemas
system
INFORMATION_SCHEMA

# Trino/Presto system catalogs and schemas
system
$internal

# MySQL system schemas
mysql
performance_schema
sys

# Django internal tables
django_*
auth_*
authtoken_*

# Common migration tables
alembic_version
flyway_*
schema_migrations
__migration*

# Common internal/temp tables
_*
tmp_*
temp_*
""".strip()

# Additional patterns specifically for catalogs (Trino)
DEFAULT_CATALOG_IGNORE_PATTERNS = [
    "system",
    "information_schema",
]


class IgnorePatterns:
    """Manages ignore patterns for schemas and tables."""

    def __init__(self, patterns: list[str] | None = None):
        """Initialize with patterns.

        Args:
            patterns: List of ignore patterns. If None, uses defaults.
        """
        self.patterns: list[str] = []
        if patterns is not None:
            self.patterns = patterns
        else:
            self.patterns = self._parse_patterns(DEFAULT_IGNORE_PATTERNS)

    @staticmethod
    def _parse_patterns(content: str) -> list[str]:
        """Parse patterns from file content, ignoring comments and blank lines."""
        patterns = []
        for line in content.splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
        return patterns

    def should_ignore(self, name: str) -> bool:
        """Check if a schema or table name should be ignored.

        Args:
            name: Schema or table name to check

        Returns:
            True if the name matches any ignore pattern
        """
        for pattern in self.patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
            # Also check case-insensitive for common variations
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                return True
        return False

    def filter_catalogs(self, catalogs: list[str | None]) -> list[str | None]:
        """Filter out ignored catalogs.

        Args:
            catalogs: List of catalog names (may contain None for non-catalog DBs)

        Returns:
            List of catalogs that don't match ignore patterns
        """
        result = []
        for c in catalogs:
            if c is None:
                result.append(c)
            elif not self.should_ignore(c):
                # Also check against default catalog patterns
                if c.lower() not in [p.lower() for p in DEFAULT_CATALOG_IGNORE_PATTERNS]:
                    result.append(c)
        return result

    def filter_schemas(self, schemas: list[str | None]) -> list[str | None]:
        """Filter out ignored schemas.

        Args:
            schemas: List of schema names (may contain None)

        Returns:
            List of schemas that don't match ignore patterns
        """
        return [s for s in schemas if s is None or not self.should_ignore(s)]

    def filter_tables(self, tables: list[dict]) -> list[dict]:
        """Filter out ignored tables.

        Args:
            tables: List of table dicts with 'name' and 'full_name' keys

        Returns:
            List of tables that don't match ignore patterns
        """
        result = []
        for table in tables:
            table_name = table.get("name", "")
            # Check both the simple name and full name
            if not self.should_ignore(table_name):
                result.append(table)
        return result


def load_ignore_patterns(provider_id: str | None = None) -> IgnorePatterns:
    """Load ignore patterns from .dbmetaignore file.

    Searches for .dbmetaignore in:
    1. Provider directory: {providers_dir}/{provider_id}/.dbmetaignore
    2. Resources directory: {resources_dir}/.dbmetaignore
    3. Falls back to built-in defaults

    Args:
        provider_id: Provider ID. Uses configured default if not provided.

    Returns:
        IgnorePatterns instance
    """
    settings = get_settings()
    if provider_id is None:
        provider_id = settings.provider_id

    # Check provider-specific file first
    provider_ignore = Path(settings.providers_dir) / provider_id / ".dbmetaignore"
    if provider_ignore.exists():
        content = provider_ignore.read_text()
        patterns = IgnorePatterns._parse_patterns(content)
        return IgnorePatterns(patterns)

    # Check resources directory
    resources_ignore = Path(settings.resources_dir) / ".dbmetaignore"
    if resources_ignore.exists():
        content = resources_ignore.read_text()
        patterns = IgnorePatterns._parse_patterns(content)
        return IgnorePatterns(patterns)

    # Fall back to defaults
    return IgnorePatterns()


def get_default_ignore_content() -> str:
    """Get the default .dbmetaignore file content.

    Returns:
        Default ignore patterns as a string
    """
    return DEFAULT_IGNORE_PATTERNS


def save_ignore_patterns(provider_id: str, patterns: list[str]) -> dict:
    """Save ignore patterns to .dbmetaignore file.

    Args:
        provider_id: Provider ID
        patterns: List of patterns to save

    Returns:
        Dict with save status
    """
    settings = get_settings()
    provider_dir = Path(settings.providers_dir) / provider_id
    provider_dir.mkdir(parents=True, exist_ok=True)

    ignore_file = provider_dir / ".dbmetaignore"

    try:
        content = "\n".join(patterns)
        ignore_file.write_text(content)
        return {
            "saved": True,
            "file_path": str(ignore_file),
            "pattern_count": len(patterns),
        }
    except Exception as e:
        return {
            "saved": False,
            "error": str(e),
        }


def add_ignore_pattern(provider_id: str, pattern: str) -> dict:
    """Add a pattern to the ignore file.

    Args:
        provider_id: Provider ID
        pattern: Pattern to add

    Returns:
        Dict with result
    """
    ignore = load_ignore_patterns(provider_id)
    pattern = pattern.strip()

    if not pattern or pattern.startswith("#"):
        return {"added": False, "error": "Invalid pattern"}

    if pattern in ignore.patterns:
        return {"added": False, "error": "Pattern already exists", "patterns": ignore.patterns}

    ignore.patterns.append(pattern)
    result = save_ignore_patterns(provider_id, ignore.patterns)

    if result.get("saved"):
        return {
            "added": True,
            "pattern": pattern,
            "total_patterns": len(ignore.patterns),
            "patterns": ignore.patterns,
        }
    return {"added": False, "error": result.get("error")}


def remove_ignore_pattern(provider_id: str, pattern: str) -> dict:
    """Remove a pattern from the ignore file.

    Args:
        provider_id: Provider ID
        pattern: Pattern to remove

    Returns:
        Dict with result
    """
    ignore = load_ignore_patterns(provider_id)
    pattern = pattern.strip()

    if pattern not in ignore.patterns:
        return {"removed": False, "error": "Pattern not found", "patterns": ignore.patterns}

    ignore.patterns.remove(pattern)
    result = save_ignore_patterns(provider_id, ignore.patterns)

    if result.get("saved"):
        return {
            "removed": True,
            "pattern": pattern,
            "total_patterns": len(ignore.patterns),
            "patterns": ignore.patterns,
        }
    return {"removed": False, "error": result.get("error")}


def import_ignore_patterns(provider_id: str, patterns: list[str], replace: bool = False) -> dict:
    """Import patterns (from LLM extraction of uploaded file).

    Args:
        provider_id: Provider ID
        patterns: List of patterns to import
        replace: If True, replace all patterns. If False, merge with existing.

    Returns:
        Dict with import result
    """
    if replace:
        new_patterns = [p.strip() for p in patterns if p.strip() and not p.startswith("#")]
    else:
        ignore = load_ignore_patterns(provider_id)
        existing = set(ignore.patterns)
        new_patterns = list(ignore.patterns)
        for p in patterns:
            p = p.strip()
            if p and not p.startswith("#") and p not in existing:
                new_patterns.append(p)
                existing.add(p)

    result = save_ignore_patterns(provider_id, new_patterns)

    if result.get("saved"):
        return {
            "imported": True,
            "total_patterns": len(new_patterns),
            "patterns": new_patterns,
        }
    return {"imported": False, "error": result.get("error")}
