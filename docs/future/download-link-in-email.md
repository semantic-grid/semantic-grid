# Download Link in Email Notifications

## Overview

When a query completes and the user requested notifications, include a secure, time-limited download link in the email so users can download results with one click.

## Architecture

```
Query completes (worker.py)
    │
    ├─► Export results to S3 as CSV
    │   s3://{bucket}/exports/{query_id}/{timestamp}.csv
    │
    ├─► Generate pre-signed URL (24h expiry)
    │
    └─► Send email with download link
        [View Results] [Download CSV]
```

## Implementation

### 1. Add S3 Config Settings

**File: `apps/fm-app/fm_app/config.py`**

```python
# S3 Export settings
s3_exports_bucket: str = "semantic-grid-exports"
s3_exports_prefix: str = "exports"
s3_presigned_url_expiry: int = 86400  # 24 hours in seconds
```

### 2. Create S3 Export Service

**File: `apps/fm-app/fm_app/services/s3_export.py`**

```python
"""S3 export service for query results."""

import csv
import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from fm_app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_s3_client():
    """Get configured S3 client."""
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def export_to_s3(
    query_id: str,
    rows: List[Dict[str, Any]],
    filename: Optional[str] = None,
) -> Optional[str]:
    """
    Export query results to S3 as CSV.
    
    Args:
        query_id: Query identifier
        rows: List of row dictionaries
        filename: Optional custom filename
        
    Returns:
        S3 key if successful, None otherwise
    """
    if not rows:
        logger.warning(f"No rows to export for query {query_id}")
        return None
        
    if not settings.aws_access_key_id:
        logger.warning("AWS credentials not configured, skipping S3 export")
        return None

    try:
        # Generate S3 key
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        s3_key = f"{settings.s3_exports_prefix}/{query_id}/{timestamp}.csv"
        
        # Convert rows to CSV
        output = io.StringIO()
        if rows:
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        csv_bytes = output.getvalue().encode("utf-8")
        
        # Upload to S3
        s3_client = get_s3_client()
        s3_client.put_object(
            Bucket=settings.s3_exports_bucket,
            Key=s3_key,
            Body=csv_bytes,
            ContentType="text/csv",
            ContentDisposition=f'attachment; filename="{filename or query_id}.csv"',
            # Auto-delete after 7 days
            Expires=datetime.utcnow() + timedelta(days=7),
        )
        
        logger.info(f"Exported {len(rows)} rows to s3://{settings.s3_exports_bucket}/{s3_key}")
        return s3_key
        
    except ClientError as e:
        logger.error(f"Failed to export to S3: {e}", exc_info=True)
        return None


def generate_presigned_url(s3_key: str) -> Optional[str]:
    """
    Generate a pre-signed URL for downloading the export.
    
    Args:
        s3_key: S3 object key
        
    Returns:
        Pre-signed URL if successful, None otherwise
    """
    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.s3_exports_bucket,
                "Key": s3_key,
            },
            ExpiresIn=settings.s3_presigned_url_expiry,
        )
        return url
    except ClientError as e:
        logger.error(f"Failed to generate pre-signed URL: {e}", exc_info=True)
        return None


def export_and_get_url(
    query_id: str,
    rows: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Export to S3 and return pre-signed download URL.
    
    Convenience function that combines export and URL generation.
    """
    s3_key = export_to_s3(query_id, rows)
    if s3_key:
        return generate_presigned_url(s3_key)
    return None
```

### 3. Update Email Template

**File: `apps/fm-app/fm_app/notifications/email.py`**

Add download URL parameter to `send_query_completion_email`:

