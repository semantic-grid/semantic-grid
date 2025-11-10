import logging

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fm_app.api.v1.model import GetRequestModel, GetSessionModel, RequestStatus


async def get_all_sessions_admin(
    limit: int, offset: int, admin: str, db: AsyncSession
) -> list[GetSessionModel]:
    logging.debug(
        "Get all sessions",
        extra={"admin": admin, "action": "db::get_all_sessions_admin"},
    )
    get_all_session_sql = text(
        """
    SELECT *
    FROM session
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset;
    """
    )
    res = await db.execute(
        get_all_session_sql, params={"limit": limit, "offset": offset}
    )
    data = res.mappings().fetchall()
    result = []
    for s in data:
        try:
            result.append(GetSessionModel.model_validate(s))
        except ValidationError as e:
            logging.error(f"Can't validate Session object from DB error: {e}")
            raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def get_all_requests_admin(
    limit: int, offset: int, admin: str, status: RequestStatus, db: AsyncSession
) -> list[GetRequestModel]:
    logging.debug(
        "Get all requests",
        extra={"admin": admin, "action": "db::get_all_requests_admin"},
    )
    get_all_requests_sql = text(
        """
        SELECT *
        FROM request
        WHERE status = :status and sql is not null
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset;
    """
    )
    res = await db.execute(
        get_all_requests_sql,
        params={"status": status, "limit": limit, "offset": offset},
    )
    data = res.mappings().fetchall()
    result = []
    for s in data:
        try:
            result.append(GetRequestModel.model_validate(s))
        except ValidationError as e:
            logging.error(f"Can't validate Request object from DB error: {e}")
            raise HTTPException(status_code=500, detail=str("Internal error"))
    return result
