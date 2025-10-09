import json
import pathlib
import typing

import numpy as np
import openai
import pymilvus
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    SearchResult,
    connections,
    utility,
)

from dbmeta_app.config import get_settings
from dbmeta_app.prompt_assembler.prompt_packs import assemble_effective_tree, load_yaml
from dbmeta_app.vector_db.milvus import QueryExample

# print(os.getenv("VECTOR_DB_EMBEDDINGS"))


settings = get_settings()
# print(settings.vector_db_embeddings)


collection_name = settings.vector_db_collection_name


def get_embeddings(
    texts: list[str], model: str = settings.vector_db_embeddings
) -> list[list[float]]:
    response = openai.embeddings.create(input=texts, model=model)
    # Order is preserved in OpenAI responses
    return [r.embedding for r in response.data]


def normalize_vector(vector):
    norm = np.linalg.norm(vector)
    return vector / (norm if norm > 0 else vector)  # Avoid division by zero


def load_query_examples():
    settings = get_settings()
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    client = settings.client
    env = settings.env
    profile = settings.default_profile
    tree = assemble_effective_tree(repo_root, profile, client, env)

    file = load_yaml(tree, "resources/query_examples.yaml")
    data = file["profiles"][profile]["examples"]
    examples = []
    print(f"loaded {len(data)} examples")
    for row in data:
        request = row.get("request", "").strip()
        response = row.get("response", "").strip()
        db = row.get("db", "").strip()
        # print(f"loading: {request} -> {response} ({db})")
        examples.append((request, response, db))

    # Generate embeddings
    example_texts = [
        f"User request: {request}, SQL response {response}"
        for request, response, db in examples
    ]
    token_embeddings = get_embeddings(example_texts)

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

    # Define schema
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(
            name="embedding", dtype=DataType.FLOAT_VECTOR, dim=len(token_embeddings[0])
        ),
        FieldSchema(name="request", dtype=DataType.VARCHAR, max_length=1000),
        FieldSchema(name="response", dtype=DataType.VARCHAR, max_length=5000),
        FieldSchema(name="db", dtype=DataType.VARCHAR, max_length=20),
    ]
    schema = CollectionSchema(fields, description="Query examples")

    # Create or load collection
    collection_name = settings.vector_db_collection_name
    index_params = {
        "metric_type": settings.vector_db_metric_type,
        # Use Inner Product for Cosine Similarity
        "index_type": settings.vector_db_index_type,
        # Choose IVF_FLAT, IVF_PQ, or HNSW as needed
        "params": json.loads(settings.vector_db_params),
        # Adjust based on dataset size
    }
    names: list[str] = pymilvus.utility.list_collections()
    if collection_name in names:
        utility.drop_collection(collection_name)
    collection = Collection(name=collection_name, schema=schema)
    collection.create_index("embedding", index_params)

    # Insert data into Milvus

    entities = [
        {
            "embedding": normalize_vector(np.array(token_embeddings[i])),
            # "embedding": normalized_vector,
            "request": examples[i][0],
            "response": examples[i][1],
            "db": examples[i][2],
        }
        for i in range(len(examples))
    ]

    collection.insert(entities)
    collection.flush()
    print("Inserted embeddings into Milvus")


def get_hits(query: str, db: str, top_k=3):
    print(f"Searching for: {query} in {collection_name} of {db}")
    query_embedding = get_embeddings([query])
    # if utility.load_state(collection_name) != LoadState.Loaded:
    #    collection.load()  # Ensure collection is loaded before querying

    search_params = {
        "metric_type": settings.vector_db_metric_type,
        "params": json.loads(settings.vector_db_params),
    }

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(
            name="embedding",
            dtype=DataType.FLOAT_VECTOR,
            dim=len(get_embeddings([query])[0]),
        ),
        FieldSchema(name="request", dtype=DataType.VARCHAR, max_length=1000),
        FieldSchema(name="response", dtype=DataType.VARCHAR, max_length=5000),
        FieldSchema(name="db", dtype=DataType.VARCHAR, max_length=20),
    ]
    schema = CollectionSchema(fields, description="Query examples")
    collection = Collection(name=collection_name, schema=schema)

    results: SearchResult = typing.cast(SearchResult, collection.search(
        # data=[query_embedding.tolist()],  # Query vector
        data=[normalize_vector(np.array(query_embedding[0]))],  # Query vector
        anns_field="embedding",
        param=search_params,
        limit=top_k,
        output_fields=["request", "response"],
        expr=f'db == "{db}"',
    ))

    output = []
    if results:
        for i, hit in enumerate(results[0]):
            request = hit.entity.get("request")
            response = hit.entity.get("response")
            # print(f"   : {request} - {response} - {1 / (1 + hit.score):.2f}")
            output.append(
                QueryExample(request=request, response=response, score=1 / (1 + hit.score))
            )

    # Combine all examples into a single LLM input string

    return output


def test_vector_db():
    print("\n\nTesting vector DB\n\n")
    print(f"Index type: {settings.vector_db_index_type}")

    question = "What wallet held the most MOBILE tokens on February 12th, 2025."
    hits = get_hits(query=question, db="wh")
    print(f"{question}\n{hits}")

    # question = "Get the name of mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So address"
    # hits = get_hits(query=question, db="wh")
    # print(f"{question} => {hits}")


def main():
    print(
        f"""
        loading data from {settings.etl_file_name}
        to Milvus {settings.vector_db_collection_name}
        ({settings.vector_db_host}:{settings.vector_db_port})
        """
    )
    load_query_examples()
    # test_vector_db()


if __name__ == "__main__":
    main()
