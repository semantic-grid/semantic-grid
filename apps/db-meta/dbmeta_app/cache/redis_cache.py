"""
Redis cache layer for db-meta MCP server.

Provides cross-worker caching for expensive operations like:
- Schema introspection (get_db_schema)
- Query examples (get_query_examples)
- EXPLAIN analysis (query_preflight)
"""

import hashlib
import json
import logging
from typing import Any, Optional

import redis

from dbmeta_app.config import get_settings

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Redis cache client with connection pooling and error handling.

    Features:
    - Automatic JSON serialization/deserialization
    - Configurable TTL per cache key type
    - Graceful fallback on Redis errors (never breaks the app)
    - Hash-based cache keys for consistent lookups
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: int = 0,
        password: Optional[str] = None,
        enabled: bool = True,
    ):
        """
        Initialize Redis cache client.

        Args:
            host: Redis host (defaults to settings.redis_host)
            port: Redis port (defaults to settings.redis_port)
            db: Redis database number (default 0)
            password: Redis password (optional)
            enabled: Whether caching is enabled (defaults to settings.redis_cache_enabled)
        """
        settings = get_settings()

        self.enabled = (
            enabled
            if enabled is not None
            else getattr(settings, "redis_cache_enabled", True)
        )
        self.host = host or getattr(settings, "redis_host", "localhost")
        self.port = port or getattr(settings, "redis_port", 6379)
        self.db = db
        self.password = password or getattr(settings, "redis_password", None)

        self._client: Optional[redis.Redis] = None

        if self.enabled:
            try:
                self._client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    decode_responses=True,  # Auto-decode bytes to str
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    retry_on_timeout=True,
                    health_check_interval=30,
                )
                # Test connection
                self._client.ping()
                logger.info(f"Redis cache connected: {self.host}:{self.port}/{self.db}")
            except Exception as e:
                logger.warning(f"Redis cache disabled due to connection error: {e}")
                self._client = None
                self.enabled = False

    def _generate_key(self, prefix: str, *args: Any, **kwargs: Any) -> str:
        """
        Generate a consistent cache key from prefix and parameters.

        Args:
            prefix: Cache key prefix (e.g., "schema", "examples", "explain")
            *args: Positional arguments to hash
            **kwargs: Keyword arguments to hash

        Returns:
            Cache key string like "dbmeta:schema:abc123def456"
        """
        # Serialize all arguments to create a stable hash
        key_data = {
            "args": args,
            "kwargs": kwargs,
        }
        key_json = json.dumps(key_data, sort_keys=True, default=str)
        key_hash = hashlib.sha256(key_json.encode()).hexdigest()[:16]

        return f"dbmeta:{prefix}:{key_hash}"

    def get(self, prefix: str, *args: Any, **kwargs: Any) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            prefix: Cache key prefix
            *args: Arguments used to generate cache key
            **kwargs: Keyword arguments used to generate cache key

        Returns:
            Cached value (deserialized from JSON) or None if not found/error
        """
        if not self.enabled or not self._client:
            return None

        try:
            key = self._generate_key(prefix, *args, **kwargs)
            value = self._client.get(key)

            if value:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(value)
            else:
                logger.debug(f"Cache MISS: {key}")
                return None

        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None

    def set(
        self,
        prefix: str,
        value: Any,
        ttl: int = 3600,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """
        Set value in cache.

        Args:
            prefix: Cache key prefix
            value: Value to cache (will be JSON-serialized)
            ttl: Time-to-live in seconds (default 1 hour)
            *args: Arguments used to generate cache key
            **kwargs: Keyword arguments used to generate cache key

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled or not self._client:
            return False

        try:
            key = self._generate_key(prefix, *args, **kwargs)
            serialized = json.dumps(value, default=str)

            self._client.setex(key, ttl, serialized)
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.warning(f"Redis set error: {e}")
            return False

    def delete(self, prefix: str, *args: Any, **kwargs: Any) -> bool:
        """
        Delete value from cache.

        Args:
            prefix: Cache key prefix
            *args: Arguments used to generate cache key
            **kwargs: Keyword arguments used to generate cache key

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled or not self._client:
            return False

        try:
            key = self._generate_key(prefix, *args, **kwargs)
            self._client.delete(key)
            logger.debug(f"Cache DELETE: {key}")
            return True

        except Exception as e:
            logger.warning(f"Redis delete error: {e}")
            return False

    def clear_prefix(self, prefix: str) -> int:
        """
        Clear all keys with a specific prefix.

        Args:
            prefix: Cache key prefix to clear

        Returns:
            Number of keys deleted
        """
        if not self.enabled or not self._client:
            return 0

        try:
            pattern = f"dbmeta:{prefix}:*"
            keys = list(self._client.scan_iter(match=pattern, count=100))

            if keys:
                deleted = self._client.delete(*keys)
                logger.info(f"Cleared {deleted} keys with prefix: {prefix}")
                return deleted

            return 0

        except Exception as e:
            logger.warning(f"Redis clear_prefix error: {e}")
            return 0

    def health_check(self) -> bool:
        """
        Check if Redis is healthy.

        Returns:
            True if Redis is responding, False otherwise
        """
        if not self.enabled or not self._client:
            return False

        try:
            return self._client.ping()
        except Exception:
            return False


# Global cache instance (singleton)
_cache_instance: Optional[RedisCache] = None


def get_cache() -> RedisCache:
    """
    Get or create global Redis cache instance.

    Returns:
        RedisCache instance
    """
    global _cache_instance

    if _cache_instance is None:
        _cache_instance = RedisCache()

    return _cache_instance


# Cache TTL configurations (in seconds)
CACHE_TTL = {
    "schema": 3600,  # 1 hour - schema doesn't change often
    "schema_structured": 3600,  # 1 hour - structured schema cache
    "examples": 1800,  # 30 minutes - examples update periodically
    "explain": 600,  # 10 minutes - query plans can change with data
    "prompt": 3600,  # 1 hour - prompt instructions rarely change
    "table_details": 3600,  # 1 hour - table statistics don't change rapidly
    "table_relationships": 86400,  # 24 hours - PK/FK relationships very stable
}


def cache_result(prefix: str, ttl: Optional[int] = None):
    """
    Decorator to cache function results in Redis.

    Usage:
        @cache_result("schema", ttl=3600)
        def get_db_schema(profile: str):
            # expensive operation
            return schema

    Args:
        prefix: Cache key prefix
        ttl: Time-to-live in seconds (defaults to CACHE_TTL[prefix])
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            cache = get_cache()

            # Try to get from cache
            cached = cache.get(prefix, *args, **kwargs)
            if cached is not None:
                return cached

            # Execute function
            result = func(*args, **kwargs)

            # Store in cache
            cache_ttl = ttl or CACHE_TTL.get(prefix, 3600)
            cache.set(prefix, result, ttl=cache_ttl, *args, **kwargs)

            return result

        return wrapper

    return decorator
