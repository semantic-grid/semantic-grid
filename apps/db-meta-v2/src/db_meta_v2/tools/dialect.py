"""SQL dialect MCP tools."""

from db_meta_v2.dialect import get_dialect_for_connection, load_dialect_rules


async def _get_dialect_rules(dialect: str) -> dict:
    """Get SQL dialect rules for a specific dialect.

    Args:
        dialect: Dialect name (trino, postgresql, clickhouse)

    Returns:
        Dialect rules and metadata
    """
    return load_dialect_rules(dialect)


async def _get_connection_dialect() -> dict:
    """Detect dialect from configured database and load rules.

    Returns:
        Detected dialect and rules for the configured database
    """
    return get_dialect_for_connection()
