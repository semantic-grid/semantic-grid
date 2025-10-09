import json
import os
import typing

import numpy as np
import openai
import pymilvus
from pydantic import BaseModel
from pymilvus import Collection, SearchResult, connections, utility
from pymilvus.client.types import LoadState

from dbmeta_app.config import get_settings


class QueryExample(BaseModel):
    request: str
    response: str
    score: float


settings = get_settings()
collection_name = settings.vector_db_collection_name


def get_embedding(text: str, model: str = settings.vector_db_embeddings) -> list[float]:
    response = openai.embeddings.create(input=[text], model=model)
    return response.data[0].embedding


def init() -> Collection:
    # Connect to Milvus
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
        # connections.connect(alias="default", uri="sqlite:///:memory:")
        # Uses in-memory SQLite for testing
    else:
        print(
            "No Milvus connection information found. Please set it in the environment."
        )
        exit(1)

    if collection_name not in pymilvus.utility.list_collections():
        pymilvus.utility.has_collection

    if collection_name not in pymilvus.utility.list_collections():
        print(f"Collection {collection_name} not found.")
        exit(1)
    else:
        collection = Collection(collection_name)
        collection.load()

    utility.wait_for_loading_complete(collection_name)
    assert utility.load_state(collection_name) == LoadState.Loaded
    print(f"Collection {collection_name} loaded")

    return collection


collection = init()


def normalize_vector(vector):
    norm = np.linalg.norm(vector)
    return vector / (norm if norm > 0 else vector)  # Avoid division by zero


def get_hits(query: str, db: str, top_k=3) -> list[QueryExample]:
    print(f"Searching for: {query} in {collection_name} of {db}")
    query_embedding = get_embedding(query)
    if utility.load_state(collection_name) != LoadState.Loaded:
        collection.load()  # Ensure collection is loaded before querying

    search_params = {
        "metric_type": settings.vector_db_metric_type,
        "params": json.loads(settings.vector_db_params),
    }
    results: SearchResult = typing.cast(
        SearchResult,
        collection.search(
            # data=[query_embedding.tolist()],  # Query vector
            data=[normalize_vector(np.array(query_embedding))],  # Query vector
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            output_fields=["request", "response"],
            expr=f'db == "{db}"',
        ),
    )

    output = []
    if results:
        for i, hit in enumerate(results[0]):
            request = hit.entity.get("request")
            response = hit.entity.get("response")
            # print(f"   : {request} - {response} - {1 / (1 + hit.score):.2f}")
            output.append(
                QueryExample(
                    request=request, response=response, score=1 / (1 + hit.score)
                )
            )
    # Combine all examples into a single LLM input string

    return output
