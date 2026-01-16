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

    If state file doesn't exist but schema/domain files do (e.g., after
    cloning from git), automatically recovers state from existing files.

    Args:
        provider_id: Ignored in v2 (kept for backward compatibility)

    Returns:
        OnboardingState if found or recovered, None otherwise
    """
    state_file = get_state_file_path()

    if not state_file.exists():
        # Try to recover state from existing files (e.g., after git clone)
        recovered = _recover_state_from_files()
        if recovered:
            # Save the recovered state
            save_state(recovered)
            logger.info("Recovered onboarding state from existing files")
        return recovered

    try:
        with open(state_file) as f:
            state_dict = yaml.safe_load(f)

        return OnboardingState.model_validate(state_dict)
    except Exception:
        return None


def _recover_state_from_files() -> OnboardingState | None:
    """Attempt to recover onboarding state from existing files.

    This handles the case where a connection was cloned from git
    (state.yaml is gitignored) but schema/domain files exist.

    Returns:
        Recovered OnboardingState or None if no files found
    """
    conn_path = get_connection_path()

    # Check what files exist
    schema_file = conn_path / "schema" / "descriptions.yaml"
    domain_file = conn_path / "domain" / "model.md"

    has_schema = schema_file.exists()
    has_domain = domain_file.exists()

    # If neither exists, nothing to recover
    if not has_schema and not has_domain:
        return None

    logger.info(f"Recovering state: schema={has_schema}, domain={has_domain}")

    # Count tables in schema if it exists
    tables_total = 0
    if has_schema:
        try:
            with open(schema_file) as f:
                schema_data = yaml.safe_load(f)
            if schema_data and "tables" in schema_data:
                tables_total = len(schema_data["tables"])
        except Exception:
            pass

    # Determine phase based on what exists
    if has_schema and has_domain:
        phase = OnboardingPhase.COMPLETE
    elif has_schema:
        phase = OnboardingPhase.DOMAIN
    else:
        phase = OnboardingPhase.SCHEMA

    # Get provider_id from settings
    settings = get_settings()
    provider_id = settings.get_effective_provider_id()

    # Create recovered state
    return OnboardingState(
        provider_id=provider_id,
        phase=phase,
        database_url_configured=True,
        connection_verified=True,
        tables_discovered=has_schema,
        tables_total=tables_total,
        domain_model_generated=has_domain,
        domain_model_approved=has_domain,
        started_at=datetime.now(UTC),
        last_updated_at=datetime.now(UTC),
    )


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
