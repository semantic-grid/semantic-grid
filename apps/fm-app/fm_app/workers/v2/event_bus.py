"""
Event Bus for V2 Agent Status Updates

Provides a mechanism for workers to emit real-time status events
that can be streamed to clients via SSE.

Uses asyncio queues and Redis pub/sub (in production) to broadcast
events across worker processes.
"""

import asyncio
import json
import logging
from typing import Dict, Optional, Set
from uuid import UUID

import structlog

from fm_app.api.v2.model import AgentEvent, AgentEventLevel, AgentEventType

logger = structlog.wrap_logger(logging.getLogger(__name__))


class EventBus:
    """
    Centralized event bus for agent status updates.

    In-memory implementation (single process).
    For multi-worker deployments, would use Redis pub/sub.
    """

    def __init__(self):
        # Session ID -> Set of queues listening to that session
        self._listeners: Dict[UUID, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def emit(self, event: AgentEvent):
        """
        Emit an agent event to all listeners for this session.

        Args:
            event: The agent event to emit
        """
        session_id = event.session_id

        logger.debug(
            "Emitting agent event",
            session_id=str(session_id),
            event_type=event.event_type.value,
            message=event.message,
        )

        async with self._lock:
            listeners = self._listeners.get(session_id, set())

            # Send event to all listeners (non-blocking)
            for queue in listeners:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "Event queue full, dropping event",
                        session_id=str(session_id),
                        event_type=event.event_type.value,
                    )

    async def subscribe(self, session_id: UUID) -> asyncio.Queue:
        """
        Subscribe to events for a specific session.

        Returns an asyncio.Queue that will receive AgentEvent objects.

        Args:
            session_id: Session to listen to

        Returns:
            Queue that will receive events
        """
        queue = asyncio.Queue(maxsize=100)

        async with self._lock:
            if session_id not in self._listeners:
                self._listeners[session_id] = set()
            self._listeners[session_id].add(queue)

        logger.info(
            "Client subscribed to session events",
            session_id=str(session_id),
            listener_count=len(self._listeners[session_id]),
        )

        return queue

    async def unsubscribe(self, session_id: UUID, queue: asyncio.Queue):
        """
        Unsubscribe from session events.

        Args:
            session_id: Session ID
            queue: The queue to remove
        """
        async with self._lock:
            if session_id in self._listeners:
                self._listeners[session_id].discard(queue)

                # Clean up empty listener sets
                if not self._listeners[session_id]:
                    del self._listeners[session_id]

        logger.info(
            "Client unsubscribed from session events",
            session_id=str(session_id),
        )

    async def cleanup_session(self, session_id: UUID):
        """
        Remove all listeners for a session.

        Args:
            session_id: Session to clean up
        """
        async with self._lock:
            if session_id in self._listeners:
                listener_count = len(self._listeners[session_id])
                del self._listeners[session_id]
                logger.info(
                    "Cleaned up session listeners",
                    session_id=str(session_id),
                    removed_count=listener_count,
                )


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus instance"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


