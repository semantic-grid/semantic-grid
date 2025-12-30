"""Redis client for caching.

Note: Do NOT cache Redis connections across Celery tasks - each task may run
in a different event loop, and reusing connections across loops causes errors.
"""

import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis

from fm_app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RedisClient:
    """Async Redis client with per-loop instance management.

    Each event loop gets its own Redis connection to avoid
    'Future attached to a different loop' errors in Celery.
    """

    _instances: dict[int, aioredis.Redis] = {}

    @classmethod
    def _get_loop_id(cls) -> int:
        """Get current event loop's id."""
        try:
            loop = asyncio.get_running_loop()
            return id(loop)
        except RuntimeError:
            return 0

    @classmethod
    async def get_client(cls) -> aioredis.Redis:
        """Get or create Redis client for current event loop."""
        loop_id = cls._get_loop_id()

        if loop_id not in cls._instances or cls._instances[loop_id] is None:
            try:
                # Build Redis URL with authentication if password provided
                if settings.redis_password:
                    redis_url = f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
                else:
                    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"

                client = await aioredis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                # Test connection
                await client.ping()
                cls._instances[loop_id] = client
                logger.debug(
                    f"Redis client connected for loop {loop_id}: "
                    f"{settings.redis_host}:{settings.redis_port}"
                )
            except Exception as e:
                logger.warning(f"Failed to connect to Redis (caching disabled): {e}")
                raise

        return cls._instances[loop_id]

    @classmethod
    async def close(cls):
        """Close Redis connection for current event loop."""
        loop_id = cls._get_loop_id()
        if loop_id in cls._instances and cls._instances[loop_id]:
            await cls._instances[loop_id].close()
            del cls._instances[loop_id]
            logger.info(f"Redis client closed for loop {loop_id}")


async def get_redis() -> aioredis.Redis:
    """Convenience function to get Redis client."""
    return await RedisClient.get_client()
