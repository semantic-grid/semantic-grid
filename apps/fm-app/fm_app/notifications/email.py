"""Email notification service using AWS SES."""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from fm_app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> bool:
    """
    Send email using AWS SES.

    Args:
        to_email: Recipient email address
        subject: Email subject
        body_text: Plain text email body
        body_html: HTML email body (optional)

    Returns:
        True if email sent successfully, False otherwise
    """
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        logger.warning("AWS credentials not configured, skipping email send")
        return False

    try:
        # Create SES client
        ses_client = boto3.client(
            "ses",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

        # Build email body
        body = {"Text": {"Data": body_text}}
        if body_html:
            body["Html"] = {"Data": body_html}

        # Send email
        response = ses_client.send_email(
            Source=settings.ses_from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject},
                "Body": body,
            },
        )

        logger.info(
            f"Email sent successfully to {to_email}",
            message_id=response["MessageId"],
        )
        return True

    except ClientError as e:
        logger.error(
            f"Failed to send email to {to_email}: {e.response['Error']['Message']}",
            exc_info=True,
        )
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}", exc_info=True)
        return False


def send_query_completion_email(
    to_email: str,
    query_id: str,
    query_name: Optional[str] = None,
) -> bool:
    """
    Send query completion notification email.

    Args:
        to_email: Recipient email address
        query_id: Query ID
        query_name: Optional query name/description

    Returns:
        True if email sent successfully
    """
    subject = "Your query is ready"

    if query_name:
        subject = f"Your query '{query_name}' is ready"

    # Build query link - using /q/:query_id route
    query_url = f"https://app.apegpt.ai/q/{query_id}"

    body_text = f"""Your query has completed successfully.

View results: {query_url}

---
You received this email because you requested a notification when your query completed.
"""

    body_html = f"""
<html>
<head></head>
<body>
    <p>Your query has completed successfully.</p>

    <p><a href="{query_url}">View results</a></p>

    <hr>
    <p style="font-size: 12px; color: #666;">
        You received this email because you requested a notification when
        your query completed.
    </p>
</body>
</html>
"""

    return send_email(to_email, subject, body_text, body_html)