```python
def send_query_completion_email(
    to_email: str,
    query_id: str,
    query_name: Optional[str] = None,
    download_url: Optional[str] = None,  # NEW
    row_count: Optional[int] = None,     # NEW
) -> bool:
    """Send query completion notification email with optional download link."""
    
    subject = "Your query is ready"
    if query_name:
        subject = f"Your query '{query_name}' is ready"

    query_url = f"{settings.app_base_url}/q/{query_id}"
    
    # Build download section
    download_section_text = ""
    download_section_html = ""
    
    if download_url:
        row_info = f" ({row_count:,} rows)" if row_count else ""
        download_section_text = f"""
Download CSV{row_info}: {download_url}
(Link expires in 24 hours)
"""
        download_section_html = f"""
    <p>
        <a href="{download_url}" 
           style="background-color: #4CAF50; color: white; padding: 10px 20px; 
                  text-decoration: none; border-radius: 4px; margin-right: 10px;">
            Download CSV{row_info}
        </a>
        <span style="font-size: 12px; color: #666;">(Link expires in 24 hours)</span>
    </p>
"""

    body_text = f"""Your query has completed successfully.

View results: {query_url}
{download_section_text}
---
You received this email because you requested a notification when your query completed.
"""

    body_html = f"""
<html>
<head></head>
<body>
    <p>Your query has completed successfully.</p>

    <p>
        <a href="{query_url}"
           style="background-color: #2196F3; color: white; padding: 10px 20px; 
                  text-decoration: none; border-radius: 4px; margin-right: 10px;">
            View Results
        </a>
    </p>
    
    {download_section_html}

    <hr>
    <p style="font-size: 12px; color: #666;">
        You received this email because you requested a notification when
        your query completed.
    </p>
</body>
</html>
"""

    return send_email(to_email, subject, body_text, body_html)
```

### 4. Update Worker to Export on Completion

**File: `apps/fm-app/fm_app/workers/worker.py`**

In `wrk_fetch_data`, after successful query execution:

```python
# After getting results, before sending notification:

# Export to S3 and get download URL
download_url = None
if notify_on_complete and settings.s3_exports_bucket:
    from fm_app.services.s3_export import export_and_get_url
    download_url = export_and_get_url(query_id, serialized_rows)

# Update notification call to include download URL
for subscriber in subscribers:
    send_query_notification.delay(
        query_id, 
        subscriber["user_email"],
        download_url=download_url,
        row_count=len(serialized_rows),
    )
```

### 5. Update Notification Task

**File: `apps/fm-app/fm_app/workers/tasks/notify.py`**

```python
@celery_app.task(bind=True)
def send_query_notification(
    self, 
    query_id: str, 
    user_email: str,
    download_url: Optional[str] = None,
    row_count: Optional[int] = None,
):
    """Send query completion notification."""
    from fm_app.notifications.email import send_query_completion_email
    
    send_query_completion_email(
        to_email=user_email,
        query_id=query_id,
        download_url=download_url,
        row_count=row_count,
    )
```

## S3 Bucket Setup

### Bucket Policy (for pre-signed URLs)
No special policy needed - pre-signed URLs work with default private buckets.

### Lifecycle Rule (auto-cleanup)
```json
{
  "Rules": [
    {
      "ID": "DeleteExportsAfter7Days",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "exports/"
      },
      "Expiration": {
        "Days": 7
      }
    }
  ]
}
```

## Environment Variables

```bash
# .env additions
S3_EXPORTS_BUCKET=semantic-grid-exports
S3_EXPORTS_PREFIX=exports
S3_PRESIGNED_URL_EXPIRY=86400  # 24 hours
```

## Security Considerations

1. **Pre-signed URLs are secure** - Only valid for specified duration, tied to specific object
2. **No auth bypass** - User must have received the email (knows their email)
3. **Auto-expiry** - Both URLs (24h) and files (7 days) auto-expire
4. **No PII in filenames** - Use query_id, not user info

## Future Enhancements

1. **Format options** - CSV, JSON, Parquet
2. **Compression** - Gzip for large exports
3. **Streaming export** - For very large datasets, stream directly to S3
4. **Export limits** - Cap at N rows for email exports, full export via app
5. **Cloudflare R2** - Consider R2 for egress cost savings
