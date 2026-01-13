"""Configuration for db-meta-v2."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database connection - either full URL or components
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

    # Provider configuration
    provider_id: str = Field(
        default="default",
        description="Provider identifier for multi-tenant support",
    )

    # Resource paths
    resources_dir: str = Field(
        default="packages/resources/dbmeta_app",
        description="Path to resources directory",
    )

    providers_dir: str = Field(
        default="packages/resources/dbmeta_app/providers",
        description="Path to providers directory for artifact storage",
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

    # Knowledge Vault configuration
    vault_backend: Literal["local", "s3"] = Field(
        default="local",
        description="Vault storage backend: 'local' for filesystem, 's3' for AWS S3",
    )
    vault_path: str = Field(
        default="/data/vault",
        description="Local path for vault storage (also used as cache for S3 backend)",
    )
    vault_s3_bucket: str = Field(
        default="",
        description="S3 bucket name for vault storage (only used if vault_backend='s3')",
    )
    vault_s3_prefix: str = Field(
        default="knowledge/",
        description="S3 key prefix for vault files",
    )
    vault_s3_region: str = Field(
        default="us-east-1",
        description="AWS region for S3 bucket",
    )
    vault_sync_on_startup: bool = Field(
        default=True,
        description="Sync vault from S3 on startup (only if vault_backend='s3')",
    )
    vault_sync_interval_seconds: int = Field(
        default=300,
        description="Interval for background vault sync in seconds (0 to disable)",
    )
    vault_migrate_legacy: bool = Field(
        default=True,
        description="Auto-migrate data from legacy providers/{id}/ structure on startup",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
