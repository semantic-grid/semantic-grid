"""Track running query tasks in Redis."""

import json
import logging
from typing import Optional

from fm_app.cache.query_cache import run_async
from fm_app.cache.redis_client import get_redis
from fm_app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def set_running_task(
    query_id: str,
    task_id: str,
    notify_on_complete: bool = False,
    user_email: Optional[str] = None,
) -> bool:
    """
    Store running task info in Redis.

    Args:
        query_id: Query ID
        task_id: Celery task ID
        notify_on_complete: Whether notification was requested
        user_email: User email for notification

    Returns:
        True if stored successfully
    """
    try:
        redis = await get_redis()
        key = f"running_task:{query_id}"

        task_info = {
            "task_id": task_id,
            "notify_on_complete": notify_on_complete,
            "user_email": user_email,
        }

        # Store with 30 minute TTL (longer than query timeout)
        await redis.setex(key, 1800, json.dumps(task_info))
        logger.debug(f"Stored running task {task_id} for query {query_id}")
        return True
    except Exception as e:
        logger.warning(f"Failed to store running task: {e}")
        return False


async def get_running_task(query_id: str) -> Optional[dict]:
    """
    Get running task info from Redis.

    Args:
        query_id: Query ID

    Returns:
        Task info dict or None if no running task
    """
    try:
        redis = await get_redis()
        key = f"running_task:{query_id}"

        task_data = await redis.get(key)
        if task_data:
            task_info = json.loads(task_data)
            logger.info(
                f"Found running task {task_info['task_id']} for query {query_id}"
            )
            return task_info

        return None
    except Exception as e:
        logger.warning(f"Failed to get running task: {e}")
        return None


async def clear_running_task(query_id: str) -> bool:
    """
    Clear running task info from Redis.

    Args:
        query_id: Query ID

    Returns:
        True if cleared successfully
    """
    try:
        redis = await get_redis()
        key = f"running_task:{query_id}"
        await redis.delete(key)
        logger.debug(f"Cleared running task for query {query_id}")
        return True
    except Exception as e:
        logger.warning(f"Failed to clear running task: {e}")
        return False


async def set_timeout_notified(query_id: str) -> bool:
    """
    Mark that a timeout notification has been sent for this query.
    Uses Redis NX flag to ensure only one notification is sent.

    Args:
        query_id: Query ID

    Returns:
        True if this is the first timeout notification (should send),
        False if already sent (should skip)
    """
    try:
        redis = await get_redis()
        key = f"timeout_notified:{query_id}"
        # Try to set the key only if it doesn't exist (NX flag)
        # TTL of 1 hour to auto-cleanup
        result = await redis.set(key, "1", ex=3600, nx=True)
        return (
            result is not None
        )  # True if key was set (first time), False if already exists
    except Exception as e:
        logger.warning(f"Failed to check timeout notification status: {e}")
        return True  # On error, allow notification to be sent
