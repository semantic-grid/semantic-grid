# settings.py (your parent file)
from functools import lru_cache
from typing import Optional

from dotenv import find_dotenv, load_dotenv
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
    database_wh_user: str
    database_wh_pass: str
    database_wh_driver: Optional[str] = "clickhouse+native"
    database_wh_port: int
    database_wh_port_new: int
    database_wh_port_v2: int
    database_wh_server: str
    database_wh_server_new: str
    database_wh_server_v2: str
    database_wh_params: str
    database_wh_params_new: str
    database_wh_params_v2: str
    database_wh_db: str
    database_wh_db_new: str
    database_wh_db_v2: str
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


@lru_cache()
def get_settings() -> Settings:
    return Settings()
