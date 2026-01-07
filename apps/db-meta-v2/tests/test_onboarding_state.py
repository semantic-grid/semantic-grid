"""Tests for onboarding state persistence."""

import tempfile
from pathlib import Path

import pytest
from sg_models import OnboardingPhase

from db_meta_v2.onboarding.state import (
    create_initial_state,
    delete_state,
    load_state,
    save_state,
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


def test_create_initial_state():
    """Test creating initial onboarding state."""
    state = create_initial_state("test-provider")

    assert state.provider_id == "test-provider"
    assert state.phase == OnboardingPhase.NOT_STARTED
    assert state.started_at is not None
    assert state.database_url_configured is False
    assert state.tables_total == 0


def test_save_and_load_state(temp_providers_dir):
    """Test saving and loading state."""
    # Create and save state
    state = create_initial_state("test-provider")
    state.phase = OnboardingPhase.INIT
    state.database_url_configured = True
    state.dialect_detected = "postgresql"

    result = save_state(state)
    assert result["saved"] is True
    assert result["error"] is None

    # Verify file exists
    state_file = Path(temp_providers_dir) / "test-provider" / "onboarding_state.yaml"
    assert state_file.exists()

    # Load and verify
    loaded = load_state("test-provider")
    assert loaded is not None
    assert loaded.provider_id == "test-provider"
    assert loaded.phase == OnboardingPhase.INIT
    assert loaded.database_url_configured is True
    assert loaded.dialect_detected == "postgresql"


def test_load_nonexistent_state(temp_providers_dir):
    """Test loading state that doesn't exist."""
    loaded = load_state("nonexistent-provider")
    assert loaded is None


def test_delete_state(temp_providers_dir):
    """Test deleting state."""
    # Create and save state
    state = create_initial_state("test-provider")
    save_state(state)

    # Verify exists
    assert load_state("test-provider") is not None

    # Delete
    result = delete_state("test-provider")
    assert result["deleted"] is True

    # Verify deleted
    assert load_state("test-provider") is None


def test_delete_nonexistent_state(temp_providers_dir):
    """Test deleting state that doesn't exist."""
    result = delete_state("nonexistent-provider")
    assert result["deleted"] is False
    assert "not found" in result["error"]


def test_state_progress_calculation():
    """Test progress percentage calculation."""
    state = create_initial_state("test")

    # Not started
    assert state.progress_percentage() == 0

    # Init phase
    state.phase = OnboardingPhase.INIT
    assert state.progress_percentage() == 10

    # Schema phase with progress (tables_described is now passed as arg)
    state.phase = OnboardingPhase.SCHEMA
    state.tables_total = 10
    progress = state.progress_percentage(tables_described=5)
    assert 10 < progress <= 40

    # Schema phase with no progress
    progress_zero = state.progress_percentage(tables_described=0)
    assert progress_zero == 10  # base for SCHEMA phase
