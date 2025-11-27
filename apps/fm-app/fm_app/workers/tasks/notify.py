"""Notification Celery tasks."""

import logging

from fm_app.notifications.email import send_query_completion_email
from fm_app.workers.worker import app

logger = logging.getLogger(__name__)


@app.task(name="send_query_notification", bind=True, max_retries=3)
def send_query_notification(self, query_id: str, user_email: str):
    """
    Send query completion notification email.

    Args:
        query_id: Query ID
        user_email: User email address (not persisted to DB)
    """
    logger.info(
        f"Sending query completion notification to {user_email} for query {query_id}"
    )

    try:
        success = send_query_completion_email(
            to_email=user_email,
            query_id=query_id,
        )

        if success:
            logger.info(f"Notification sent successfully to {user_email}")
        else:
            logger.warning(f"Notification failed for {user_email}, will retry")
            # Retry if email failed
            raise Exception("Email send failed")

    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2**self.request.retries)
