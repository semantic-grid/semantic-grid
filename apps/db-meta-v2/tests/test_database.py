"""Tests for database connectivity and introspection."""

import pytest

from db_meta_v2.db.connection import detect_dialect_from_url, normalize_database_url
from db_meta_v2.tools.database import _detect_dialect


def test_detect_dialect_trino():
    """Test Trino dialect detection."""
    assert detect_dialect_from_url("trino://user:pass@host:8080/catalog") == "trino"


def test_detect_dialect_postgresql():
    """Test PostgreSQL dialect detection."""
    assert detect_dialect_from_url("postgresql://user:pass@host:5432/db") == "postgresql"
    assert detect_dialect_from_url("postgres://user:pass@host:5432/db") == "postgresql"
    assert detect_dialect_from_url("postgresql+psycopg2://user:pass@host/db") == "postgresql"


def test_detect_dialect_clickhouse():
    """Test ClickHouse dialect detection."""
    assert detect_dialect_from_url("clickhouse://user:pass@host:8123/db") == "clickhouse"
    assert detect_dialect_from_url("clickhouse+native://user:pass@host/db") == "clickhouse"


def test_detect_dialect_mysql():
    """Test MySQL dialect detection."""
    assert detect_dialect_from_url("mysql://user:pass@host:3306/db") == "mysql"
    assert detect_dialect_from_url("mariadb://user:pass@host:3306/db") == "mysql"


def test_detect_dialect_unknown():
    """Test unknown dialect handling."""
    assert detect_dialect_from_url("") == "unknown"
    assert detect_dialect_from_url("somedb://host/db") == "somedb"


def test_normalize_database_url():
    """Test database URL normalization."""
    # postgres -> postgresql
    assert normalize_database_url("postgres://host/db") == "postgresql://host/db"
    # postgresql stays the same
    assert normalize_database_url("postgresql://host/db") == "postgresql://host/db"
    # Other URLs unchanged
    assert normalize_database_url("trino://host/db") == "trino://host/db"
    # Empty URL
    assert normalize_database_url("") == ""


@pytest.mark.asyncio
async def test_detect_dialect_tool():
    """Test detect dialect MCP tool."""
    result = await _detect_dialect("trino://user:pass@host:8080/catalog")
    assert result["dialect"] == "trino"
    assert result["database_url_prefix"] == "trino"
