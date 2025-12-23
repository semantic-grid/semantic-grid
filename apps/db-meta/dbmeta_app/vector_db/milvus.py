import json
import logging
from typing import Optional

import numpy as np
import openai
import pymilvus
from pydantic import BaseModel
from pymilvus import Collection, connections, utility
from pymilvus.client.types import LoadState
from rank_bm25 import BM25Okapi

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


def get_all_table_records(
    profile: str,
    client: Optional[str] = None,
    env: Optional[str] = None,
) -> list[dict]:
    """
    Get all table records from the Milvus collection (for BM25 indexing).

    Args:
        profile: Database profile (e.g., 'wh_v2')
        client: Client name (defaults to settings.client)
        env: Environment (defaults to settings.env)

    Returns:
        List of dicts with table_name, description, columns_json
    """
    client = client or settings.client
    env = env or settings.env

    collection_name = get_collection_name(client, env, profile, "tables")
    collection = ensure_collection_loaded(collection_name)

    if collection is None:
        return []

    # Query all table data (no vector search, just fetch fields)
    results = collection.query(
        expr=f'profile == "{profile}"',
        output_fields=["table_name", "description", "columns_json"],
        limit=1000,  # Should be enough for any schema
    )

    return results


# Cache for BM25 index per profile
_bm25_cache: dict[str, tuple[BM25Okapi, list[dict]]] = {}


def clear_bm25_cache() -> None:
    """Clear the BM25 cache. Call this after schema changes or tokenizer updates."""
    global _bm25_cache
    _bm25_cache = {}
    logging.info("BM25 cache cleared")


def _stem_token(token: str) -> str:
    """
    Simple stemming: remove common suffixes.

    Handles:
    - Plurals: hotspots → hotspot, entries → entry, tables → table
    - -ing: processing → process
    - -ed: aggregated → aggregat (close enough for matching)
    """
    if len(token) <= 3:
        return token

    # Handle -ies → -y (entries → entry)
    if token.endswith("ies"):
        return token[:-3] + "y"

    # Handle -es (tables → tabl, but matches "table" stemmed too)
    if token.endswith("es") and len(token) > 4:
        return token[:-2]

    # Handle -s (hotspots → hotspot)
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]

    # Handle -ing (processing → process)
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]

    # Handle -ed (aggregated → aggregat)
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]

    return token


def _tokenize_for_bm25(text: str) -> list[str]:
    """
    Tokenize text for BM25 search with simple stemming.

    Splits on dots, underscores, and spaces to handle table names like
    'iceberg.radius.wifi_qm_v2' → ['iceberg', 'radius', 'wifi', 'qm', 'v2']

    Applies simple stemming so 'hotspots' matches 'hotspot'.
    """
    tokens = text.lower().replace(".", " ").replace("_", " ").split()
    return [_stem_token(t) for t in tokens]


def _build_searchable_text(record: dict) -> str:
    """
    Build searchable text for a table record (for BM25 indexing).

    Includes table name, description, and column names/descriptions.
    """
    table_name = record.get("table_name", "")
    description = record.get("description", "") or ""
    columns_json = record.get("columns_json", "")

    # Parse columns
    try:
        columns = json.loads(columns_json) if columns_json else {}
    except json.JSONDecodeError:
        columns = {}

    # Build searchable text
    parts = [f"Table {table_name}", description]

    # Add column names and descriptions
    for col_name, col_info in columns.items():
        col_desc = col_info.get("description", "") if isinstance(col_info, dict) else ""
        parts.append(f"{col_name}: {col_desc}")

    return " ".join(parts)


def _get_bm25_index(
    profile: str,
    client: Optional[str] = None,
    env: Optional[str] = None,
) -> tuple[Optional[BM25Okapi], list[dict]]:
    """
    Get or build BM25 index for a profile.

    Returns:
        Tuple of (BM25 index, list of table records)
    """
    cache_key = f"{client}_{env}_{profile}"

    if cache_key in _bm25_cache:
        return _bm25_cache[cache_key]

    # Fetch all table records
    records = get_all_table_records(profile, client, env)

    if not records:
        return None, []

    # Build corpus for BM25
    corpus = [_tokenize_for_bm25(_build_searchable_text(r)) for r in records]

    # Create BM25 index
    bm25 = BM25Okapi(corpus)

    # Cache it
    _bm25_cache[cache_key] = (bm25, records)

    # Log all indexed tables for debugging
    table_names = [r.get("table_name", "?") for r in records]
    logging.info(
        f"Built BM25 index for {cache_key} with {len(records)} tables: {table_names}",
        extra={
            "action": "bm25_index_built",
            "profile": profile,
            "tables": len(records),
        },
    )

    return bm25, records


