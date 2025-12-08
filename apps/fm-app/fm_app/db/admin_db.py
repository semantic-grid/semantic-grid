import logging

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fm_app.api.model import GetRequestModel, GetSessionModel, RequestStatus


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


class AdminRequestsResult:
    """Result container for admin requests query with pagination metadata."""

    def __init__(self, requests: list[GetRequestModel], total: int):
        self.requests = requests
        self.total = total


async def get_all_requests_admin_v2(
    limit: int,
    offset: int,
    admin: str,
    status: RequestStatus,
    search: str | None,
    has_feedback: bool | None,
    db: AsyncSession,
) -> AdminRequestsResult:
    """
    Get all requests for admin with user email, search, and total count.
    Joins with session table to get user_owner (Auth0 sub).
    """
    logging.debug(
        "Get all requests v2",
        extra={"admin": admin, "action": "db::get_all_requests_admin_v2"},
    )

    # Build WHERE clause
    where_conditions = ["r.status = :status"]
    params: dict = {"status": status, "limit": limit, "offset": offset}

    # Only filter for non-null SQL when not looking at Error status
    if status != RequestStatus.error:
        where_conditions.append("r.sql is not null")

    if search:
        where_conditions.append(
            "(r.request ILIKE :search OR r.sql ILIKE :search "
            "OR s.user_owner ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    if has_feedback:
        where_conditions.append("(r.rating IS NOT NULL OR r.review IS NOT NULL)")

    where_clause = " AND ".join(where_conditions)

    # Count query
    count_sql = text(
        f"""
        SELECT COUNT(*) as total
        FROM request r
        LEFT JOIN session s ON r.session_id = s.session_id
        WHERE {where_clause};
    """
    )
    count_res = await db.execute(count_sql, params=params)
    total = count_res.scalar() or 0

    # Data query with user_owner from session
    get_all_requests_sql = text(
        f"""
        SELECT r.*, s.user_owner
        FROM request r
        LEFT JOIN session s ON r.session_id = s.session_id
        WHERE {where_clause}
        ORDER BY r.created_at DESC
        LIMIT :limit OFFSET :offset;
    """
    )
    res = await db.execute(get_all_requests_sql, params=params)
    data = res.mappings().fetchall()

    result = []
    for row in data:
        try:
            # Extract user_owner before validation
            row_dict = dict(row)
            user_owner = row_dict.pop("user_owner", None)

            request_model = GetRequestModel.model_validate(row_dict)
            # Store user_owner in a way the frontend can access
            # We'll add it as session.user if session doesn't exist
            if request_model.session is None and user_owner:
                request_model.session = GetSessionModel(
                    user=user_owner,
                    session_id=request_model.session_id,
                    created_at=request_model.created_at,
                )
            result.append(request_model)
        except ValidationError as e:
            logging.error(f"Can't validate Request object from DB error: {e}")
            raise HTTPException(status_code=500, detail=str("Internal error"))

    return AdminRequestsResult(requests=result, total=total)
