"""Database connection management."""

import urllib.parse
from functools import lru_cache

import urllib3
from sqlalchemy import Engine, create_engine, text
from trino.auth import BasicAuthentication

from db_meta_v2.config import get_settings

# Disable urllib3 SSL warnings for Trino connections with verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class DatabaseError(Exception):
    """Database connection or query error."""

    pass


def detect_dialect_from_url(database_url: str) -> str:
    """Detect SQL dialect from database URL.

    Args:
        database_url: SQLAlchemy-compatible database URL

    Returns:
        Dialect name: 'trino', 'postgresql', 'clickhouse', 'mysql', etc.
    """
    if not database_url:
        return "unknown"

    # Parse the URL to get the scheme/driver
    parsed = urllib.parse.urlparse(database_url)
    scheme = parsed.scheme.lower()

    # Handle driver specifications (e.g., postgresql+psycopg2)
    dialect = scheme.split("+")[0]

    # Normalize common variations
    dialect_map = {
        "postgres": "postgresql",
        "psycopg2": "postgresql",
        "clickhouse": "clickhouse",
        "clickhousedb": "clickhouse",
        "trino": "trino",
        "mysql": "mysql",
        "mariadb": "mysql",
        "pymysql": "mysql",
        "mysqlconnector": "mysql",
        "mssql": "mssql",
        "sqlserver": "mssql",
        "pyodbc": "mssql",
        "pymssql": "mssql",
        "sqlite": "sqlite",
        "sqlite3": "sqlite",
    }

    return dialect_map.get(dialect, dialect)


def normalize_database_url(database_url: str) -> str:
    """Normalize database URL for SQLAlchemy compatibility.

    Args:
        database_url: Database URL that may need normalization

    Returns:
        Normalized URL compatible with SQLAlchemy
    """
    if not database_url:
        return database_url

    # Replace 'postgres://' with 'postgresql://' for SQLAlchemy
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[11:]

    return database_url


@lru_cache(maxsize=8)
def get_engine(database_url: str | None = None) -> Engine:
    """Get or create a SQLAlchemy engine.

    Args:
        database_url: Optional database URL. If not provided, uses settings.

    Returns:
        SQLAlchemy Engine instance

    Raises:
        DatabaseError: If no database URL is configured
    """
    if database_url is None:
        settings = get_settings()
        database_url = settings.database_url

    if not database_url:
        raise DatabaseError("No database URL configured")

    normalized_url = normalize_database_url(database_url)
    dialect = detect_dialect_from_url(normalized_url)

    # Configure engine based on dialect
    engine_kwargs = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    if dialect == "trino":
        # Trino-specific configuration
        # Extract username/password from URL for BasicAuthentication
        parsed = urllib.parse.urlparse(normalized_url)
        username = urllib.parse.unquote(parsed.username) if parsed.username else None
        password = urllib.parse.unquote(parsed.password) if parsed.password else None

        connect_args = {
            "http_scheme": "https",
            "verify": False,  # TODO: Make configurable for production
        }

        # Add BasicAuthentication if credentials are in the URL
        if username and password:
            connect_args["auth"] = BasicAuthentication(username, password)

        engine_kwargs["connect_args"] = connect_args

    try:
        engine = create_engine(normalized_url, **engine_kwargs)
        return engine
    except Exception as e:
        raise DatabaseError(f"Failed to create database engine: {e}") from e


def test_connection(database_url: str | None = None) -> dict:
    """Test database connection.

    Args:
        database_url: Optional database URL. If not provided, uses settings.

    Returns:
        Dict with connection status and info
    """
    try:
        engine = get_engine(database_url)
        dialect = detect_dialect_from_url(str(engine.url))

        with engine.connect() as conn:
            # Execute a simple query to verify connection
            if dialect == "trino":
                result = conn.execute(text("SELECT 1"))
            elif dialect == "clickhouse":
                result = conn.execute(text("SELECT 1"))
            else:
                result = conn.execute(text("SELECT 1"))

            result.fetchone()

        return {
            "connected": True,
            "dialect": dialect,
            "url_host": engine.url.host,
            "url_database": engine.url.database,
            "error": None,
        }
    except DatabaseError as e:
        return {
            "connected": False,
            "dialect": None,
            "url_host": None,
            "url_database": None,
            "error": str(e),
        }
    except Exception as e:
        return {
            "connected": False,
            "dialect": None,
            "url_host": None,
            "url_database": None,
            "error": f"Connection failed: {e}",
        }
