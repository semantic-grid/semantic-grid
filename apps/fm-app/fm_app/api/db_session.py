import logging

import urllib3
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from trino.auth import BasicAuthentication

from fm_app.config import get_settings

# Disable urllib3 SSL warnings for Trino connections with verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
    parts = driver.split("+", 1)
    dialect = parts[0].lower()

    # Normalize 'postgres' to 'postgresql' for SQLAlchemy
    if dialect == "postgres":
        dialect = "postgresql"

    # Reconstruct with driver if present
    if len(parts) > 1:
        return f"{dialect}+{parts[1]}"
    return dialect


settings = get_settings()
DATABASE_URL = f"postgresql+asyncpg://{settings.database_user}:{settings.database_pass}@{settings.database_server}:{settings.database_port}/{settings.database_db}"

engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,  # Base pool size per pod
    max_overflow=15,  # Allow burst to 25 total connections per pod
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=300,  # Recycle idle connections after 5 minutes
    pool_timeout=30,  # Fail fast if no connections available after 30s
    connect_args={
        "server_settings": {"application_name": "fm_app_api"},
    },
)

SESSION = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with SESSION() as session:
        yield session


# Normalize driver to handle 'postgres' -> 'postgresql' conversion
normalized_driver = normalize_database_driver(settings.database_wh_driver)
WH_URL = f"{normalized_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_v2}:{settings.database_wh_port_v2}/{settings.database_wh_db_v2}{settings.database_wh_params_v2}"
if normalized_driver == "trino":
    logging.info("Starting Trino session")
    wh_engine = create_engine(
        WH_URL,
        echo=False,  # Disable SQLAlchemy query logging
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=360,
        connect_args={
            "http_scheme": "https",
            # Use a CA file path instead in prod, e.g. "/path/to/ca.crt"
            "verify": False,
            "auth": BasicAuthentication(
                settings.database_wh_user, settings.database_wh_pass
            ),
            "application_name": "fm_app_api_wh",
        },
    )
else:
    logging.info(f"Starting {normalized_driver} session")
    wh_engine = create_engine(
        WH_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=360,
        connect_args={"application_name": "fm_app_api_wh"},
    )

wh_session = sessionmaker(bind=wh_engine, expire_on_commit=False)


def get_wh_db() -> Session:
    session = wh_session()
    return session
