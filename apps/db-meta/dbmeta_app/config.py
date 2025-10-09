from functools import lru_cache
import json
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import field_validator

load_dotenv()


class Settings(BaseSettings):
    port: int = 8080
    log_level: str = "INFO"
    database_wh_user: str = ""
    database_wh_pass: str = ""
    database_wh_port: int = 0
    database_wh_server: str = ""
    database_wh_params: str = ""
    database_wh_db: str = "wh"
    database_wh_driver: str = "clickhouse+native"
    vector_db_host: Optional[str] = None
    vector_db_port: Optional[str] = None
    vector_db_connection_string: Optional[str] = None
    vector_db_collection_name: str = "apegpt_prompts"
    vector_db_embeddings: str = "all-MiniLM-L6-v2"
    vector_db_metric_type: Optional[str] = "L2"
    vector_db_index_type: Optional[str] = "HNSW"
    vector_db_params: str = '{"nprobe": 15}'
    etl_file_name: Optional[str] = None
    schema_descriptions_file: Optional[str] = None
    query_examples_file: Optional[str] = None
    prompt_instructions_file: Optional[str] = None
    data_examples: bool = False
    openai_api_key: Optional[str] = None
    client: Optional[str] = "apegpt"
    env: Optional[str] = "prod"
    default_profile: str = "wh"
    packs_resources_dir: str = "/app/packages"

    @field_validator(
        "database_wh_user",
        "database_wh_pass",
        "database_wh_server",
        "database_wh_db",
        "default_profile",
        "vector_db_embeddings",
        "vector_db_collection_name",
        "database_wh_driver",
        mode="after",
    )
    @classmethod
    def validator_string_not_empty(cls, value: str) -> str:
        if value == "":
            raise ValueError("empty string")
        return value

    @field_validator(
        "vector_db_params",
        mode="after",
    )
    @classmethod
    def validator_json(cls, value: str) -> str:
        try:
            json.loads(value)
        except json.JSONDecodeError as ex:
            raise ValueError(f"invalid json {ex}")
        return value

    @field_validator("port", "database_wh_port", mode="after")
    @classmethod
    def validator_port(cls, value: int) -> int:
        if 1 <= value <= 65535:
            return value
        raise ValueError("invalid port")


@lru_cache()
def get_settings():
    return Settings()