class EventEmitter:
    """
    Convenience wrapper for emitting agent events from workers.

    Automatically includes session/message context in all events.
    """

    def __init__(
        self,
        session_id: UUID,
        message_id: Optional[str] = None,
        bus: Optional[EventBus] = None,
    ):
        self.session_id = session_id
        self.message_id = message_id
        self.bus = bus or get_event_bus()
        self._step = 0
        self._total_steps: Optional[int] = None

    def set_total_steps(self, total: int):
        """Set expected total number of steps for progress tracking"""
        self._total_steps = total

    def _calculate_progress(self) -> Optional[float]:
        """Calculate current progress percentage"""
        if self._total_steps and self._total_steps > 0:
            return min(100.0, (self._step / self._total_steps) * 100)
        return None

    async def emit(
        self,
        event_type: AgentEventType,
        message: str,
        level: AgentEventLevel = AgentEventLevel.INFO,
        details: Optional[Dict] = None,
        increment_step: bool = False,
        **kwargs,
    ):
        """
        Emit an event with auto-populated session/message context.

        Args:
            event_type: Type of event
            message: Human-readable status message
            level: Event severity level
            details: Additional event details
            increment_step: If True, increment step counter
            **kwargs: Additional fields for AgentEvent
        """
        if increment_step:
            self._step += 1

        event = AgentEvent.create(
            session_id=self.session_id,
            message_id=self.message_id,
            event_type=event_type,
            message=message,
            level=level,
            details=details,
            step=self._step if self._step > 0 else None,
            total_steps=self._total_steps,
            progress_percent=self._calculate_progress(),
            **kwargs,
        )

        await self.bus.emit(event)

    # Convenience methods for common event types

    async def task_received(self):
        """Task received by worker (non-verbal)"""
        await self.emit(
            AgentEventType.TASK_RECEIVED,
            "Task received",
            level=AgentEventLevel.DEBUG,
        )

    async def task_started(self):
        """Task processing started"""
        await self.emit(
            AgentEventType.TASK_STARTED,
            "Starting to process your request...",
            increment_step=True,
        )

    async def intent_analyzing(self):
        """Analyzing user intent"""
        await self.emit(
            AgentEventType.INTENT_ANALYZING,
            "Understanding your request...",
            increment_step=True,
        )

    async def intent_analyzed(self, intent: str):
        """Intent understood"""
        await self.emit(
            AgentEventType.INTENT_ANALYZED,
            f"I understand: {intent}",
            level=AgentEventLevel.SUCCESS,
            details={"intent": intent},
        )

    async def plan_drafting(self):
        """Creating execution plan"""
        await self.emit(
            AgentEventType.PLAN_DRAFTING,
            "Planning how to answer your question...",
            increment_step=True,
        )

    async def plan_drafted(self, plan: str):
        """Plan created"""
        await self.emit(
            AgentEventType.PLAN_DRAFTED,
            "Execution plan ready",
            level=AgentEventLevel.SUCCESS,
            details={"plan": plan},
        )

    async def tool_calling(self, tool_name: str, purpose: str):
        """Calling an MCP tool"""
        await self.emit(
            AgentEventType.TOOL_CALLING,
            f"{purpose}...",
            details={"tool": tool_name, "purpose": purpose},
            increment_step=True,
        )

    async def tool_called(self, tool_name: str):
        """Tool call completed"""
        await self.emit(
            AgentEventType.TOOL_CALLED,
            f"Completed {tool_name}",
            level=AgentEventLevel.SUCCESS,
            details={"tool": tool_name},
        )

    async def llm_thinking(self, purpose: str = "Processing"):
        """Engaging LLM"""
        await self.emit(
            AgentEventType.LLM_THINKING,
            f"{purpose}...",
            increment_step=True,
        )

    async def llm_responded(self):
        """LLM response received"""
        await self.emit(
            AgentEventType.LLM_RESPONDED,
            "Response generated",
            level=AgentEventLevel.SUCCESS,
        )

    async def sql_validating(self):
        """Validating SQL"""
        await self.emit(
            AgentEventType.SQL_VALIDATING,
            "Validating SQL query...",
            increment_step=True,
        )

    async def sql_validated(self):
        """SQL validation passed"""
        await self.emit(
            AgentEventType.SQL_VALIDATED,
            "SQL query validated successfully",
            level=AgentEventLevel.SUCCESS,
        )

    async def sql_invalid(self, error: str):
        """SQL validation failed"""
        await self.emit(
            AgentEventType.SQL_INVALID,
            "SQL validation failed",
            level=AgentEventLevel.WARNING,
            details={"error": error},
        )

    async def sql_repairing(self, attempt: int):
        """Repairing failed SQL"""
        await self.emit(
            AgentEventType.SQL_REPAIRING,
            f"Fixing SQL query (attempt {attempt})...",
            level=AgentEventLevel.WARNING,
            details={"attempt": attempt},
            increment_step=True,
        )

    async def query_executing(self):
        """Executing SQL query"""
        await self.emit(
            AgentEventType.QUERY_EXECUTING,
            "Executing query...",
            increment_step=True,
        )

    async def query_executed(self, row_count: int, duration_ms: int):
        """Query execution completed"""
        await self.emit(
            AgentEventType.QUERY_EXECUTED,
            f"Query completed ({row_count} rows, {duration_ms}ms)",
            level=AgentEventLevel.SUCCESS,
            details={"row_count": row_count, "duration_ms": duration_ms},
            duration_ms=duration_ms,
        )

    async def artifact_saving(self):
        """Saving artifacts"""
        await self.emit(
            AgentEventType.ARTIFACT_SAVING,
            "Saving results...",
            increment_step=True,
        )

    async def artifact_saved(self):
        """Artifacts saved"""
        await self.emit(
            AgentEventType.ARTIFACT_SAVED,
            "Results saved",
            level=AgentEventLevel.SUCCESS,
        )

    async def error_detected(self, error: str):
        """Error occurred"""
        await self.emit(
            AgentEventType.ERROR_DETECTED,
            f"Error: {error}",
            level=AgentEventLevel.ERROR,
            details={"error": error},
        )

    async def error_recovering(self):
        """Attempting error recovery"""
        await self.emit(
            AgentEventType.ERROR_RECOVERING,
            "Attempting to recover from error...",
            level=AgentEventLevel.WARNING,
        )

    async def task_completed(self):
        """Task completed successfully"""
        await self.emit(
            AgentEventType.TASK_COMPLETED,
            "Request completed successfully",
            level=AgentEventLevel.SUCCESS,
        )

    async def task_failed(self, error: str):
        """Task failed"""
        await self.emit(
            AgentEventType.TASK_FAILED,
            f"Request failed: {error}",
            level=AgentEventLevel.ERROR,
            details={"error": error},
        )
