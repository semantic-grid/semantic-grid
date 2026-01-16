"""Onboarding state persistence."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sg_models import OnboardingPhase, OnboardingState

from db_meta_v2.config import get_settings

logger = logging.getLogger(__name__)


def get_connection_path() -> Path:
    """Get the current connection directory path.

    Returns:
        Path to connection directory
    """
    settings = get_settings()
    return settings.get_effective_connection_path()


def get_provider_dir(provider_id: str | None = None) -> Path:
    """Get the directory for connection artifacts.

    DEPRECATED: Use get_connection_path() instead.

    Args:
        provider_id: Ignored in v2 (kept for backward compatibility)

    Returns:
        Path to connection directory
    """
    # In v2, we ignore provider_id and use the connection path
    return get_connection_path()


def get_state_file_path(provider_id: str | None = None) -> Path:
    """Get path to the onboarding state file.

    Args:
        provider_id: Ignored in v2 (kept for backward compatibility)

    Returns:
        Path to state YAML file
    """
    return get_connection_path() / "state.yaml"


def create_initial_state(provider_id: str) -> OnboardingState:
    """Create initial onboarding state for a provider.

    Args:
        provider_id: Provider identifier

    Returns:
        New OnboardingState instance
    """
    return OnboardingState(
        provider_id=provider_id,
        phase=OnboardingPhase.NOT_STARTED,
        started_at=datetime.now(UTC),
    )


def save_state(state: OnboardingState) -> dict:
    """Save onboarding state to YAML file.

    Args:
        state: OnboardingState to save

    Returns:
        Dict with save status
    """
    try:
        # Ensure connection directory exists
        conn_path = get_connection_path()
        conn_path.mkdir(parents=True, exist_ok=True)

        # Update timestamp
        state.last_updated_at = datetime.now(UTC)

        # Convert to dict for YAML serialization
        state_dict = state.model_dump(mode="json")

        # Write to file
        state_file = get_state_file_path()
        with open(state_file, "w") as f:
            yaml.dump(state_dict, f, default_flow_style=False, sort_keys=False)

        return {
            "saved": True,
            "connection": str(conn_path),
            "file_path": str(state_file),
            "error": None,
        }
    except Exception as e:
        return {
            "saved": False,
            "connection": None,
            "file_path": None,
            "error": str(e),
        }


def load_state(provider_id: str | None = None) -> OnboardingState | None:
    """Load onboarding state from YAML file.

    Args:
        provider_id: Ignored in v2 (kept for backward compatibility)

    Returns:
        OnboardingState if found, None otherwise
    """
    state_file = get_state_file_path()

    if not state_file.exists():
        return None

    try:
        with open(state_file) as f:
            state_dict = yaml.safe_load(f)

        return OnboardingState.model_validate(state_dict)
    except Exception:
        return None


def delete_state(provider_id: str | None = None) -> dict:
    """Delete onboarding state file.

    Args:
        provider_id: Ignored in v2 (kept for backward compatibility)

    Returns:
        Dict with delete status
    """
    state_file = get_state_file_path()
    conn_path = get_connection_path()

    if not state_file.exists():
        return {
            "deleted": False,
            "connection": str(conn_path),
            "error": "State file not found",
        }

    try:
        state_file.unlink()
        return {
            "deleted": True,
            "connection": str(conn_path),
            "error": None,
        }
    except Exception as e:
        return {
            "deleted": False,
            "connection": str(conn_path),
            "error": str(e),
        }
