from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    port: int = 8080
    log_level: str = "INFO"
    database_wh_user: Optional[str] = None
    database_wh_pass: Optional[str] = None
    database_wh_port: Optional[str] = None
    database_wh_port_new: Optional[str] = None
    database_wh_port_v2: Optional[str] = None
    database_wh_server: Optional[str] = None
    database_wh_server_new: Optional[str] = None
    database_wh_server_v2: Optional[str] = None
    database_wh_params: Optional[str] = ""
    database_wh_params_new: Optional[str] = ""
    database_wh_params_v2: Optional[str] = ""
    database_wh_db: Optional[str] = "wh"
    database_wh_db_new: Optional[str] = "wh_new"
    database_wh_db_v2: Optional[str] = "wh"
    vector_db_host: Optional[str] = None
    vector_db_port: Optional[str] = None
    vector_db_timeout: Optional[float] = 10
    vector_db_connection_string: Optional[str] = None
    vector_db_collection_name: Optional[str] = "apegpt_prompts"
    vector_db_embeddings: Optional[str] = "all-MiniLM-L6-v2"
    vector_db_metric_type: Optional[str] = "L2"
    vector_db_index_type: Optional[str] = "HNSW"
    vector_db_params: Optional[str] = '{"nprobe": 15}'
    etl_file_name: Optional[str] = None
    schema_descriptions_file: Optional[str] = None
    query_examples_file: Optional[str] = None
    prompt_instructions_file: Optional[str] = None
    data_examples: bool = False
    openai_api_key: Optional[str] = None
    client: Optional[str] = "apegpt"
    env: Optional[str] = "prod"
    default_profile: Optional[str] = "wh_v2"
    packs_resources_dir: str = "/app/packages"


@lru_cache()
def get_settings():
    return Settings()
