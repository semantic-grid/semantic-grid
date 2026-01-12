"""Unified query store for validation and async execution.

Queries go through a lifecycle:
1. VALIDATED - Query passed validation, ready to execute
2. PENDING - Submitted for async execution, waiting to start
3. RUNNING - Currently executing
4. COMPLETE - Finished successfully with results
5. ERROR - Failed with error
6. EXPIRED - TTL exceeded, cleaned up
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class QueryStatus(str, Enum):
    """Status of a query in the store."""

    VALIDATED = "validated"  # Passed validation, ready to execute
    PENDING = "pending"  # Submitted for async execution
    RUNNING = "running"  # Currently executing
    COMPLETE = "complete"  # Finished successfully
    ERROR = "error"  # Failed with error
    EXPIRED = "expired"  # TTL exceeded


@dataclass
class Query:
    """A query with full lifecycle tracking."""

    query_id: str
    sql: str
    status: QueryStatus = QueryStatus.VALIDATED
    created_at: float = field(default_factory=time.time)

    # Validation info
    estimated_rows: int | None = None
    estimated_cost: float | None = None
    cost_tier: str = "unknown"
    explanation: list[str] = field(default_factory=list)

    # Execution info
    started_at: float | None = None
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    rows_returned: int = 0

    # TTL settings
    VALIDATION_TTL = 1800  # 30 minutes for validated but not executed
    RESULT_TTL = 3600  # 1 hour for completed results

    @property
    def elapsed_seconds(self) -> float:
        """Seconds since query was created."""
        if self.completed_at:
            return self.completed_at - self.created_at
        return time.time() - self.created_at

    @property
    def running_seconds(self) -> float | None:
        """Seconds since query started running."""
        if not self.started_at:
            return None
        if self.completed_at:
            return self.completed_at - self.started_at
        return time.time() - self.started_at

    @property
    def is_expired(self) -> bool:
        """Check if query has expired based on its status."""
        age = time.time() - self.created_at

        if self.status == QueryStatus.VALIDATED:
            return age > self.VALIDATION_TTL
        elif self.status in (QueryStatus.COMPLETE, QueryStatus.ERROR):
            if self.completed_at:
                result_age = time.time() - self.completed_at
                return result_age > self.RESULT_TTL
        return False

    @property
    def can_execute(self) -> bool:
        """Check if query can be executed."""
        return self.status == QueryStatus.VALIDATED and not self.is_expired

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response."""
        return {
            "query_id": self.query_id,
            "status": self.status.value,
            "sql": self.sql,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "running_seconds": round(self.running_seconds, 1) if self.running_seconds else None,
            "estimated_rows": self.estimated_rows,
            "estimated_cost": self.estimated_cost,
            "cost_tier": self.cost_tier,
            "rows_returned": self.rows_returned,
            "error": self.error,
            "is_expired": self.is_expired,
        }


