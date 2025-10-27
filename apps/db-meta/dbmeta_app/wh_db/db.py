from sqlalchemy import Engine, create_engine

from dbmeta_app.config import get_settings


def normalize_database_driver(driver: str) -> str:
    """
    Normalize database driver string for SQLAlchemy compatibility.

    SQLAlchemy expects 'postgresql' not 'postgres' as the dialect name.
    This function normalizes common variations to the correct SQLAlchemy format.

    Args:
        driver: Database driver string (e.g., 'postgres+psycopg2', 'clickhouse+native')

    Returns:
        Normalized driver string compatible with SQLAlchemy

    Examples:
        >>> normalize_database_driver('postgres+psycopg2')
        'postgresql+psycopg2'
        >>> normalize_database_driver('postgres')
        'postgresql'
        >>> normalize_database_driver('clickhouse+native')
        'clickhouse+native'
    """
    if not driver:
        return driver

    # Split on '+' to separate dialect from driver
    parts = driver.split('+', 1)
    dialect = parts[0].lower()

    # Normalize 'postgres' to 'postgresql' for SQLAlchemy
    if dialect == 'postgres':
        dialect = 'postgresql'

    # Reconstruct with driver if present
    if len(parts) > 1:
        return f"{dialect}+{parts[1]}"
    return dialect


def get_db() -> Engine:
    settings = get_settings()
    # Normalize driver to handle 'postgres' -> 'postgresql' conversion
    normalized_driver = normalize_database_driver(settings.database_wh_driver)
    url = f"{normalized_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_v2}:{settings.database_wh_port_v2}/{settings.database_wh_db_v2}{settings.database_wh_params_v2}"  # noqa: E501
    return create_engine(
        url, pool_size=20, max_overflow=30, pool_pre_ping=True, pool_recycle=360
    )
