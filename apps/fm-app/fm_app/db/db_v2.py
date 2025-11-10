"""
Database access layer for API v2 (message-based architecture).

This module provides CRUD operations for the v2 message-based API:
- messages table
- message_queries table
- message_attachments table
- sessions table (with api_version support)
"""

import json
import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from fm_app.api.v2.model import (
    CreateSessionRequest,
    CreateSessionResponse,
    GetMessagesResponse,
    GetSessionResponse,
    Message,
    MessageAttachment,
    MessageKind,
    MessageQuery,
    MessageRole,
    MessageStatus,
    SendMessageRequest,
    SendMessageResponse,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Session Management (v2)
# ============================================================================


async def create_v2_session(
    request: CreateSessionRequest, user_owner: str, db: AsyncSession
) -> CreateSessionResponse:
    """Create a new v2 session."""
    logger.debug(
        "Creating v2 session",
        extra={"user_owner": user_owner, "action": "db_v2::create_session"},
    )

    session_id = uuid7()
    add_session_sql = text(
        """
        INSERT INTO session (name, tags, user_owner, session_id, parent, api_version)
        VALUES (:name, :tags, :user_owner, :session_id, :parent, 'v2')
        RETURNING session_id, name, tags, user_owner as "user", created_at, parent, api_version;
        """
    )

    res = await db.execute(
        add_session_sql,
        params={
            "name": request.name,
            "tags": request.tags,
            "user_owner": user_owner,
            "session_id": session_id,
            "parent": request.parent,
        },
    )
    data = res.mappings().fetchone()
    await db.commit()

    return CreateSessionResponse(
        session_id=data["session_id"],
        api_version=data["api_version"],
        created_at=data["created_at"],
        messages=[],
    )


async def get_v2_session(
    session_id: UUID, user_owner: str, db: AsyncSession
) -> GetSessionResponse:
    """Get a v2 session with all its messages."""
    logger.debug(
        "Getting v2 session",
        extra={"session_id": session_id, "action": "db_v2::get_session"},
    )

    # Check ownership and api_version
    check_sql = text(
        """
        SELECT session_id, name, tags, user_owner, created_at, api_version
        FROM session
        WHERE session_id = :session_id AND user_owner = :user_owner AND api_version = 'v2';
        """
    )
    res = await db.execute(
        check_sql, params={"session_id": str(session_id), "user_owner": user_owner}
    )
    session_data = res.mappings().fetchone()

    if not session_data:
        raise HTTPException(status_code=404, detail="V2 session not found")

    # Get messages for this session
    messages = await get_messages_for_session(
        session_id=session_id, db=db, limit=1000, offset=0
    )

    return GetSessionResponse(
        session_id=session_data["session_id"],
        api_version=session_data["api_version"],
        created_at=session_data["created_at"],
        messages=messages.messages,
        message_count=messages.total_count,
    )


# ============================================================================
# Message Management
# ============================================================================


async def create_message(
    session_id: UUID,
    user_owner: str,
    msg_request: SendMessageRequest,
    db: AsyncSession,
) -> Message:
    """Create a new message in a session."""
    logger.debug(
        "Creating message",
        extra={
            "session_id": session_id,
            "role": msg_request.role,
            "kind": msg_request.kind,
            "action": "db_v2::create_message",
        },
    )

    # Verify session ownership and that it's v2
    check_sql = text(
        """
        SELECT session_id FROM session
        WHERE session_id = :session_id AND user_owner = :user_owner AND api_version = 'v2';
        """
    )
    res = await db.execute(
        check_sql, params={"session_id": session_id, "user_owner": user_owner}
    )
    if not res.fetchone():
        raise HTTPException(
            status_code=404, detail="V2 session not found or access denied"
        )

    message_id = str(uuid7())

    # Determine persistence based on message kind
    from fm_app.api.v2.model import PERSISTENCE_RULES

    persistent = PERSISTENCE_RULES.get(msg_request.kind, True)

    # Insert message
    insert_sql = text(
        """
        INSERT INTO messages (
            id, session_id, content, content_type, role, kind,
            persistent, metadata, parent_id, thread_id, tags, status
        )
        VALUES (
            :id, :session_id, :content, :content_type, :role, :kind,
            :persistent, :metadata, :parent_id, :thread_id, :tags, :status
        )
        RETURNING id, session_id, content, content_type, role, kind,
                  persistent, created_at, metadata, parent_id, thread_id, tags, status, error;
        """
    )

    res = await db.execute(
        insert_sql,
        params={
            "id": message_id,
            "session_id": str(session_id),
            "content": json.dumps(msg_request.content, default=str),
            "content_type": msg_request.content_type,
            "role": msg_request.role.value,
            "kind": msg_request.kind.value,
            "persistent": persistent,
            "metadata": json.dumps(msg_request.metadata, default=str),
            "parent_id": msg_request.parent_id,
            "thread_id": msg_request.thread_id,
            "tags": msg_request.tags,
            "status": MessageStatus.PENDING.value,
        },
    )

    data = res.mappings().fetchone()
    await db.commit()

    # Parse content back from JSON
    # Handle None, empty string, and invalid JSON cases
    try:
        content = json.loads(data["content"]) if data["content"] else ""
    except (json.JSONDecodeError, TypeError):
        content = data["content"] or ""

    try:
        metadata = json.loads(data["metadata"]) if data["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    return Message(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        content=content,
        content_type=data["content_type"],
        role=MessageRole(data["role"]),
        kind=MessageKind(data["kind"]),
        persistent=data["persistent"],
        created_at=data["created_at"],
        metadata=metadata,
        parent_id=str(data["parent_id"]) if data["parent_id"] else None,
        thread_id=str(data["thread_id"]) if data["thread_id"] else None,
        tags=data["tags"] or [],
        status=MessageStatus(data["status"]),
        error=data["error"],
        attachments=[],
    )


async def get_message_by_id(message_id: str, db: AsyncSession) -> Optional[Message]:
    """Get a single message by ID."""
    logger.debug(
        "Getting message by ID",
        extra={"message_id": message_id, "action": "db_v2::get_message"},
    )

    query_sql = text(
        """
        SELECT id, session_id, content, content_type, role, kind,
               persistent, created_at, metadata, parent_id, thread_id, tags, status, error
        FROM messages
        WHERE id = :message_id;
        """
    )

    res = await db.execute(query_sql, params={"message_id": message_id})
    data = res.mappings().fetchone()

    if not data:
        return None

    # Parse JSON fields
    try:
        content = json.loads(data["content"]) if data["content"] else ""
    except (json.JSONDecodeError, TypeError):
        content = data["content"] or ""

    try:
        metadata = json.loads(data["metadata"]) if data["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    # Get attachments
    attachments = await get_message_attachments(message_id=message_id, db=db)

    return Message(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        content=content,
        content_type=data["content_type"],
        role=MessageRole(data["role"]),
        kind=MessageKind(data["kind"]),
        persistent=data["persistent"],
        created_at=data["created_at"],
        metadata=metadata,
        parent_id=str(data["parent_id"]) if data["parent_id"] else None,
        thread_id=str(data["thread_id"]) if data["thread_id"] else None,
        tags=data["tags"] or [],
        status=MessageStatus(data["status"]),
        error=data["error"],
        attachments=attachments,
    )


async def get_messages_for_session(
    session_id: UUID,
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    role: Optional[MessageRole] = None,
    kind: Optional[MessageKind] = None,
    persistent_only: bool = True,
) -> GetMessagesResponse:
    """Get messages for a session with optional filtering."""
    logger.debug(
        "Getting messages for session",
        extra={
            "session_id": session_id,
            "limit": limit,
            "offset": offset,
            "action": "db_v2::get_messages",
        },
    )

    # Build WHERE clause based on filters
    where_clauses = ["session_id = :session_id"]
    params: dict[str, Any] = {
        "session_id": str(session_id),
        "limit": limit,
        "offset": offset,
    }

    if role:
        where_clauses.append("role = :role")
        params["role"] = role.value

    if kind:
        where_clauses.append("kind = :kind")
        params["kind"] = kind.value

    if persistent_only:
        where_clauses.append("persistent = true")

    where_clause = " AND ".join(where_clauses)

    # Get total count
    count_sql = text(f"SELECT COUNT(*) as count FROM messages WHERE {where_clause};")
    count_res = await db.execute(count_sql, params=params)
    total_count = count_res.scalar()

    # Get messages
    query_sql = text(
        f"""
        SELECT id, session_id, content, content_type, role, kind,
               persistent, created_at, metadata, parent_id, thread_id, tags, status, error
        FROM messages
        WHERE {where_clause}
        ORDER BY created_at ASC
        LIMIT :limit OFFSET :offset;
        """
    )

    res = await db.execute(query_sql, params=params)
    rows = res.mappings().fetchall()

    messages = []
    for data in rows:
        # Parse JSON fields
        try:
            content = json.loads(data["content"]) if data["content"] else ""
        except (json.JSONDecodeError, TypeError):
            content = data["content"] or ""

        try:
            metadata = json.loads(data["metadata"]) if data["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        # Get attachments for this message
        attachments = await get_message_attachments(message_id=data["id"], db=db)

        messages.append(
            Message(
                id=str(data["id"]),
                session_id=str(data["session_id"]),
                content=content,
                content_type=data["content_type"],
                role=MessageRole(data["role"]),
                kind=MessageKind(data["kind"]),
                persistent=data["persistent"],
                created_at=data["created_at"],
                metadata=metadata,
                parent_id=str(data["parent_id"]) if data["parent_id"] else None,
                thread_id=str(data["thread_id"]) if data["thread_id"] else None,
                tags=data["tags"] or [],
                status=MessageStatus(data["status"]),
                error=data["error"],
                attachments=attachments,
            )
        )

    has_more = (offset + limit) < total_count

    return GetMessagesResponse(
        messages=messages, total_count=total_count, has_more=has_more
    )


async def update_message_status(
    message_id: str, status: MessageStatus, error: Optional[str], db: AsyncSession
) -> Message:
    """Update the status of a message."""
    logger.debug(
        "Updating message status",
        extra={
            "message_id": message_id,
            "status": status,
            "action": "db_v2::update_message_status",
        },
    )

    update_sql = text(
        """
        UPDATE messages
        SET status = :status, error = :error
        WHERE id = :message_id
        RETURNING id, session_id, content, content_type, role, kind,
                  persistent, created_at, metadata, parent_id, thread_id, tags, status, error;
        """
    )

    res = await db.execute(
        update_sql,
        params={"message_id": message_id, "status": status.value, "error": error},
    )
    data = res.mappings().fetchone()
    await db.commit()

    if not data:
        raise HTTPException(status_code=404, detail="Message not found")

    # Parse JSON fields
    try:
        content = json.loads(data["content"]) if data["content"] else ""
    except (json.JSONDecodeError, TypeError):
        content = data["content"] or ""

    try:
        metadata = json.loads(data["metadata"]) if data["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    return Message(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        content=content,
        content_type=data["content_type"],
        role=MessageRole(data["role"]),
        kind=MessageKind(data["kind"]),
        persistent=data["persistent"],
        created_at=data["created_at"],
        metadata=metadata,
        parent_id=str(data["parent_id"]) if data["parent_id"] else None,
        thread_id=str(data["thread_id"]) if data["thread_id"] else None,
        tags=data["tags"] or [],
        status=MessageStatus(data["status"]),
        error=data["error"],
        attachments=[],
    )


# ============================================================================
# Message Attachments
# ============================================================================


async def get_message_attachments(
    message_id: str, db: AsyncSession
) -> list[MessageAttachment]:
    """Get all attachments for a message."""
    query_sql = text(
        """
        SELECT id, message_id, content_type, content_url, content_data,
               filename, size_bytes, metadata
        FROM message_attachments
        WHERE message_id = :message_id;
        """
    )

    res = await db.execute(query_sql, params={"message_id": message_id})
    rows = res.mappings().fetchall()

    attachments = []
    for data in rows:
        try:
            metadata = json.loads(data["metadata"]) if data["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        attachments.append(
            MessageAttachment(
                id=data["id"],
                message_id=data["message_id"],
                content_type=data["content_type"],
                content_url=data["content_url"],
                content_data=data["content_data"],
                filename=data["filename"],
                size_bytes=data["size_bytes"],
                metadata=metadata,
            )
        )

    return attachments


async def create_message_attachment(
    attachment: MessageAttachment, db: AsyncSession
) -> MessageAttachment:
    """Create a new message attachment."""
    logger.debug(
        "Creating message attachment",
        extra={
            "message_id": attachment.message_id,
            "action": "db_v2::create_attachment",
        },
    )

    insert_sql = text(
        """
        INSERT INTO message_attachments (
            id, message_id, content_type, content_url, content_data,
            filename, size_bytes, metadata
        )
        VALUES (
            :id, :message_id, :content_type, :content_url, :content_data,
            :filename, :size_bytes, :metadata
        )
        RETURNING id, message_id, content_type, content_url, content_data,
                  filename, size_bytes, metadata;
        """
    )

    res = await db.execute(
        insert_sql,
        params={
            "id": attachment.id,
            "message_id": attachment.message_id,
            "content_type": attachment.content_type,
            "content_url": attachment.content_url,
            "content_data": attachment.content_data,
            "filename": attachment.filename,
            "size_bytes": attachment.size_bytes,
            "metadata": json.dumps(attachment.metadata, default=str),
        },
    )

    await db.commit()
    return attachment


# ============================================================================
# Message Queries (linking to SQL queries)
# ============================================================================


async def create_message_query(query: MessageQuery, db: AsyncSession) -> MessageQuery:
    """Create a message query linking a message to SQL execution."""
    logger.debug(
        "Creating message query",
        extra={
            "message_id": query.message_id,
            "action": "db_v2::create_message_query",
        },
    )

    insert_sql = text(
        """
        INSERT INTO message_queries (
            id, message_id, sql_query, row_count, execution_time_ms,
            prompt_hash, mcp_call_hash, profile, v1_query_id, metadata
        )
        VALUES (
            :id, :message_id, :sql_query, :row_count, :execution_time_ms,
            :prompt_hash, :mcp_call_hash, :profile, :v1_query_id, :metadata
        )
        RETURNING id, message_id, sql_query, row_count, execution_time_ms,
                  prompt_hash, mcp_call_hash, profile, v1_query_id, metadata, created_at;
        """
    )

    res = await db.execute(
        insert_sql,
        params={
            "id": query.id,
            "message_id": query.message_id,
            "sql_query": query.sql_query,
            "row_count": query.row_count,
            "execution_time_ms": query.execution_time_ms,
            "prompt_hash": query.prompt_hash,
            "mcp_call_hash": query.mcp_call_hash,
            "profile": query.profile,
            "v1_query_id": query.v1_query_id,
            "metadata": json.dumps(query.metadata, default=str),
        },
    )

    data = res.mappings().fetchone()
    await db.commit()

    try:
        metadata = json.loads(data["metadata"]) if data["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    return MessageQuery(
        id=data["id"],
        message_id=data["message_id"],
        sql_query=data["sql_query"],
        row_count=data["row_count"],
        execution_time_ms=data["execution_time_ms"],
        prompt_hash=data["prompt_hash"],
        mcp_call_hash=data["mcp_call_hash"],
        profile=data["profile"],
        v1_query_id=data["v1_query_id"],
        metadata=metadata,
        created_at=data["created_at"],
    )


async def get_message_queries(message_id: str, db: AsyncSession) -> list[MessageQuery]:
    """Get all queries associated with a message."""
    query_sql = text(
        """
        SELECT id, message_id, sql_query, row_count, execution_time_ms,
               prompt_hash, mcp_call_hash, profile, v1_query_id, metadata, created_at
        FROM message_queries
        WHERE message_id = :message_id;
        """
    )

    res = await db.execute(query_sql, params={"message_id": message_id})
    rows = res.mappings().fetchall()

    queries = []
    for data in rows:
        try:
            metadata = json.loads(data["metadata"]) if data["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        queries.append(
            MessageQuery(
                id=data["id"],
                message_id=data["message_id"],
                sql_query=data["sql_query"],
                row_count=data["row_count"],
                execution_time_ms=data["execution_time_ms"],
                prompt_hash=data["prompt_hash"],
                mcp_call_hash=data["mcp_call_hash"],
                profile=data["profile"],
                v1_query_id=data["v1_query_id"],
                metadata=metadata,
                created_at=data["created_at"],
            )
        )

    return queries
