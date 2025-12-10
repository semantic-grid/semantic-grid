"""Database operations for data_fetch table."""

import json
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fm_app.api.model import (
    CreateDataFetchModel,
    DataFetchStatus,
    GetDataFetchModel,
)


async def create_data_fetch(
    db: AsyncSession,
    data: CreateDataFetchModel,
) -> GetDataFetchModel:
    """Create a new data fetch record with pending status."""
    logging.debug(
        "Creating data fetch record",
        extra={
            "query_id": str(data.query_id),
            "request_id": str(data.request_id) if data.request_id else None,
            "action": "db::create_data_fetch",
        },
    )

    query_params_json = (
        json.dumps(data.query_params.model_dump()) if data.query_params else None
    )

    insert_sql = text(
        """
        INSERT INTO data_fetch (query_id, request_id, task_id, requestor, query_params)
        VALUES (:query_id, :request_id, :task_id, :requestor, :query_params)
        RETURNING id, query_id, request_id, task_id, requestor, status,
                  created_at, started_at, completed_at, duration_ms,
                  query_params, row_count, error, cache_hit;
        """
    )

    try:
        result = await db.execute(
            insert_sql,
            params={
                "query_id": data.query_id,
                "request_id": data.request_id,
                "task_id": data.task_id,
                "requestor": data.requestor,
                "query_params": query_params_json,
            },
        )
        row = result.mappings().fetchone()
        await db.commit()

        return GetDataFetchModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate DataFetch object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def update_data_fetch_started(
    db: AsyncSession,
    data_fetch_id: UUID,
) -> Optional[GetDataFetchModel]:
    """Update data fetch to running status with started_at timestamp."""
    logging.debug(
        "Updating data fetch to running",
        extra={"data_fetch_id": str(data_fetch_id), "action": "db::update_data_fetch"},
    )

    update_sql = text(
        """
        UPDATE data_fetch
        SET status = 'running', started_at = now()
        WHERE id = :data_fetch_id
        RETURNING id, query_id, request_id, task_id, requestor, status,
                  created_at, started_at, completed_at, duration_ms,
                  query_params, row_count, error, cache_hit;
        """
    )

    try:
        result = await db.execute(update_sql, params={"data_fetch_id": data_fetch_id})
        row = result.mappings().fetchone()
        await db.commit()

        if not row:
            return None

        return GetDataFetchModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate DataFetch object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def update_data_fetch_completed(
    db: AsyncSession,
    data_fetch_id: UUID,
    row_count: int,
    cache_hit: bool = False,
) -> Optional[GetDataFetchModel]:
    """Update data fetch to success status with completion details."""
    logging.debug(
        "Updating data fetch to completed",
        extra={
            "data_fetch_id": str(data_fetch_id),
            "row_count": row_count,
            "cache_hit": cache_hit,
            "action": "db::update_data_fetch",
        },
    )

    update_sql = text(
        """
        UPDATE data_fetch
        SET status = 'success',
            completed_at = now(),
            duration_ms = EXTRACT(MILLISECONDS FROM
                (now() - COALESCE(started_at, created_at)))::integer,
            row_count = :row_count,
            cache_hit = :cache_hit
        WHERE id = :data_fetch_id
        RETURNING id, query_id, request_id, task_id, requestor, status,
                  created_at, started_at, completed_at, duration_ms,
                  query_params, row_count, error, cache_hit;
        """
    )

    try:
        result = await db.execute(
            update_sql,
            params={
                "data_fetch_id": data_fetch_id,
                "row_count": row_count,
                "cache_hit": cache_hit,
            },
        )
        row = result.mappings().fetchone()
        await db.commit()

        if not row:
            return None

        return GetDataFetchModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate DataFetch object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def update_data_fetch_error(
    db: AsyncSession,
    data_fetch_id: UUID,
    error: str,
    status: DataFetchStatus = DataFetchStatus.error,
) -> Optional[GetDataFetchModel]:
    """Update data fetch with error status."""
    logging.debug(
        "Updating data fetch with error",
        extra={
            "data_fetch_id": str(data_fetch_id),
            "status": status.value,
            "action": "db::update_data_fetch",
        },
    )

    update_sql = text(
        """
        UPDATE data_fetch
        SET status = :status,
            completed_at = now(),
            duration_ms = EXTRACT(MILLISECONDS FROM
                (now() - COALESCE(started_at, created_at)))::integer,
            error = :error
        WHERE id = :data_fetch_id
        RETURNING id, query_id, request_id, task_id, requestor, status,
                  created_at, started_at, completed_at, duration_ms,
                  query_params, row_count, error, cache_hit;
        """
    )

    try:
        result = await db.execute(
            update_sql,
            params={
                "data_fetch_id": data_fetch_id,
                "status": status.value,
                "error": error,
            },
        )
        row = result.mappings().fetchone()
        await db.commit()

        if not row:
            return None

        return GetDataFetchModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate DataFetch object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def update_data_fetch_task_id(
    db: AsyncSession,
    data_fetch_id: UUID,
    task_id: str,
) -> Optional[GetDataFetchModel]:
    """Update data fetch with task_id after task is launched."""
    logging.debug(
        "Updating data fetch task_id",
        extra={
            "data_fetch_id": str(data_fetch_id),
            "task_id": task_id,
            "action": "db::update_data_fetch_task_id",
        },
    )

    update_sql = text(
        """
        UPDATE data_fetch
        SET task_id = :task_id
        WHERE id = :data_fetch_id
        RETURNING id, query_id, request_id, task_id, requestor, status,
                  created_at, started_at, completed_at, duration_ms,
                  query_params, row_count, error, cache_hit;
        """
    )

    try:
        result = await db.execute(
            update_sql,
            params={"data_fetch_id": data_fetch_id, "task_id": task_id},
        )
        row = result.mappings().fetchone()
        await db.commit()

        if not row:
            return None

        return GetDataFetchModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate DataFetch object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def get_data_fetch_by_id(
    db: AsyncSession,
    data_fetch_id: UUID,
) -> Optional[GetDataFetchModel]:
    """Get a data fetch record by ID."""
    select_sql = text(
        """
        SELECT id, query_id, request_id, task_id, requestor, status,
               created_at, started_at, completed_at, duration_ms,
               query_params, row_count, error, cache_hit
        FROM data_fetch
        WHERE id = :data_fetch_id;
        """
    )

    try:
        result = await db.execute(select_sql, params={"data_fetch_id": data_fetch_id})
        row = result.mappings().fetchone()

        if not row:
            return None

        return GetDataFetchModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate DataFetch object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def get_data_fetches_by_query(
    db: AsyncSession,
    query_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[GetDataFetchModel]:
    """Get all data fetch records for a query."""
    select_sql = text(
        """
        SELECT id, query_id, request_id, task_id, requestor, status,
               created_at, started_at, completed_at, duration_ms,
               query_params, row_count, error, cache_hit
        FROM data_fetch
        WHERE query_id = :query_id
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset;
        """
    )

    try:
        result = await db.execute(
            select_sql,
            params={"query_id": query_id, "limit": limit, "offset": offset},
        )
        rows = result.mappings().fetchall()

        return [GetDataFetchModel.model_validate(row) for row in rows]

    except ValidationError as e:
        logging.error(f"Can't validate DataFetch object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


class DataFetchesResult:
    """Result container for data fetches query with pagination metadata."""

    def __init__(self, data_fetches: list[GetDataFetchModel], total: int):
        self.data_fetches = data_fetches
        self.total = total


async def get_all_data_fetches_admin(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    status: Optional[DataFetchStatus] = None,
    query_id: Optional[UUID] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> DataFetchesResult:
    """Get all data fetch records for admin with filtering and pagination."""
    logging.debug(
        "Get all data fetches for admin",
        extra={"action": "db::get_all_data_fetches_admin"},
    )

    # Build WHERE clause
    where_conditions = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if status:
        where_conditions.append("df.status = :status")
        params["status"] = status.value

    if query_id:
        where_conditions.append("df.query_id = :query_id")
        params["query_id"] = query_id

    if start_date:
        where_conditions.append("df.created_at >= :start_date")
        params["start_date"] = start_date

    if end_date:
        where_conditions.append("df.created_at <= :end_date")
        params["end_date"] = end_date

    where_clause = " AND ".join(where_conditions)

    # Count query
    count_sql = text(
        f"""
        SELECT COUNT(*) as total
        FROM data_fetch df
        WHERE {where_clause};
        """
    )
    count_result = await db.execute(count_sql, params=params)
    total = count_result.scalar() or 0

    # Data query
    select_sql = text(
        f"""
        SELECT df.id, df.query_id, df.request_id, df.task_id, df.requestor,
               df.status, df.created_at, df.started_at, df.completed_at,
               df.duration_ms, df.query_params, df.row_count, df.error, df.cache_hit
        FROM data_fetch df
        WHERE {where_clause}
        ORDER BY df.created_at DESC
        LIMIT :limit OFFSET :offset;
        """
    )

    try:
        result = await db.execute(select_sql, params=params)
        rows = result.mappings().fetchall()

        data_fetches = [GetDataFetchModel.model_validate(row) for row in rows]
        return DataFetchesResult(data_fetches=data_fetches, total=total)

    except ValidationError as e:
        logging.error(f"Can't validate DataFetch object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
