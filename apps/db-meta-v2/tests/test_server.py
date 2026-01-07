"""Tests for the MCP server."""

import pytest

from db_meta_v2.server import _get_config, _ping, mcp


def test_mcp_server_created():
    """Test MCP server is properly configured."""
    assert mcp.name == "db-meta-v2"


@pytest.mark.asyncio
async def test_ping():
    """Test ping tool returns ok status."""
    result = await _ping()
    assert result["status"] == "ok"
    assert "provider_id" in result
    assert "database_configured" in result


@pytest.mark.asyncio
async def test_get_config():
    """Test get_config tool returns configuration."""
    result = await _get_config()
    assert "provider_id" in result
    assert "resources_dir" in result
    assert "providers_dir" in result
    assert "database_configured" in result
