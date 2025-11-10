"""
API v2 Routes - Message-based flexible chat architecture.

This module provides REST endpoints for the v2 message-based API:
- Session management (v2-specific)
- Message operations (create, read, list)
- Query execution results as messages
- Real-time updates via SSE (planned)
"""

import asyncio
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import EventSourceResponse
from starlette import status

from fm_app.api.auth0 import VerifyGuestToken, VerifyToken
from fm_app.api.db_session import get_db
from fm_app.api.v2.model import (
    CreateSessionRequest,
    CreateSessionResponse,
    GetMessagesResponse,
    GetSessionResponse,
    Message,
    MessageKind,
    MessageRole,
    MessageStatus,
    SendMessageRequest,
    SendMessageResponse,
)
from fm_app.db.db_v2 import (
    create_message,
    create_v2_session,
    get_message_by_id,
    get_messages_for_session,
    get_v2_session,
    update_message_status,
)

logger = logging.getLogger(__name__)

auth = VerifyToken()
guest_auth = VerifyGuestToken()
api_router_v2 = APIRouter()


async def verify_any_token(
    guest: dict = Depends(guest_auth.verify), user: dict = Depends(auth.verify)
):
    """Verify either guest or user token (for endpoints with Authorization header)."""
    return guest or user


async def verify_any_token_with_cookie(
    request: Request,
):
    """
    Verify either guest or user token from Authorization header OR cookies.
    This is needed for SSE endpoints where EventSource sends cookies but not headers.
    """
    from fastapi.security import HTTPAuthorizationCredentials

    logger.info(f"[SSE Auth] Request path: {request.url.path}")
    logger.info(f"[SSE Auth] Cookies present: {list(request.cookies.keys())}")
    logger.info(
        f"[SSE Auth] Authorization header: {request.headers.get('authorization', 'None')[:50] if request.headers.get('authorization') else 'None'}"
    )

    # Try to get token from Authorization header first
    auth_header = request.headers.get("authorization")
    token_credentials = None

    if auth_header and auth_header.startswith("Bearer "):
        token_str = auth_header.replace("Bearer ", "")
        token_credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token_str
        )
        logger.info("[SSE Auth] Using token from Authorization header")

    # If no header, try to get from cookie
    if not token_credentials:
        # Try uid cookie (guest token)
        uid_cookie = request.cookies.get("uid")
        if uid_cookie:
            token_credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=uid_cookie
            )
            logger.info(f"[SSE Auth] Using token from uid cookie: {uid_cookie[:20]}...")

    if not token_credentials:
        logger.error("[SSE Auth] No token found in header or cookies")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authentication token provided",
        )

    # Try guest auth first
    try:
        from fastapi.security import SecurityScopes

        result = await guest_auth.verify(SecurityScopes(), token_credentials)
        if result:
            logger.info(f"[SSE Auth] Guest auth succeeded: {result.get('sub')}")
            return result
    except Exception as e:
        logger.info(f"[SSE Auth] Guest auth failed: {e}")

    # Try regular auth
    try:
        from fastapi.security import SecurityScopes

        result = await auth.verify(SecurityScopes(), token_credentials)
        if result:
            logger.info(f"[SSE Auth] Regular auth succeeded: {result.get('sub')}")
            return result
    except Exception as e:
        logger.info(f"[SSE Auth] Regular auth failed: {e}")

    logger.error("[SSE Auth] Both auth methods failed")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token",
    )


# ============================================================================
# Session Endpoints
# ============================================================================


@api_router_v2.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    session_request: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> CreateSessionResponse:
    """
    Create a new v2 session.

    V2 sessions use a message-based architecture instead of request/response pairs.
    All interactions are stored as messages with flexible content types.
    """
    if auth_result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token")

    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    logger.info(
        "Creating v2 session",
        extra={"user": user_owner, "session_name": session_request.name},
    )

    response = await create_v2_session(
        request=session_request, user_owner=user_owner, db=db
    )

    return response


