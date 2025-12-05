"""Notification Celery tasks."""

import logging

from fm_app.notifications.email import send_query_completion_email
from fm_app.workers.worker import app

logger = logging.getLogger(__name__)


@app.task(name="send_query_notification", bind=True, max_retries=3)
def send_query_notification(
    self,
    query_id: str,
    user_email: str,
    row_count: int = None,
):
    """
    Send query completion notification email.

    Args:
        query_id: Query ID
        user_email: User email address (not persisted to DB)
        row_count: Optional total row count (passed from worker)
    """
    logger.info(
        f"Sending query completion notification for query {query_id}",
        extra={"query_id": query_id, "has_email": bool(user_email)},
    )

    # Try to fetch query metadata for summary
    summary = None
    try:
        import asyncio

        from fm_app.api.db_session import async_session_factory
        from fm_app.api.stores.query_metadata import get_query_by_id

        async def fetch_summary():
            async with async_session_factory() as db:
                query = await get_query_by_id(query_id=query_id, db=db)
                if query:
                    return query.summary
            return None

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(fetch_summary())
        finally:
            loop.close()
    except Exception as e:
        logger.warning(f"Could not fetch query summary: {e}")

    try:
        success = send_query_completion_email(
            to_email=user_email,
            query_id=query_id,
            summary=summary,
            row_count=row_count,
        )

        if success:
            logger.info(
                f"Notification sent successfully for query {query_id}",
                extra={"query_id": query_id},
            )
        else:
            logger.warning(
                f"Notification failed for query {query_id}, will retry",
                extra={"query_id": query_id},
            )
            # Retry if email failed
            raise Exception("Email send failed")

    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2**self.request.retries)


@app.task(name="send_query_timeout_notification", bind=True, max_retries=3)
def send_query_timeout_notification(
    self, query_id: str, user_email: str, timeout_minutes: int
):
    """
    Send query timeout notification email.

    Args:
        query_id: Query ID
        user_email: User email address (not persisted to DB)
        timeout_minutes: Timeout duration in minutes
    """
    logger.info(
        f"Sending query timeout notification for query {query_id}",
        extra={"query_id": query_id, "timeout_minutes": timeout_minutes},
    )

    try:
        from fm_app.notifications.email import send_query_timeout_email

        success = send_query_timeout_email(
            to_email=user_email,
            query_id=query_id,
            timeout_minutes=timeout_minutes,
        )

        if success:
            logger.info(
                f"Timeout notification sent successfully for query {query_id}",
                extra={"query_id": query_id},
            )
        else:
            logger.warning(
                f"Timeout notification failed for query {query_id}, will retry",
                extra={"query_id": query_id},
            )
            raise Exception("Email send failed")

    except Exception as e:
        logger.error(f"Error sending timeout notification: {e}")
        raise self.retry(exc=e, countdown=2**self.request.retries)
