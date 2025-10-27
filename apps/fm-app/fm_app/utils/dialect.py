"""
Database dialect detection utilities.
"""

from typing import Optional

from fm_app.api.db_session import wh_engine
from fm_app.config import get_settings


def get_warehouse_dialect() -> str:
    """
    Detect warehouse database dialect.

    Returns dialect name compatible with sqlglot:
    - 'clickhouse'
    - 'postgresql'
    - 'mysql'
    - etc.

    Returns:
        Dialect name (lowercase)
    """
    try:
        # Get dialect from SQLAlchemy engine
        dialect_name = wh_engine.dialect.name

        # Normalize dialect names for sqlglot compatibility
        dialect_map = {
            "clickhouse": "clickhouse",
            "postgresql": "postgres",  # sqlglot uses 'postgres'
            "postgres": "postgres",
            "mysql": "mysql",
            "sqlite": "sqlite",
            "mssql": "tsql",  # SQL Server
            "oracle": "oracle",
        }

        return dialect_map.get(dialect_name.lower(), dialect_name.lower())

    except Exception:
        # Fallback: try to detect from settings
        settings = get_settings()
        driver = settings.database_wh_driver or ""

        # Parse driver string (e.g., "clickhouse+native", "postgresql+psycopg2")
        if "clickhouse" in driver.lower():
            return "clickhouse"
        elif "postgres" in driver.lower():
            return "postgres"
        elif "mysql" in driver.lower():
            return "mysql"
        elif "mssql" in driver.lower() or "sqlserver" in driver.lower():
            return "tsql"
        else:
            # Default fallback
            return "clickhouse"


def get_dialect_from_query(
    query_metadata: Optional[dict] = None,
) -> str:
    """
    Get dialect from query metadata or fall back to warehouse dialect.

    Args:
        query_metadata: Optional query metadata dict with db_dialect field

    Returns:
        Dialect name
    """
    if query_metadata and isinstance(query_metadata, dict):
        dialect = query_metadata.get("db_dialect")
        if dialect:
            return dialect.lower()

    # Fallback to warehouse dialect
    return get_warehouse_dialect()


# Cache the dialect to avoid repeated detection
_CACHED_DIALECT: Optional[str] = None


def get_cached_warehouse_dialect() -> str:
    """
    Get warehouse dialect with caching for performance.

    Returns:
        Dialect name
    """
    global _CACHED_DIALECT

    if _CACHED_DIALECT is None:
        _CACHED_DIALECT = get_warehouse_dialect()

    return _CACHED_DIALECT
