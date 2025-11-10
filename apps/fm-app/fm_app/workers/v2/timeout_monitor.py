"""
Timeout Monitor for V2 Messages

Background task that monitors for messages stuck in PROCESSING status
and marks them as FAILED if they've been processing for too long.

This is a safety net for scenarios where:
- Worker crashes and Celery retries fail
- Worker hangs/deadlocks
- Network partition prevents status updates

Runs every 5 minutes, marks messages as FAILED if processing >10 minutes.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import structlog

from fm_app.api.v2.model import MessageStatus
from fm_app.db.db_v2 import update_message_status
from fm_app.workers.db_session import get_db

logger = structlog.wrap_logger(logging.getLogger(__name__))


class TimeoutMonitor:
    """
    Background monitor for stuck messages.

    Usage:
        monitor = TimeoutMonitor(check_interval_seconds=300, timeout_minutes=10)
        asyncio.create_task(monitor.run())
    """

    def __init__(
        self,
        check_interval_seconds: int = 300,  # Check every 5 minutes
        timeout_minutes: int = 10,  # Mark as failed after 10 minutes
    ):
        self.check_interval = check_interval_seconds
        self.timeout_threshold = timedelta(minutes=timeout_minutes)
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def run(self):
        """
        Main loop - runs continuously until stopped.

        This should be started as a background task on application startup.
        """
        self._running = True
        logger.info(
            "Timeout monitor started",
            check_interval=self.check_interval,
            timeout_minutes=self.timeout_threshold.total_seconds() / 60,
        )

        while self._running:
            try:
                await self._check_stuck_messages()
            except Exception as e:
                logger.error(
                    "Error in timeout monitor check",
                    error=str(e),
                    exc_info=True,
                )

            # Wait before next check
            await asyncio.sleep(self.check_interval)

        logger.info("Timeout monitor stopped")

    async def stop(self):
        """Stop the monitor gracefully."""
        logger.info("Stopping timeout monitor...")
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_stuck_messages(self):
        """
        Check for messages stuck in PROCESSING and mark them as FAILED.
        """
        from sqlalchemy import text

        cutoff_time = datetime.utcnow() - self.timeout_threshold

        async for db in get_db():
            try:
                # Find messages stuck in PROCESSING using raw SQL
                query = text("""
                    SELECT id, session_id, created_at
                    FROM messages
                    WHERE status = 'processing'
                      AND created_at < :cutoff_time
                """)

                result = await db.execute(query, {"cutoff_time": cutoff_time})
                stuck_messages = result.fetchall()

                if stuck_messages:
                    logger.warning(
                        "Found stuck messages",
                        count=len(stuck_messages),
                        cutoff_time=cutoff_time.isoformat(),
                    )

                for msg in stuck_messages:
                    age_minutes = (
                        datetime.utcnow() - msg.created_at
                    ).total_seconds() / 60

                    logger.warning(
                        "Marking stuck message as FAILED",
                        message_id=str(msg.id),
                        session_id=str(msg.session_id),
                        age_minutes=round(age_minutes, 2),
                        created_at=msg.created_at.isoformat(),
                    )

                    # Mark as failed
                    await update_message_status(
                        message_id=str(msg.id),
                        status=MessageStatus.FAILED,
                        error=f"Processing timeout ({round(age_minutes, 1)}min) - worker may have crashed or hung",
                        db=db,
                    )

                    # PostgreSQL trigger will automatically send NOTIFY
                    # to connected SSE clients

                if stuck_messages:
                    logger.info(
                        "Timeout monitor check completed",
                        stuck_count=len(stuck_messages),
                        marked_failed=len(stuck_messages),
                    )

            except Exception as e:
                logger.error(
                    "Error checking stuck messages",
                    error=str(e),
                    exc_info=True,
                )
                # Continue to next iteration


# Global monitor instance
_monitor: Optional[TimeoutMonitor] = None


def get_monitor() -> TimeoutMonitor:
    """Get or create the global timeout monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = TimeoutMonitor(
            check_interval_seconds=300,  # 5 minutes
            timeout_minutes=10,
        )
    return _monitor


async def start_monitor():
    """
    Start the timeout monitor as a background task.

    Should be called on application startup.
    """
    monitor = get_monitor()
    task = asyncio.create_task(monitor.run())
    monitor._task = task
    logger.info("Timeout monitor background task started")
    return task


async def stop_monitor():
    """
    Stop the timeout monitor.

    Should be called on application shutdown.
    """
    monitor = get_monitor()
    await monitor.stop()
    logger.info("Timeout monitor stopped")