def _search_bm25(
    query: str,
    profile: str,
    top_k: int = 10,
    client: Optional[str] = None,
    env: Optional[str] = None,
) -> list[TableMatch]:
    """
    BM25 keyword search for tables.

    Args:
        query: User's natural language query
        profile: Database profile
        top_k: Number of results to return
        client: Client name
        env: Environment

    Returns:
        List of TableMatch objects sorted by BM25 score
    """
    client = client or settings.client
    env = env or settings.env

    bm25, records = _get_bm25_index(profile, client, env)

    if bm25 is None or not records:
        return []

    # Tokenize query
    query_tokens = _tokenize_for_bm25(query)

    # Get BM25 scores
    scores = bm25.get_scores(query_tokens)

    # Get top_k indices sorted by score
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :top_k
    ]

    # Build results
    results = []
    max_score = max(scores) if max(scores) > 0 else 1.0

    for idx in top_indices:
        if scores[idx] > 0:  # Only include matches with positive score
            record = records[idx]
            columns_json = record.get("columns_json", "")
            try:
                columns = json.loads(columns_json) if columns_json else {}
            except json.JSONDecodeError:
                columns = {}

            results.append(
                TableMatch(
                    table_name=record.get("table_name", ""),
                    description=record.get("description", "") or "",
                    columns=columns,
                    score=scores[idx] / max_score,  # Normalize to 0-1
                )
            )

    return results


def _search_relevant_tables_vector(
    query: str,
    profile: str,
    top_k: int = 5,
    client: Optional[str] = None,
    env: Optional[str] = None,
) -> list[TableMatch]:
    """
    Vector-only search for tables (internal function).

    Args:
        query: User's natural language query
        profile: Database profile (e.g., 'wh_v2')
        top_k: Number of most relevant tables to return
        client: Client name (defaults to settings.client)
        env: Environment (defaults to settings.env)

    Returns:
        List of TableMatch objects with table names, descriptions, columns, scores
    """
    client = client or settings.client
    env = env or settings.env

    collection_name = get_collection_name(client, env, profile, "tables")
    collection = ensure_collection_loaded(collection_name)

    if collection is None:
        return []

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


def search_relevant_tables(
    query: str,
    profile: str,
    top_k: int = 5,
    client: Optional[str] = None,
    env: Optional[str] = None,
) -> list[TableMatch]:
    """
    Hybrid search for tables relevant to a user's natural language query.

    Combines BM25 keyword search (for explicit terms like table names, column names)
    with semantic vector search (for conceptual/meaning-based queries).

    Algorithm:
    1. Run BM25 search on table names + descriptions + column info
    2. Run semantic vector search
    3. Combine scores: (bm25_weight * bm25_score) + (vector_weight * vector_score)
    4. Return top_k by combined score

    Args:
        query: User's natural language query
        profile: Database profile (e.g., 'wh_v2')
        top_k: Number of most relevant tables to return
        client: Client name (defaults to settings.client)
        env: Environment (defaults to settings.env)

    Returns:
        List of TableMatch objects with table names, descriptions, columns, scores
    """
    client = client or settings.client
    env = env or settings.env

    # Check if hybrid search is enabled (default: True)
    hybrid_enabled = getattr(settings, "search_hybrid_enabled", True)

    if not hybrid_enabled:
        # Fall back to vector-only search
        return _search_relevant_tables_vector(
            query=query, profile=profile, top_k=top_k, client=client, env=env
        )

    # Get weights from settings
    bm25_weight = getattr(settings, "search_bm25_weight", 0.3)
    vector_weight = getattr(settings, "search_vector_weight", 0.7)

    # Step 1: BM25 search (keyword matching on full searchable text)
    bm25_results = _search_bm25(
        query=query, profile=profile, top_k=top_k * 2, client=client, env=env
    )
    bm25_scores = {m.table_name: m.score for m in bm25_results}

    # Step 2: Vector search (semantic similarity)
    vector_results = _search_relevant_tables_vector(
        query=query, profile=profile, top_k=top_k * 2, client=client, env=env
    )
    vector_scores = {m.table_name: m.score for m in vector_results}

    # Step 3: Combine scores
    # Collect all tables from both searches
    all_tables = set(bm25_scores.keys()) | set(vector_scores.keys())

    # Build metadata lookup from both result sets
    metadata_lookup: dict[str, TableMatch] = {}
    for m in bm25_results + vector_results:
        if m.table_name not in metadata_lookup:
            metadata_lookup[m.table_name] = m

    # Calculate combined scores
    combined_results: list[TableMatch] = []
    for table_name in all_tables:
        bm25_s = bm25_scores.get(table_name, 0.0)
        vector_s = vector_scores.get(table_name, 0.0)
        combined_score = (bm25_weight * bm25_s) + (vector_weight * vector_s)

        # Get metadata
        meta = metadata_lookup.get(table_name)
        combined_results.append(
            TableMatch(
                table_name=table_name,
                description=meta.description if meta else "",
                columns=meta.columns if meta else {},
                score=combined_score,
            )
        )

    # Step 4: Sort by combined score and return top_k
    combined_results.sort(key=lambda m: m.score, reverse=True)

    # Log detailed scores for debugging
    logging.info(
        f"Hybrid search for '{query[:50]}': "
        f"BM25 found {len(bm25_results)}, Vector found {len(vector_results)}, "
        f"Combined {len(combined_results)} tables",
        extra={
            "action": "hybrid_search",
            "query": query[:100],
            "bm25_count": len(bm25_results),
            "vector_count": len(vector_results),
        },
    )

    # Log top 15 results with component scores for debugging
    for i, m in enumerate(combined_results[:15]):
        bm25_s = bm25_scores.get(m.table_name, 0.0)
        vector_s = vector_scores.get(m.table_name, 0.0)
        logging.info(
            f"  #{i + 1} {m.table_name}: combined={m.score:.3f} "
            f"(bm25={bm25_s:.3f}, vector={vector_s:.3f})"
        )

    return combined_results[:top_k]
