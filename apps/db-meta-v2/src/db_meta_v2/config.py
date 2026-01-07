"""Configuration for db-meta-v2."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database connection
    database_url: str = Field(
        default="",
        description="Database connection URL (e.g., trino://user:pass@host:port/catalog/schema)",
    )

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
