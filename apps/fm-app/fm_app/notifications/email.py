"""Email notification service using AWS SES."""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from fm_app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def obfuscate_email(email: str) -> str:
    """Obfuscate email for logging: leo@apegpt.ai -> l*o@a*****i"""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        local_obf = local[0] + "*" if len(local) > 0 else "*"
    else:
        local_obf = local[0] + "*" * (len(local) - 2) + local[-1]
    if len(domain) <= 2:
        domain_obf = domain[0] + "*" if len(domain) > 0 else "*"
    else:
        domain_obf = domain[0] + "*" * (len(domain) - 2) + domain[-1]
    return f"{local_obf}@{domain_obf}"


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
            f"Email sent successfully to {obfuscate_email(to_email)}",
            extra={"message_id": response["MessageId"]},
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
    summary: Optional[str] = None,
    row_count: Optional[int] = None,
) -> bool:
    """
    Send query completion notification email.

    Args:
        to_email: Recipient email address
        query_id: Query ID
        query_name: Optional query name/description
        summary: Optional query summary/description
        row_count: Optional total row count

    Returns:
        True if email sent successfully
    """
    subject = "Your query is ready"

    if query_name:
        subject = f"Your query '{query_name}' is ready"

    # Build query links - using /q/:query_id route
    query_url = f"{settings.app_base_url}/q/{query_id}"
    download_url = f"{settings.app_base_url}/q/{query_id}?download=true"

    # Build summary section
    summary_text = ""
    summary_html = ""
    if summary or row_count:
        summary_parts = []
        if summary:
            summary_parts.append(summary)
        if row_count is not None:
            summary_parts.append(f"{row_count:,} rows returned")
        summary_text = "\n".join(summary_parts) + "\n\n"
        summary_html = "".join(
            f"<p style='margin: 5px 0; color: #333;'>{part}</p>"
            for part in summary_parts
        )

    body_text = f"""Your query has completed successfully.

{summary_text}View results: {query_url}

Download CSV: {download_url}

---
You received this email because you requested a notification when your query completed.
"""

    body_html = f"""
<html>
<head></head>
<body>
    <p>Your query has completed successfully.</p>

    {summary_html}

    <p style="margin-top: 20px;">
        <a href="{query_url}" style="display: inline-block; padding: 10px 20px; background-color: #1976d2; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px;">View Results</a>
        <a href="{download_url}" style="display: inline-block; padding: 10px 20px; background-color: #388e3c; color: white; text-decoration: none; border-radius: 4px;">Download CSV</a>
    </p>

    <hr>
    <p style="font-size: 12px; color: #666;">
        You received this email because you requested a notification when
        your query completed.
    </p>
</body>
</html>
"""

    return send_email(to_email, subject, body_text, body_html)


def send_query_timeout_email(
    to_email: str,
    query_id: str,
    timeout_minutes: int,
    query_name: Optional[str] = None,
) -> bool:
    """
    Send query timeout notification email.

    Args:
        to_email: Recipient email address
        query_id: Query ID
        timeout_minutes: Timeout duration in minutes
        query_name: Optional query name/description

    Returns:
        True if email sent successfully
    """
    subject = "Your query timed out"

    if query_name:
        subject = f"Your query '{query_name}' timed out"

    # Build query link
    query_url = f"{settings.app_base_url}/q/{query_id}"

    body_text = f"""Your query execution timed out after {timeout_minutes} minutes.

This usually means the query is processing too much data or is too complex.

Suggestions to fix this:
• Add a LIMIT clause to reduce the number of results
• Add more WHERE filters to narrow down the data
• Use aggregate functions instead of returning all rows
• Break the query into smaller parts

View and modify query: {query_url}

---
You received this email because you requested a notification for this query.
"""

    body_html = f"""
<html>
<head></head>
<body>
    <p><strong>
        Your query execution timed out after {timeout_minutes} minutes.
    </strong></p>

    <p>This usually means the query is processing too much data or is too complex.</p>

    <p><strong>Suggestions to fix this:</strong></p>
    <ul>
        <li>Add a LIMIT clause to reduce the number of results</li>
        <li>Add more WHERE filters to narrow down the data</li>
        <li>Use aggregate functions instead of returning all rows</li>
        <li>Break the query into smaller parts</li>
    </ul>

    <p><a href="{query_url}">View and modify query</a></p>

    <hr>
    <p style="font-size: 12px; color: #666;">
        You received this email because you requested a notification for this query.
    </p>
</body>
</html>
"""

    return send_email(to_email, subject, body_text, body_html)
