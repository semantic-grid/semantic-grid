import logging

from dbmeta_app.api.model import PromptItem, PromptItemType
from dbmeta_app.cache import CACHE_TTL, get_cache
from dbmeta_app.vector_db.milvus import QueryExample, get_hits


def get_query_example_prompt_item(query: str, db: str) -> PromptItem:
    # Try to get from cache first
    cache = get_cache()
    cached_result = cache.get("examples", query, db)
    if cached_result is not None:
        logging.info(f"Query examples cache HIT for db={db}")
        return PromptItem(**cached_result)

    logging.info(f"Query examples cache MISS for db={db}")

    data = get_hits(query, db)

    # Format into a human-readable LLM prompt
    formatted_examples = []

    for i, example in enumerate(data):
        request = example.request.strip()
        response = example.response.strip()

        # Format the example for LLM input
        formatted_example = (
            f"### Example #{i + 1}:\n"
            f"**User Request:** {request}\n\n"
            f"**Generated SQL:**\n```\n{response}\n```"
        )

        formatted_examples.append(formatted_example)

    # Combine all examples into a single LLM input string
    llm_prompt = "\n\n".join(formatted_examples)

    # Compute hash and metadata for lineage tracking
    from dbmeta_app.prompt_items.utils import compute_content_hash

    content_hash = compute_content_hash(llm_prompt)
    metadata = {
        "profile": db,
        "examples_count": len(data),
        "query_hash": compute_content_hash(query),
    }

    result = PromptItem(
        text=llm_prompt,
        prompt_item_type=PromptItemType.query_example,
        score=100_000,
        content_hash=content_hash,
        metadata=metadata,
    )

    # Cache the result
    cache.set("examples", result.model_dump(), CACHE_TTL["examples"], query, db)
    logging.info(f"Query examples cached for db={db}")

    return result


def get_query_examples(query: str, db: str) -> list[QueryExample]:
    res = get_hits(query, db)
    return res
