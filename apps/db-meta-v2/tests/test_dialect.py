"""Tests for SQL dialect loading."""

import pytest

from db_meta_v2.dialect import get_dialect_file_path, load_dialect_rules
from db_meta_v2.tools.dialect import _get_dialect_rules


def test_get_dialect_file_path_trino(monkeypatch):
    """Test finding Trino dialect file."""
    # Use the actual resources path
    monkeypatch.setenv("RESOURCES_DIR", "../../packages/resources/dbmeta_app")

    # Clear cached settings
    import db_meta_v2.config

    db_meta_v2.config._settings = None

    path = get_dialect_file_path("trino")
    assert path is not None
    assert path.exists()
    assert "trino.yaml" in str(path)


def test_load_dialect_rules_trino(monkeypatch):
    """Test loading Trino dialect rules."""
    monkeypatch.setenv("RESOURCES_DIR", "../../packages/resources/dbmeta_app")

    import db_meta_v2.config

    db_meta_v2.config._settings = None

    result = load_dialect_rules("trino")
    assert result["found"] is True
    assert result["dialect"] == "trino"
    assert len(result["rules"]) > 0
    assert result["error"] is None


def test_load_dialect_rules_postgresql(monkeypatch):
    """Test loading PostgreSQL dialect rules."""
    monkeypatch.setenv("RESOURCES_DIR", "../../packages/resources/dbmeta_app")

    import db_meta_v2.config

    db_meta_v2.config._settings = None

    result = load_dialect_rules("postgresql")
    assert result["found"] is True
    assert result["dialect"] == "postgresql"
    assert len(result["rules"]) > 0


def test_load_dialect_rules_unknown(monkeypatch):
    """Test loading unknown dialect."""
    monkeypatch.setenv("RESOURCES_DIR", "../../packages/resources/dbmeta_app")

    import db_meta_v2.config

    db_meta_v2.config._settings = None

    result = load_dialect_rules("unknowndb")
    assert result["found"] is False
    assert result["dialect"] == "unknowndb"
    assert "No dialect file found" in result["error"]


@pytest.mark.asyncio
async def test_get_dialect_rules_tool(monkeypatch):
    """Test get_dialect_rules MCP tool."""
    monkeypatch.setenv("RESOURCES_DIR", "../../packages/resources/dbmeta_app")

    import db_meta_v2.config

    db_meta_v2.config._settings = None

    result = await _get_dialect_rules("trino")
    assert result["found"] is True
    assert "rules" in result
    assert len(result["rules"]) > 0
