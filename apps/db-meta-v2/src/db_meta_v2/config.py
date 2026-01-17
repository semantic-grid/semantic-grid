"""Configuration for db-meta-v2."""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Storage format version
STORAGE_VERSION = 2


def _get_env_files() -> list[Path]:
    """Get list of .env files to load, in priority order.

    Priority (later files override earlier):
    1. Current directory .env (if exists)
    2. Connection-specific .env (from CONNECTION_PATH or CONNECTIONS_DIR/CONNECTION_NAME)
    """
    env_files = []

    # 1. Current directory .env
    cwd_env = Path(".env")
    if cwd_env.exists():
        env_files.append(cwd_env)

    # 2. Connection-specific .env
    connection_path = os.environ.get("CONNECTION_PATH", "")
    if connection_path:
        conn_env = Path(connection_path) / ".env"
        if conn_env.exists():
            env_files.append(conn_env)
    else:
        # Try connections_dir + connection_name
        connections_dir = os.environ.get("CONNECTIONS_DIR", "")
        connection_name = os.environ.get("CONNECTION_NAME", "default")
        if connections_dir:
            conn_env = Path(connections_dir) / connection_name / ".env"
            if conn_env.exists():
                env_files.append(conn_env)
        else:
            # Default location
            conn_env = Path.home() / ".dbmeta" / "connections" / connection_name / ".env"
            if conn_env.exists():
                env_files.append(conn_env)

    return env_files


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=_get_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==========================================================================
    # Connection configuration (v2 structure)
    # ==========================================================================

    # Connection path - new unified path for all connection data
    connection_path: str = Field(
        default="",
        description="Path to connection directory (contains schema, examples, etc.)",
    )

    # Connection name - used with connections_dir for local CLI
    connection_name: str = Field(
        default="default",
        description="Connection name (used with connections_dir for local CLI)",
    )

    # Connections directory - base path for multiple connections (local CLI)
    connections_dir: str = Field(
        default="",
        description="Base directory for connections (local CLI mode)",
    )

    # ==========================================================================
    # Database connection
    # ==========================================================================

    database_url: str = Field(
        default="",
        description="Database connection URL (e.g., trino://user:pass@host:port/catalog/schema)",
    )

    # Component-based DB config (reuses existing db-meta secrets)
    database_wh_driver: str = Field(default="", description="DB driver (trino, clickhouse+native)")
    database_wh_server_v2: str = Field(default="", description="DB server host")
    database_wh_port_v2: str = Field(default="", description="DB server port")
    database_wh_user: str = Field(default="", description="DB username")
    database_wh_pass: str = Field(default="", description="DB password")
    database_wh_db_v2: str = Field(default="", description="DB name/catalog/schema")
    database_wh_params_v2: str = Field(default="", description="DB connection params")

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        """Build database_url from components if not directly provided."""
        if self.database_url:
            return self

        # Build URL from components if available
        if self.database_wh_server_v2 and self.database_wh_driver:
            driver = self.database_wh_driver
            user = self.database_wh_user or ""
            password = self.database_wh_pass or ""
            host = self.database_wh_server_v2
            port = self.database_wh_port_v2 or ""
            db = self.database_wh_db_v2 or ""
            params = self.database_wh_params_v2 or ""

            # Build auth part
            auth = f"{user}:{password}@" if password else (f"{user}@" if user else "")

            # Build host:port
            host_port = f"{host}:{port}" if port else host

            # Build URL
            self.database_url = f"{driver}://{auth}{host_port}/{db}{params}"

        return self

    # ==========================================================================
    # Legacy settings (deprecated, for backward compatibility)
    # ==========================================================================

    # Provider configuration (deprecated - use connection_name)
    provider_id: str = Field(
        default="default",
        description="[DEPRECATED] Use connection_name instead",
    )

    # Resource paths
    resources_dir: str = Field(
        default="packages/resources/dbmeta_app",
        description="Path to bundled resources directory",
    )

    # Providers directory (deprecated - use connection_path or connections_dir)
    providers_dir: str = Field(
        default="",
        description="[DEPRECATED] Use connection_path instead",
    )

    # OpenAI for embeddings (optional, for query examples)
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for embeddings",
    )

    # Observability
    logfire_token: str = Field(
        default="",
        description="Pydantic Logfire token for observability (optional)",
    )

    # Auth0 OAuth configuration (uses OIDC Proxy for full OAuth 2.1 flow)
    auth0_enabled: bool = Field(
        default=False,
        description="Enable Auth0 OAuth for MCP requests",
    )
    auth0_domain: str = Field(
        default="",
        description="Auth0 domain (e.g., 'your-tenant.auth0.com')",
    )
    auth0_client_id: str = Field(
        default="",
        description="Auth0 application client ID",
    )
    auth0_client_secret: str = Field(
        default="",
        description="Auth0 application client secret",
    )
    auth0_audience: str = Field(
        default="",
        description="Auth0 API audience/identifier",
    )
    auth0_base_url: str = Field(
        default="",
        description="Public URL of this MCP server (for OAuth callbacks)",
    )

    # MCP server configuration
    tool_mode: Literal["detailed", "shell"] = Field(
        default="detailed",
        description=(
            "Tool exposure mode: "
            "'detailed' exposes all tools (schema discovery, query helpers, etc.), "
            "'shell' exposes only the shell tool for query work (agent uses vault filesystem)"
        ),
    )
    mcp_transport: str = Field(
        default="stdio",
        description="MCP transport: 'stdio' for local, 'http' for remote",
    )
    mcp_host: str = Field(
        default="0.0.0.0",
        description="Host to bind MCP HTTP server",
    )
    mcp_port: int = Field(
        default=8000,
        description="Port for MCP HTTP server",
    )
    mcp_path: str = Field(
        default="/mcp",
        description="Path for MCP HTTP endpoint",
    )

    # ==========================================================================
    # Storage backend configuration
    # ==========================================================================

    vault_backend: Literal["local", "s3"] = Field(
        default="local",
        description="Storage backend: 'local' for filesystem, 's3' for AWS S3",
    )

    # Legacy vault_path (deprecated - use connection_path)
    vault_path: str = Field(
        default="",
        description="[DEPRECATED] Use connection_path instead",
    )

    # S3 configuration (applies to connection data when vault_backend='s3')
    vault_s3_bucket: str = Field(
        default="",
        description="S3 bucket name for storage (only used if vault_backend='s3')",
    )
    vault_s3_prefix: str = Field(
        default="connections/",
        description="S3 key prefix for connection files",
    )
    vault_s3_region: str = Field(
        default="us-east-1",
        description="AWS region for S3 bucket",
    )
    vault_sync_on_startup: bool = Field(
        default=True,
        description="Sync from S3 on startup (only if vault_backend='s3')",
    )
    vault_sync_interval_seconds: int = Field(
        default=300,
        description="Interval for background sync in seconds (0 to disable)",
    )

    # Migration settings
    auto_migrate: bool = Field(
        default=True,
        description="Auto-migrate from legacy v1 structure on startup",
    )

    def get_effective_connection_path(self) -> Path:
        """Get the effective connection path based on configuration.

        Priority:
        1. connection_path (explicit, for server deployments)
        2. connections_dir + connection_name (for local CLI)
        3. Legacy: vault_path parent / "connection" (migration)
        4. Default: ~/.dbmeta/connections/{connection_name}

        Returns:
            Path to the connection directory
        """
        # 1. Explicit connection_path (server mode)
        if self.connection_path:
            return Path(self.connection_path)

        # 2. connections_dir + connection_name (local CLI)
        if self.connections_dir:
            return Path(self.connections_dir) / self.connection_name

        # 3. Legacy vault_path - derive connection path
        if self.vault_path:
            # vault_path=/data/vault -> connection=/data/connection
            return Path(self.vault_path).parent / "connection"

        # 4. Default: ~/.dbmeta/connections/{name}
        return Path.home() / ".dbmeta" / "connections" / self.connection_name

    def get_effective_provider_id(self) -> str:
        """Get effective provider/connection identifier.

        Returns connection_name, falling back to provider_id for legacy compat.
        """
        return self.connection_name or self.provider_id or "default"


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset cached settings (useful for testing)."""
    global _settings
    _settings = None