class QueryStore:
    """Unified store for query validation and execution.

    Thread-safe (uses asyncio locks) and includes TTL-based cleanup.
    """

    def __init__(self, max_queries: int = 1000):
        """Initialize query store.

        Args:
            max_queries: Maximum number of queries to store
        """
        self._queries: dict[str, Query] = {}
        self._lock = asyncio.Lock()
        self._max_queries = max_queries
        self._cleanup_task: asyncio.Task | None = None

    async def register_validated(
        self,
        sql: str,
        estimated_rows: int | None = None,
        estimated_cost: float | None = None,
        cost_tier: str = "unknown",
        explanation: list[str] | None = None,
    ) -> Query:
        """Register a validated query.

        Called by validate_sql after successful validation.

        Args:
            sql: The validated SQL query
            estimated_rows: Estimated row count from EXPLAIN
            estimated_cost: Estimated cost from EXPLAIN
            cost_tier: Cost tier (auto, confirm, reject)
            explanation: EXPLAIN output lines

        Returns:
            Query with unique query_id in VALIDATED status
        """
        query_id = str(uuid.uuid4())
        query = Query(
            query_id=query_id,
            sql=sql,
            status=QueryStatus.VALIDATED,
            estimated_rows=estimated_rows,
            estimated_cost=estimated_cost,
            cost_tier=cost_tier,
            explanation=explanation or [],
        )

        async with self._lock:
            # Enforce max limit
            if len(self._queries) >= self._max_queries:
                await self._cleanup_oldest_locked()

            self._queries[query_id] = query
            logger.info(f"Registered validated query {query_id}: {sql[:100]}...")

        return query

    async def get(self, query_id: str) -> Query | None:
        """Get a query by ID.

        Args:
            query_id: The query UUID

        Returns:
            Query if found, None otherwise
        """
        async with self._lock:
            query = self._queries.get(query_id)

            if query and query.is_expired:
                logger.info(f"Query {query_id} has expired (status: {query.status.value})")
                query.status = QueryStatus.EXPIRED

            return query

    async def start_execution(self, query_id: str) -> Query | None:
        """Mark query as pending execution.

        Called when run_sql starts async execution.

        Args:
            query_id: The query UUID

        Returns:
            Query if found and can execute, None otherwise
        """
        async with self._lock:
            query = self._queries.get(query_id)

            if not query:
                return None

            if not query.can_execute:
                logger.warning(
                    f"Query {query_id} cannot execute: status={query.status.value}, "
                    f"expired={query.is_expired}"
                )
                return None

            query.status = QueryStatus.PENDING
            logger.info(f"Query {query_id} submitted for execution")
            return query

    async def update_status(
        self,
        query_id: str,
        status: QueryStatus,
        result: dict | None = None,
        error: str | None = None,
        rows_returned: int = 0,
    ) -> None:
        """Update query status during execution.

        Args:
            query_id: The query UUID
            status: New status
            result: Query result (for COMPLETE status)
            error: Error message (for ERROR status)
            rows_returned: Number of rows returned
        """
        async with self._lock:
            query = self._queries.get(query_id)
            if not query:
                logger.warning(f"Query {query_id} not found for status update")
                return

            query.status = status

            if status == QueryStatus.RUNNING:
                query.started_at = time.time()
            elif status in (QueryStatus.COMPLETE, QueryStatus.ERROR):
                query.completed_at = time.time()

            if result is not None:
                query.result = result
            if error is not None:
                query.error = error
            query.rows_returned = rows_returned

            logger.info(f"Query {query_id} status: {status.value}")

    async def _cleanup_oldest_locked(self) -> None:
        """Remove oldest queries to make room (must hold lock)."""
        if not self._queries:
            return

        sorted_queries = sorted(self._queries.values(), key=lambda q: q.created_at)
        remove_count = max(1, len(sorted_queries) // 10)

        for query in sorted_queries[:remove_count]:
            del self._queries[query.query_id]
            logger.debug(f"Removed old query {query.query_id}")

    async def cleanup_expired(self) -> int:
        """Remove expired queries.

        Returns:
            Number of queries removed
        """
        removed = 0

        async with self._lock:
            expired_ids = [qid for qid, q in self._queries.items() if q.is_expired]

            for query_id in expired_ids:
                del self._queries[query_id]
                removed += 1

        if removed:
            logger.info(f"Cleaned up {removed} expired queries")

        return removed

    async def start_cleanup_loop(self, interval_seconds: int = 300) -> None:
        """Start background cleanup loop.

        Args:
            interval_seconds: How often to run cleanup (default 5 minutes)
        """
        if self._cleanup_task is not None:
            return

        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    await self.cleanup_expired()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception(f"Cleanup loop error: {e}")

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info(f"Started cleanup loop (interval: {interval_seconds}s)")

    async def stop_cleanup_loop(self) -> None:
        """Stop the background cleanup loop."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Stopped cleanup loop")

    def stats(self) -> dict:
        """Get store statistics."""
        statuses = {}
        for query in self._queries.values():
            statuses[query.status.value] = statuses.get(query.status.value, 0) + 1

        return {
            "total_queries": len(self._queries),
            "by_status": statuses,
            "max_queries": self._max_queries,
        }


# Global query store instance
_query_store: QueryStore | None = None


def get_query_store() -> QueryStore:
    """Get the global query store instance."""
    global _query_store
    if _query_store is None:
        _query_store = QueryStore()
    return _query_store


# Backwards compatibility aliases
TaskStatus = QueryStatus
QueryTask = Query
QueryTaskStore = QueryStore
get_task_store = get_query_store
