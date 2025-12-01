"""Middleware for API health checks and resilience."""

import json
import logging

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class DatabaseHealthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to check database pool health and return 503 when overloaded.

    This prevents cascading failures by returning proper HTTP status codes
    when the database connection pool is exhausted, allowing clients to
    implement proper retry strategies.
    """

    def __init__(self, app, engine: AsyncEngine):
        super().__init__(app)
        self.engine = engine

    async def dispatch(self, request: Request, call_next):
        # Check database pool status before processing request
        pool = self.engine.pool

        # Calculate pool utilization percentage
        total_capacity = pool.size() + pool.overflow()
        if total_capacity > 0:
            utilization = pool.checkedout() / total_capacity

            # If pool is >90% utilized, return 503 Service Unavailable
            if utilization > 0.9:
                logger.warning(
                    "Database pool exhausted",
                    extra={
                        "pool_size": pool.size(),
                        "overflow": pool.overflow(),
                        "checked_out": pool.checkedout(),
                        "utilization": f"{utilization:.1%}",
                    },
                )
                return Response(
                    status_code=503,
                    content=json.dumps(
                        {
                            "error": "service_overloaded",
                            "message": (
                                "Server is experiencing high load. "
                                "Please retry in a few seconds."
                            ),
                            "retry_after": 5,
                        }
                    ),
                    headers={
                        "Retry-After": "5",
                        "Content-Type": "application/json",
                    },
                )

        try:
            response = await call_next(request)
            return response

        except Exception as e:
            error_message = str(e).lower()

            # Check if error is related to database connection pool
            if any(
                keyword in error_message
                for keyword in [
                    "connection pool",
                    "pool exhausted",
                    "too many connections",
                    "connection timeout",
                ]
            ):
                logger.error(
                    "Database connection error",
                    extra={"error": str(e)},
                    exc_info=True,
                )
                return Response(
                    status_code=503,
                    content=json.dumps(
                        {
                            "error": "database_unavailable",
                            "message": (
                                "Database temporarily unavailable. "
                                "Please retry in a moment."
                            ),
                            "retry_after": 10,
                        }
                    ),
                    headers={
                        "Retry-After": "10",
                        "Content-Type": "application/json",
                    },
                )

            # Re-raise other exceptions to be handled by FastAPI's exception handlers
            raise
