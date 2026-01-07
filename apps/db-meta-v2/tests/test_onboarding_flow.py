"""Tests for onboarding flow - start, discover, reset."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sg_models import OnboardingPhase

from db_meta_v2.onboarding.schema_store import get_schema_file_path
from db_meta_v2.onboarding.state import create_initial_state, load_state, save_state
from db_meta_v2.tools.onboarding import (
    _onboarding_discover,
    _onboarding_reset,
    _onboarding_start,
    _onboarding_status,
)


@pytest.fixture
def temp_providers_dir(monkeypatch):
    """Create a temporary providers directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("PROVIDERS_DIR", tmpdir)

        # Clear cached settings
        import db_meta_v2.config

        db_meta_v2.config._settings = None

        yield tmpdir


@pytest.fixture
def mock_db_connection():
    """Mock database connection for testing without real DB."""
    with patch("db_meta_v2.tools.onboarding.test_connection") as mock_conn:
        mock_conn.return_value = {
            "connected": True,
            "dialect": "trino",
            "url_host": "localhost",
            "url_database": "test_catalog/test_schema",
            "error": None,
        }
        yield mock_conn


@pytest.fixture
def mock_introspection():
    """Mock database introspection functions."""
    with (
        patch("db_meta_v2.tools.onboarding.get_catalogs") as mock_catalogs,
        patch("db_meta_v2.tools.onboarding.get_schemas") as mock_schemas,
        patch("db_meta_v2.tools.onboarding.get_tables") as mock_tables,
        patch("db_meta_v2.tools.onboarding.get_columns") as mock_columns,
    ):
        mock_catalogs.return_value = ["test_catalog"]
        mock_schemas.return_value = ["test_schema"]
        mock_tables.return_value = [
            {
                "name": "users",
                "schema": "test_schema",
                "catalog": "test_catalog",
                "type": "table",
                "full_name": "test_catalog.test_schema.users",
            },
            {
                "name": "orders",
                "schema": "test_schema",
                "catalog": "test_catalog",
                "type": "table",
                "full_name": "test_catalog.test_schema.orders",
            },
        ]
        mock_columns.return_value = [
            {"name": "id", "type": "INTEGER", "nullable": False},
            {"name": "name", "type": "VARCHAR", "nullable": True},
        ]

        yield {
            "catalogs": mock_catalogs,
            "schemas": mock_schemas,
            "tables": mock_tables,
            "columns": mock_columns,
        }


class TestOnboardingStart:
    """Tests for onboarding_start."""

    @pytest.mark.asyncio
    async def test_start_success(self, temp_providers_dir, mock_db_connection):
        """Test successful onboarding start."""
        result = await _onboarding_start(provider_id="test-provider")

        assert result["started"] is True
        assert result["provider_id"] == "test-provider"
        assert result["dialect"] == "trino"
        assert result["phase"] == "init"
        assert "ignore_patterns" in result

        # Verify state was saved
        state = load_state("test-provider")
        assert state is not None
        assert state.phase == OnboardingPhase.INIT
        assert state.dialect_detected == "trino"

    @pytest.mark.asyncio
    async def test_start_already_started(self, temp_providers_dir, mock_db_connection):
        """Test starting when already started (without force)."""
        # First start
        await _onboarding_start(provider_id="test-provider")

        # Try to start again without force
        result = await _onboarding_start(provider_id="test-provider")

        assert result["started"] is False
        assert "already started" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_start_force_cleans_up(
        self, temp_providers_dir, mock_db_connection, mock_introspection
    ):
        """Test that force=True cleans up existing state and schema files."""
        # First start and discover
        await _onboarding_start(provider_id="test-provider")
        await _onboarding_discover(provider_id="test-provider")

        # Verify we're in schema phase
        state = load_state("test-provider")
        assert state.phase == OnboardingPhase.SCHEMA

        # Verify schema file exists
        schema_file = get_schema_file_path("test-provider")
        assert schema_file.exists()

        # Force restart
        result = await _onboarding_start(provider_id="test-provider", force=True)

        assert result["started"] is True
        assert result["phase"] == "init"

        # Verify state is back to INIT
        state = load_state("test-provider")
        assert state.phase == OnboardingPhase.INIT

        # Verify schema file was deleted
        assert not schema_file.exists()

    @pytest.mark.asyncio
    async def test_start_connection_failed(self, temp_providers_dir):
        """Test start when DB connection fails."""
        with patch("db_meta_v2.tools.onboarding.test_connection") as mock_conn:
            mock_conn.return_value = {
                "connected": False,
                "error": "Connection refused",
            }

            result = await _onboarding_start(provider_id="test-provider")

            assert result["started"] is False
            assert "connection failed" in result["error"].lower()