@api_router_v2.get("/sessions/{session_id}", response_model=GetSessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetSessionResponse:
    """
    Get a v2 session with all its messages.

    Returns the session metadata and all persistent messages in chronological order.
    """
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    logger.info(
        "Getting v2 session", extra={"session_id": session_id, "user": user_owner}
    )

    response = await get_v2_session(session_id=session_id, user_owner=user_owner, db=db)

    return response


# ============================================================================
# Message Endpoints
# ============================================================================


@api_router_v2.post(
    "/sessions/{session_id}/messages", response_model=SendMessageResponse
)
async def send_message(
    session_id: UUID,
    message_request: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> SendMessageResponse:
    """
    Send a message to a session.

    Creates a new message and triggers processing based on the message kind:
    - CHAT: Triggers AI response generation
    - SLASH_COMMAND: Executes command and returns result
    - QUERY_RESULT: Stores query execution result
    - etc.

    The response includes the created user message and any immediate assistant responses.
    """
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    logger.info(
        "Sending message",
        extra={
            "session_id": session_id,
            "user": user_owner,
            "role": message_request.role,
            "kind": message_request.kind,
        },
    )

    # Create the user message
    user_message = await create_message(
        session_id=session_id,
        user_owner=user_owner,
        msg_request=message_request,
        db=db,
    )

    # Mark user message as processing
    await update_message_status(
        message_id=user_message.id,
        status=MessageStatus.PROCESSING,
        error=None,
        db=db,
    )

    # Dispatch to v2 worker for processing
    from uuid_extensions import uuid7

    from fm_app.api.v1.model import DBType, ModelType
    from fm_app.workers.v2.model import (
        FlowTypeV2,
        MessageProcessingStrategy,
        WorkerMessageRequest,
    )

    task_id = str(uuid7())

    # Create worker request
    worker_request = WorkerMessageRequest(
        session_id=str(session_id),
        message_id=user_message.id,
        user=user_owner,
        content=message_request.content,
        content_type=message_request.content_type,
        kind=message_request.kind,
        flow=FlowTypeV2.DIRECT,  # Default flow, can be made configurable
        strategy=MessageProcessingStrategy.SMART_ROUTING,
        model=ModelType.anthropic_default,  # Default to Claude
        db=DBType.v2,  # Default to v2 database
        parent_message_id=message_request.parent_id,
        thread_id=message_request.thread_id,
        metadata=message_request.metadata,
    )

    # Dispatch to Celery
    from fm_app.workers.worker import wrk_process_message_v2

    task = wrk_process_message_v2.apply_async(
        args=[worker_request.model_dump()], task_id=task_id
    )

    logger.info(
        "Dispatched v2 message to worker",
        extra={
            "task_id": task_id,
            "message_id": user_message.id,
            "session_id": str(session_id),
        },
    )

    # For now, return immediately (async processing)
    # In future, could:
    # 1. Wait for task completion
    # 2. Stream results via SSE
    # 3. Return task_id for polling

    assistant_messages = []

    # Return pending status - frontend can poll or use SSE for updates
    await update_message_status(
        message_id=user_message.id,
        status=MessageStatus.COMPLETED,  # User message accepted
        error=None,
        db=db,
    )

    return SendMessageResponse(
        message_id=user_message.id,
        status=MessageStatus.COMPLETED,
        assistant_messages=assistant_messages,
    )


@api_router_v2.get(
    "/sessions/{session_id}/messages", response_model=GetMessagesResponse
)
async def get_messages(
    session_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    role: Optional[MessageRole] = Query(None, description="Filter by message role"),
    kind: Optional[MessageKind] = Query(None, description="Filter by message kind"),
    persistent_only: bool = Query(True, description="Only return persistent messages"),
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetMessagesResponse:
    """
    Get messages for a session with optional filtering.

    Supports pagination and filtering by:
    - role (user, assistant, system, tool)
    - kind (chat, query_result, notification, etc.)
    - persistent_only (exclude transient messages)
    """
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    logger.info(
        "Getting messages",
        extra={
            "session_id": session_id,
            "user": user_owner,
            "limit": limit,
            "offset": offset,
        },
    )

    # Verify session ownership (will raise 404 if not found or not owned)
    await get_v2_session(session_id=session_id, user_owner=user_owner, db=db)

    response = await get_messages_for_session(
        session_id=session_id,
        db=db,
        limit=limit,
        offset=offset,
        role=role,
        kind=kind,
        persistent_only=persistent_only,
    )

    return response


@api_router_v2.get("/messages/{message_id}", response_model=Message)
async def get_message(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> Message:
    """
    Get a single message by ID.

    Returns the message with all its attachments and metadata.
    """
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    logger.info("Getting message", extra={"message_id": message_id, "user": user_owner})

    message = await get_message_by_id(message_id=message_id, db=db)

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # TODO: Verify user has access to this message's session
    # For now, trust the message exists and return it

    return message


# ============================================================================
# Health Check
# ============================================================================


@api_router_v2.get("/health")
async def health_check():
    """Health check endpoint for v2 API."""
    return {"status": "healthy", "api_version": "v2"}


# ============================================================================
# Server-Sent Events (SSE) - Real-time status updates
# ============================================================================


@api_router_v2.get("/sessions/{session_id}/stream")
async def stream_agent_events(
    session_id: UUID,
    request: Request,
    auth_result: dict = Depends(verify_any_token_with_cookie),
):
    """
    Server-Sent Events endpoint for real-time agent status updates.

    Streams AgentEvent objects as they are emitted during message processing.

    Authentication: Uses cookie-based auth (guest or user token).

    Event format:
    ```
    event: agent_status
    data: {
        "id": "event-uuid",
        "session_id": "session-uuid",
        "message_id": "message-uuid",
        "event_type": "llm_thinking",
        "level": "info",
        "message": "Analyzing your request...",
        "details": {},
        "step": 3,
        "total_steps": 6,
        "progress_percent": 50.0,
        "timestamp": "2025-01-09T12:34:56.789Z"
    }
    ```

    Usage from frontend:
    ```javascript
    const eventSource = new EventSource('/api/v2/sessions/{session_id}/stream', {
        withCredentials: true  // Send cookies for authentication
    });
    eventSource.addEventListener('agent_status', (e) => {
        const event = JSON.parse(e.data);
        console.log(event.message);  // "Analyzing your request..."
    });
    ```
    """
    # Get user from auth result (handled by dependency)
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    # Get event bus for transient events
    import asyncpg

    from fm_app.config import get_settings
    from fm_app.workers.v2.event_bus import get_event_bus

    event_bus = get_event_bus()
    settings = get_settings()

    # Database URL for PostgreSQL NOTIFY
    db_url = (
        f"postgresql://{settings.database_user}:{settings.database_pass}"
        f"@{settings.database_server}:{settings.database_port}/{settings.database_db}"
    )

    async def event_generator():
        """
        Generate SSE events from both EventBus and PostgreSQL NOTIFY.

        Hybrid approach:
        - EventBus: Transient progress events (thinking, validating, etc.)
        - PostgreSQL NOTIFY: Persistent message state changes
        """
        queue = None
        pg_conn = None
        notify_queue = asyncio.Queue()

        def pg_notification_callback(connection, pid, channel, payload):
            """Callback for PostgreSQL notifications."""
            notify_queue.put_nowait(payload)

        try:
            # Subscribe to EventBus for transient events
            queue = await event_bus.subscribe(session_id)

            # Connect to PostgreSQL for persistent events
            pg_conn = await asyncpg.connect(db_url)
            await pg_conn.add_listener("v2_message_update", pg_notification_callback)

            logger.info(
                "SSE connection established for v2 session (hybrid mode)",
                extra={
                    "action": "sse_connect_v2_hybrid",
                    "session_id": str(session_id),
                    "user": user_owner,
                },
            )

            # Send initial connection event
            yield {
                "event": "connected",
                "data": json.dumps(
                    {
                        "session_id": str(session_id),
                        "timestamp": asyncio.get_event_loop().time(),
                        "api_version": "v2",
                        "mode": "hybrid",
                    }
                ),
            }

            # Listen for events from both sources
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    logger.info(
                        "SSE client disconnected",
                        extra={
                            "action": "sse_disconnect_v2",
                            "session_id": str(session_id),
                            "user": user_owner,
                        },
                    )
                    break

                # Create tasks for both event sources
                event_bus_task = asyncio.create_task(queue.get())
                pg_notify_task = asyncio.create_task(notify_queue.get())

                try:
                    # Wait for first event from either source (30s timeout)
                    done, pending = await asyncio.wait(
                        [event_bus_task, pg_notify_task],
                        timeout=30.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # Cancel pending tasks
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    if done:
                        # Get result from completed task
                        completed_task = done.pop()
                        result = completed_task.result()

                        # Determine which source the event came from
                        if completed_task == pg_notify_task:
                            # PostgreSQL NOTIFY event (persistent message update)
                            payload = json.loads(result)

                            # Filter: only send if this session
                            if payload.get("session_id") == str(session_id):
                                yield {
                                    "event": "message_update",
                                    "data": json.dumps(payload),
                                }
                        else:
                            # EventBus event (transient progress)
                            yield {
                                "event": "agent_status",
                                "data": json.dumps(result.to_sse_dict()),
                            }
                    else:
                        # Timeout - send keepalive ping
                        yield {
                            "event": "ping",
                            "data": json.dumps(
                                {"timestamp": asyncio.get_event_loop().time()}
                            ),
                        }

                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield {
                        "event": "ping",
                        "data": json.dumps(
                            {"timestamp": asyncio.get_event_loop().time()}
                        ),
                    }

        except Exception as e:
            logger.error(
                "Error in SSE event generator",
                extra={
                    "action": "sse_error_v2",
                    "session_id": str(session_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)}),
            }

        finally:
            # Cleanup: unsubscribe from event bus
            if queue is not None:
                await event_bus.unsubscribe(session_id, queue)

            # Cleanup: close PostgreSQL connection
            if pg_conn is not None:
                try:
                    await pg_conn.remove_listener(
                        "v2_message_update", pg_notification_callback
                    )
                    await pg_conn.close()
                except Exception as e:
                    logger.warning(
                        "Error closing PostgreSQL connection",
                        extra={"error": str(e)},
                    )

            logger.info(
                "SSE connection closed",
                extra={
                    "action": "sse_close_v2",
                    "session_id": str(session_id),
                    "user": user_owner,
                },
            )

    return EventSourceResponse(event_generator())
