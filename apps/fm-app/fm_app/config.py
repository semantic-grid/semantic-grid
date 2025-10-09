# settings.py (your parent file)
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv, find_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 1) Load .env from the project root (or nearest up the tree)
#    Works no matter where code is called from.
load_dotenv(find_dotenv(usecwd=True), override=False)


class Settings(BaseSettings):
    # 2) Make env lookup case-insensitive, so DATABASE_USER matches database_user
    model_config = SettingsConfigDict(
        case_sensitive=False,  # DATABASE_USER == database_user
        env_file=find_dotenv(
            usecwd=True
        ),  # optional: also let pydantic read the .env directly
        env_file_encoding="utf-8",
        extra="ignore",  # <- accept unknown env key
    )

    database_user: str
    database_pass: str
    database_port: int
    database_server: str
    database_db: str
    database_wh_user: str = ""
    database_wh_pass: str = ""
    database_wh_port: int = 0
    database_wh_server: str = ""
    database_wh_params: str = ""
    database_wh_db: str = "wh"
    database_wh_driver: str = "clickhouse+native"
    auth0_domain: str
    auth0_api_audience: str
    auth0_issuer: str
    auth0_algorithms: str
    log_level: str = "INFO"
    wrk_broker_connection: str = "pyamqp://guest@localhost//"
    dbmeta: str
    dbref: str
    irl_slots: str
    google_project_id: str
    google_cred_file: str
    google_llm_name: str = "gemini-1.5-pro-001"
    anthropic_api_key: str
    anthropic_llm_name: str = "claude-3-5-sonnet-20240620"
    openai_api_key: str
    openai_llm_name: str = "gpt-4o"
    deepseek_ai_api_url: str
    deepseek_ai_api_key: str
    deepseek_llm_name: str = "deepseek-chat"
    json_log: bool = True
    max_steps: int = 5
    guest_auth_host: str
    guest_auth_issuer: str
    client_id: str = "apegpt"
    env: str = "prod"
    system_version: str = "v1.0.0"
    packs_resources_dir: str = "/app/packages"

    @field_validator(
        "database_wh_user",
        "database_wh_pass",
        "database_wh_server",
        "database_wh_db",
        "database_wh_driver",
        mode="after",
    )
    @classmethod
    def validator_string_not_empty(cls, value: str) -> str:
        if value == "":
            raise ValueError("empty string")
        return value

    @field_validator("database_wh_port", mode="after")
    @classmethod
    def validator_port(cls, value: int) -> int:
        if 1 <= value <= 65535:
            return value
        raise ValueError("invalid port")

@lru_cache()
def get_settings() -> Settings:
    return Settings()
