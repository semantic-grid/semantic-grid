"""Configuration for db-meta-v2."""

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

    # MCP server configuration
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


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
