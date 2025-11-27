"""Redis client singleton for caching."""

import logging
from typing import Optional

import redis.asyncio as aioredis

from fm_app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RedisClient:
    """Async Redis client singleton."""

    _instance: Optional[aioredis.Redis] = None

    @classmethod
    async def get_client(cls) -> aioredis.Redis:
        """Get or create Redis client instance."""
        if cls._instance is None:
            try:
                cls._instance = await aioredis.from_url(
                    f"redis://{settings.redis_host}:{settings.redis_port}",
                    password=settings.redis_password or None,
                    db=settings.redis_db,
                    encoding="utf-8",
                    decode_responses=True,
                )
                # Test connection
                await cls._instance.ping()
                logger.info(
                    f"Redis client connected: "
                    f"{settings.redis_host}:{settings.redis_port}"
                )
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise

        return cls._instance

    @classmethod
    async def close(cls):
        """Close Redis connection."""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None
            logger.info("Redis client closed")


async def get_redis() -> aioredis.Redis:
    """Convenience function to get Redis client."""
    return await RedisClient.get_client()
