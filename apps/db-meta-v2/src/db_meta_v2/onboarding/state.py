"""Onboarding state persistence."""

from datetime import UTC, datetime
from pathlib import Path

import yaml
from sg_models import OnboardingPhase, OnboardingState

from db_meta_v2.config import get_settings


def get_provider_dir(provider_id: str) -> Path:
    """Get the directory for a provider's artifacts.

    Args:
        provider_id: Provider identifier

    Returns:
        Path to provider directory
    """
    settings = get_settings()
    return Path(settings.providers_dir) / provider_id


def get_state_file_path(provider_id: str) -> Path:
    """Get path to the onboarding state file.

    Args:
        provider_id: Provider identifier

    Returns:
        Path to state YAML file
    """
    return get_provider_dir(provider_id) / "onboarding_state.yaml"


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
        # Ensure provider directory exists
        provider_dir = get_provider_dir(state.provider_id)
        provider_dir.mkdir(parents=True, exist_ok=True)

        # Update timestamp
        state.last_updated_at = datetime.now(UTC)

        # Convert to dict for YAML serialization
        state_dict = state.model_dump(mode="json")

        # Write to file
        state_file = get_state_file_path(state.provider_id)
        with open(state_file, "w") as f:
            yaml.dump(state_dict, f, default_flow_style=False, sort_keys=False)

        return {
            "saved": True,
            "provider_id": state.provider_id,
            "file_path": str(state_file),
            "error": None,
        }
    except Exception as e:
        return {
            "saved": False,
            "provider_id": state.provider_id,
            "file_path": None,
            "error": str(e),
        }


def load_state(provider_id: str) -> OnboardingState | None:
    """Load onboarding state from YAML file.

    Args:
        provider_id: Provider identifier

    Returns:
        OnboardingState if found, None otherwise
    """
    state_file = get_state_file_path(provider_id)

    if not state_file.exists():
        return None

    try:
        with open(state_file) as f:
            state_dict = yaml.safe_load(f)

        return OnboardingState.model_validate(state_dict)
    except Exception:
        return None


def delete_state(provider_id: str) -> dict:
    """Delete onboarding state file.

    Args:
        provider_id: Provider identifier

    Returns:
        Dict with delete status
    """
    state_file = get_state_file_path(provider_id)

    if not state_file.exists():
        return {
            "deleted": False,
            "provider_id": provider_id,
            "error": "State file not found",
        }

    try:
        state_file.unlink()
        return {
            "deleted": True,
            "provider_id": provider_id,
            "error": None,
        }
    except Exception as e:
        return {
            "deleted": False,
            "provider_id": provider_id,
            "error": str(e),
        }
