"""Knowledge vault package."""

from db_meta_v2.vault.init import ensure_vault_structure
from db_meta_v2.vault.migrate import migrate_legacy_provider_data

__all__ = ["ensure_vault_structure", "migrate_legacy_provider_data"]
