"""Query result caching helpers."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fm_app.cache.redis_client import get_redis
from fm_app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def build_cache_key(
    query_id: str,
    limit: int,
    offset: int,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> str:
    """Build cache key for query results."""
    parts = [f"query_data:{query_id}", f"limit:{limit}", f"offset:{offset}"]

    if sort_by:
        parts.append(f"sort_by:{sort_by}")
    if sort_order:
        parts.append(f"sort_order:{sort_order}")

    return ":".join(parts)


async def get_cached_query(
    query_id: str,
    limit: int,
    offset: int,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Get cached query results from Redis."""
    if not settings.cache_enabled:
        return None

    try:
        redis = await get_redis()
        cache_key = build_cache_key(query_id, limit, offset, sort_by, sort_order)

        cached_data = await redis.get(cache_key)
        if cached_data:
            logger.info(f"Cache HIT: {cache_key}")
            return json.loads(cached_data)

        logger.info(f"Cache MISS: {cache_key}")
        return None
    except Exception as e:
        logger.error(f"Error getting cached query: {e}")
        return None


async def set_cached_query(
    query_id: str,
    limit: int,
    offset: int,
    rows: list,
    total_rows: int,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> bool:
    """Cache query results in Redis."""
    if not settings.cache_enabled:
        return False

    try:
        redis = await get_redis()
        cache_key = build_cache_key(query_id, limit, offset, sort_by, sort_order)

        cache_data = {
            "rows": rows,
            "total_rows": total_rows,
            "cached_at": datetime.utcnow().isoformat(),
            "query_id": query_id,
        }

        await redis.setex(
            cache_key,
            settings.cache_ttl_seconds,
            json.dumps(cache_data),
        )

        logger.info(
            f"Cached query results: {cache_key} "
            f"(rows: {len(rows)}, ttl: {settings.cache_ttl_seconds}s)"
        )
        return True
    except Exception as e:
        logger.error(f"Error caching query results: {e}")
        return False


async def invalidate_query_cache(query_id: str) -> int:
    """Invalidate all cache entries for a query."""
    try:
        redis = await get_redis()
        pattern = f"query_data:{query_id}:*"

        keys = []
        async for key in redis.scan_iter(match=pattern):
            keys.append(key)

        if keys:
            deleted = await redis.delete(*keys)
            logger.info(f"Invalidated {deleted} cache entries for query {query_id}")
            return deleted

        return 0
    except Exception as e:
        logger.error(f"Error invalidating query cache: {e}")
        return 0
