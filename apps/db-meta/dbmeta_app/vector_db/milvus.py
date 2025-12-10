import json
from typing import Optional

import numpy as np
import openai
import pymilvus
from pydantic import BaseModel
from pymilvus import Collection, connections, utility
from pymilvus.client.types import LoadState

from dbmeta_app.config import get_settings


class QueryExample(BaseModel):
    request: str
    response: str
    score: float


class TableMatch(BaseModel):
    table_name: str
    description: str
    columns: dict  # Parsed from columns_json
    score: float


# load_dotenv()
settings = get_settings()


def get_collection_name(client: str, env: str, profile: str, suffix: str) -> str:
    """Generate collection name with pattern: {client}_{env}_{profile}_{suffix}"""
    return f"{client}_{env}_{profile}_{suffix}"


def get_embedding(text: str, model: str = settings.vector_db_embeddings) -> list[float]:
    response = openai.embeddings.create(input=[text], model=model)
    return response.data[0].embedding


# Connect to Milvus on module import
if settings.vector_db_port is not None and settings.vector_db_host is not None:
    connections.connect(
        host=settings.vector_db_host,
        port=settings.vector_db_port,
    )
elif settings.vector_db_connection_string is not None:
    connections.connect(
        alias="default",
        uri=settings.vector_db_connection_string,
    )
else:
    pass  # Connection will be attempted when functions are called


def ensure_collection_loaded(collection_name: str) -> Optional[Collection]:
    """Ensure a collection exists and is loaded"""
    if collection_name not in pymilvus.utility.list_collections():
        return None

    collection = Collection(collection_name)
    if utility.load_state(collection_name) != LoadState.Loaded:
        collection.load()
        utility.wait_for_loading_complete(collection_name)

    return collection


def normalize_vector(vector):
    norm = np.linalg.norm(vector)
    return vector / (norm if norm > 0 else vector)  # Avoid division by zero


def get_hits(
    query: str,
    db: str,
    top_k=3,
    client: Optional[str] = None,
    env: Optional[str] = None,
    profile: Optional[str] = None,
) -> list[QueryExample]:
    """Search for similar query examples in the examples collection"""
    client = client or settings.client
    env = env or settings.env
    profile = profile or settings.default_profile

    collection_name = get_collection_name(client, env, profile, "examples")
    collection = ensure_collection_loaded(collection_name)

    if collection is None:
        return []  # Collection doesn't exist yet

    query_embedding = get_embedding(query)

    search_params = {
        "metric_type": settings.vector_db_metric_type,
        "params": json.loads(settings.vector_db_params),
    }

    results = collection.search(
        data=[normalize_vector(np.array(query_embedding))],  # Query vector
        anns_field="embedding",
        param=search_params,
        limit=top_k,
        output_fields=["request", "response"],
        expr=f'db == "{db}"',
    )

    output = []
    for hit in results[0]:
        request = hit.entity.get("request")
        response = hit.entity.get("response")
        output.append(
            QueryExample(request=request, response=response, score=1 / (1 + hit.score))
        )

    return output


def search_relevant_tables(
    query: str,
    profile: str,
    top_k: int = 5,
    client: Optional[str] = None,
    env: Optional[str] = None,
) -> list[TableMatch]:
    """
    Search for tables relevant to a user's natural language query.

    Args:
        query: User's natural language query
        profile: Database profile (e.g., 'wh_v2')
        top_k: Number of most relevant tables to return
        client: Client name (defaults to settings.client)
        env: Environment (defaults to settings.env)

    Returns:
        List of TableMatch objects with table names, descriptions, columns, and relevance scores
    """
    client = client or settings.client
    env = env or settings.env

    collection_name = get_collection_name(client, env, profile, "tables")
    collection = ensure_collection_loaded(collection_name)

    if collection is None:
        return []  # Collection doesn't exist yet

    # Generate query embedding
    query_embedding = get_embedding(query)

    search_params = {
        "metric_type": settings.vector_db_metric_type,
        "params": json.loads(settings.vector_db_params),
    }

    # Search for relevant tables
    results = collection.search(
        data=[normalize_vector(np.array(query_embedding))],
        anns_field="embedding",
        param=search_params,
        limit=top_k,
        output_fields=["table_name", "description", "columns_json"],
        expr=f'profile == "{profile}"',
    )

    # Parse results
    output = []
    for hit in results[0]:
        table_name = hit.entity.get("table_name")
        description = hit.entity.get("description")
        columns_json = hit.entity.get("columns_json")

        # Parse columns JSON
        try:
            columns = json.loads(columns_json) if columns_json else {}
        except json.JSONDecodeError:
            columns = {}

        output.append(
            TableMatch(
                table_name=table_name,
                description=description,
                columns=columns,
                score=1 / (1 + hit.score),  # Convert distance to similarity score
            )
        )

    return output
