"""Knowledge vault package."""

from db_meta_v2.vault.init import ensure_connection_structure, ensure_vault_structure
from db_meta_v2.vault.migrate import migrate_legacy_provider_data, migrate_to_connection_structure

__all__ = [
    # New connection-based functions
    "ensure_connection_structure",
    "migrate_to_connection_structure",
    # Legacy aliases (deprecated)
    "ensure_vault_structure",
    "migrate_legacy_provider_data",
]
