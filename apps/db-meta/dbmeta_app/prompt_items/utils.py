"""Utility functions for prompt item generation."""

import hashlib


def compute_content_hash(content: str) -> str:
    """Compute SHA256 hash of content for lineage tracking.

    Args:
        content: The text content to hash

    Returns:
        Hex-encoded SHA256 hash (first 16 chars for brevity)
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