class TestOnboardingDiscover:
    """Tests for onboarding_discover."""

    @pytest.mark.asyncio
    async def test_discover_success(
        self, temp_providers_dir, mock_db_connection, mock_introspection
    ):
        """Test successful schema discovery."""
        # Start first
        await _onboarding_start(provider_id="test-provider")

        # Then discover
        result = await _onboarding_discover(provider_id="test-provider")

        assert result["discovered"] is True
        assert result["tables_found"] == 2
        assert result["phase"] == "schema"

        # Verify state updated
        state = load_state("test-provider")
        assert state.phase == OnboardingPhase.SCHEMA
        assert state.tables_total == 2

        # Verify schema file created
        schema_file = get_schema_file_path("test-provider")
        assert schema_file.exists()

    @pytest.mark.asyncio
    async def test_discover_not_started(self, temp_providers_dir):
        """Test discover when onboarding not started."""
        result = await _onboarding_discover(provider_id="test-provider")

        assert result["discovered"] is False
        assert "not started" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_discover_already_discovered(
        self, temp_providers_dir, mock_db_connection, mock_introspection
    ):
        """Test discover when already in schema phase."""
        # Start and discover
        await _onboarding_start(provider_id="test-provider")
        await _onboarding_discover(provider_id="test-provider")

        # Try to discover again
        result = await _onboarding_discover(provider_id="test-provider")

        assert result["discovered"] is False
        assert "already discovered" in result["error"].lower()


class TestOnboardingReset:
    """Tests for onboarding_reset."""

    @pytest.mark.asyncio
    async def test_reset_success(self, temp_providers_dir, mock_db_connection, mock_introspection):
        """Test successful reset."""
        # Start and discover
        await _onboarding_start(provider_id="test-provider")
        await _onboarding_discover(provider_id="test-provider")

        # Reset
        result = await _onboarding_reset(provider_id="test-provider")

        assert result["reset"] is True

        # Verify state deleted
        state = load_state("test-provider")
        assert state is None

    @pytest.mark.asyncio
    async def test_reset_hard_deletes_schema(
        self, temp_providers_dir, mock_db_connection, mock_introspection
    ):
        """Test hard reset deletes schema file too."""
        # Start and discover
        await _onboarding_start(provider_id="test-provider")
        await _onboarding_discover(provider_id="test-provider")

        # Verify schema file exists
        schema_file = get_schema_file_path("test-provider")
        assert schema_file.exists()

        # Hard reset
        result = await _onboarding_reset(provider_id="test-provider", hard=True)

        assert result["reset"] is True
        assert result["schema_deleted"] is True

        # Verify both deleted
        assert load_state("test-provider") is None
        assert not schema_file.exists()

    @pytest.mark.asyncio
    async def test_reset_not_started(self, temp_providers_dir):
        """Test reset when nothing to reset."""
        result = await _onboarding_reset(provider_id="test-provider")

        # Should fail gracefully
        assert result["reset"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_hard_reset_succeeds_even_if_no_state(self, temp_providers_dir):
        """Test hard reset returns success even if state file doesn't exist."""
        result = await _onboarding_reset(provider_id="test-provider", hard=True)

        # Hard reset should succeed (we've reset to clean state)
        assert result["reset"] is True


class TestOnboardingFlowIntegration:
    """Integration tests for the full onboarding flow."""

    @pytest.mark.asyncio
    async def test_full_flow_start_discover_reset(
        self, temp_providers_dir, mock_db_connection, mock_introspection
    ):
        """Test complete flow: start -> discover -> reset -> start again."""
        provider = "integration-test"

        # 1. Check status - not started
        status = await _onboarding_status(provider_id=provider)
        assert status["status"] == "not_started"

        # 2. Start
        start_result = await _onboarding_start(provider_id=provider)
        assert start_result["started"] is True
        assert start_result["phase"] == "init"

        # 3. Check status - init
        status = await _onboarding_status(provider_id=provider)
        assert status["phase"] == "init"

        # 4. Discover
        discover_result = await _onboarding_discover(provider_id=provider)
        assert discover_result["discovered"] is True
        assert discover_result["tables_found"] == 2

        # 5. Check status - schema
        status = await _onboarding_status(provider_id=provider)
        assert status["phase"] == "schema"
        assert status["tables_total"] == 2

        # 6. Hard reset
        reset_result = await _onboarding_reset(provider_id=provider, hard=True)
        assert reset_result["reset"] is True

        # 7. Check status - not started
        status = await _onboarding_status(provider_id=provider)
        assert status["status"] == "not_started"

        # 8. Start again
        start_result = await _onboarding_start(provider_id=provider)
        assert start_result["started"] is True

    @pytest.mark.asyncio
    async def test_force_restart_from_schema_phase(
        self, temp_providers_dir, mock_db_connection, mock_introspection
    ):
        """Test force restart when already in schema phase."""
        provider = "force-test"

        # Start and discover
        await _onboarding_start(provider_id=provider)
        await _onboarding_discover(provider_id=provider)

        # Verify in schema phase
        state = load_state(provider)
        assert state.phase == OnboardingPhase.SCHEMA

        # Force start
        result = await _onboarding_start(provider_id=provider, force=True)
        assert result["started"] is True
        assert result["phase"] == "init"

        # Verify back in init
        state = load_state(provider)
        assert state.phase == OnboardingPhase.INIT

        # Should be able to discover again
        discover_result = await _onboarding_discover(provider_id=provider)
        assert discover_result["discovered"] is True
