import logging

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fm_app.api.model import (
    GetDataFetchModel,
    GetQueryModel,
    GetRequestModel,
    GetSessionModel,
    PatchAdminRequestModel,
    RequestStatus,
)


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
    is_test: bool | None,
    is_fixed: bool | None,
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

    # Only filter for non-null SQL when not looking at statuses without SQL yet
    # - error: may have failed before SQL generation
    # - feedback_requested: waiting for user approval of query plan
    # - planning: actively generating query plan
    # - intent: just analyzed intent
    # - in_process: early stage before SQL
    statuses_without_sql = {
        RequestStatus.error,
        RequestStatus.feedback_requested,
        RequestStatus.planning,
        RequestStatus.intent,
        RequestStatus.in_process,
    }
    if status not in statuses_without_sql:
        where_conditions.append("r.sql is not null")

    if search:
        where_conditions.append(
            "(r.request ILIKE :search OR r.sql ILIKE :search "
            "OR s.user_owner ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    if has_feedback:
        where_conditions.append("(r.rating IS NOT NULL OR r.review IS NOT NULL)")

    if is_test is not None:
        where_conditions.append("r.is_test = :is_test")
        params["is_test"] = is_test

    if is_fixed is not None:
        where_conditions.append("r.is_fixed = :is_fixed")
        params["is_fixed"] = is_fixed

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

    # Data query with user_owner from session and query details
    get_all_requests_sql = text(
        f"""
        SELECT r.*, s.user_owner,
               q.query_id as q_query_id, q.request as q_request, q.intent as q_intent,
               q.summary as q_summary, q.description as q_description, q.sql as q_sql,
               q.row_count as q_row_count, q.columns as q_columns, q.chart as q_chart,
               q.ai_generated as q_ai_generated, q.created_at as q_created_at
        FROM request r
        LEFT JOIN session s ON r.session_id = s.session_id
        LEFT JOIN query q ON r.query_id = q.query_id
        WHERE {where_clause}
        ORDER BY r.created_at DESC
        LIMIT :limit OFFSET :offset;
    """
    )
    res = await db.execute(get_all_requests_sql, params=params)
    data = res.mappings().fetchall()

    # Collect all query_ids to fetch data_fetches in bulk
    query_ids = []
    for row in data:
        q_query_id = row.get("q_query_id")
        if q_query_id:
            query_ids.append(q_query_id)

    # Fetch all data_fetches for these queries in one query
    data_fetches_by_query: dict = {}
    if query_ids:
        data_fetches_sql = text(
            """
            SELECT id, query_id, request_id, task_id, requestor, status,
                   created_at, started_at, completed_at, duration_ms,
                   query_params, row_count, error, cache_hit
            FROM data_fetch
            WHERE query_id = ANY(:query_ids)
            ORDER BY created_at DESC;
            """
        )
        df_res = await db.execute(data_fetches_sql, params={"query_ids": query_ids})
        df_rows = df_res.mappings().fetchall()

        for df_row in df_rows:
            try:
                df_model = GetDataFetchModel.model_validate(df_row)
                query_id = df_row["query_id"]
                if query_id not in data_fetches_by_query:
                    data_fetches_by_query[query_id] = []
                data_fetches_by_query[query_id].append(df_model)
            except ValidationError as e:
                logging.warning(f"Can't validate DataFetch object: {e}")

    result = []
    for row in data:
        try:
            # Extract user_owner and query fields before validation
            row_dict = dict(row)
            user_owner = row_dict.pop("user_owner", None)

            # Extract query fields (prefixed with q_)
            query_data = {}
            query_keys = [k for k in list(row_dict.keys()) if k.startswith("q_")]
            for k in query_keys:
                # Remove q_ prefix for the query model
                query_data[k[2:]] = row_dict.pop(k)

            request_model = GetRequestModel.model_validate(row_dict)

            # Build query object if query_id exists
            if query_data.get("query_id"):
                try:
                    request_model.query = GetQueryModel.model_validate(query_data)
                except ValidationError:
                    # If query validation fails, just leave query as None
                    pass

            # Store user_owner in a way the frontend can access
            # We'll add it as session.user if session doesn't exist
            if request_model.session is None and user_owner:
                request_model.session = GetSessionModel(
                    user=user_owner,
                    session_id=request_model.session_id,
                    created_at=request_model.created_at,
                )

            # Attach data_fetches if we have them for this request's query
            q_query_id = query_data.get("query_id")
            if q_query_id and q_query_id in data_fetches_by_query:
                request_model.data_fetches = data_fetches_by_query[q_query_id]

            result.append(request_model)
        except ValidationError as e:
            logging.error(f"Can't validate Request object from DB error: {e}")
            raise HTTPException(status_code=500, detail=str("Internal error"))

    return AdminRequestsResult(requests=result, total=total)


async def update_request_admin(
    request_id: str,
    admin: str,
    patch: PatchAdminRequestModel,
    db: AsyncSession,
) -> GetRequestModel | None:
    """
    Update admin-specific fields on a request.
    Automatically sets fixed_by and fixed_ts when is_fixed is set to True.
    """
    logging.debug(
        "Update request admin fields",
        extra={
            "admin": admin,
            "request_id": request_id,
            "action": "db::update_request_admin",
        },
    )

    # Build dynamic SET clause based on provided fields
    set_clauses = ["updated_at = now()"]
    params: dict = {"request_id": request_id, "admin": admin}

    if patch.is_test is not None:
        set_clauses.append("is_test = :is_test")
        params["is_test"] = patch.is_test

    if patch.is_fixed is not None:
        set_clauses.append("is_fixed = :is_fixed")
        params["is_fixed"] = patch.is_fixed
        # Auto-set fixed_by and fixed_ts when marking as fixed
        if patch.is_fixed:
            set_clauses.append("fixed_by = :fixed_by")
            set_clauses.append("fixed_ts = now()")
            params["fixed_by"] = admin
        else:
            # Clear fixed_by and fixed_ts when unmarking
            set_clauses.append("fixed_by = NULL")
            set_clauses.append("fixed_ts = NULL")

    if patch.fix_comment is not None:
        set_clauses.append("fix_comment = :fix_comment")
        params["fix_comment"] = patch.fix_comment

    set_clause = ", ".join(set_clauses)

    update_sql = text(
        f"""
        UPDATE request
        SET {set_clause}
        WHERE request_id = :request_id
        RETURNING *;
    """
    )

    res = await db.execute(update_sql, params=params)
    row = res.mappings().fetchone()
    await db.commit()

    if not row:
        return None

    try:
        return GetRequestModel.model_validate(row)
    except ValidationError as e:
        logging.error(f"Can't validate Request object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))


class AdminQueriesResult:
    """Result container for admin queries with pagination metadata."""

    def __init__(self, queries: list[GetQueryModel], total: int):
        self.queries = queries
        self.total = total


async def get_all_queries_admin(
    limit: int,
    offset: int,
    admin: str,
    search: str | None,
    db: AsyncSession,
) -> AdminQueriesResult:
    """
    Get all queries for admin with data_fetches and total count.
    """
    logging.debug(
        "Get all queries for admin",
        extra={"admin": admin, "action": "db::get_all_queries_admin"},
    )

    # Build WHERE clause
    where_conditions = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if search:
        where_conditions.append(
            "(q.request ILIKE :search OR q.sql ILIKE :search "
            "OR q.summary ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    where_clause = " AND ".join(where_conditions)

    # Count query
    count_sql = text(
        f"""
        SELECT COUNT(*) as total
        FROM query q
        WHERE {where_clause};
        """
    )
    count_res = await db.execute(count_sql, params=params)
    total = count_res.scalar() or 0

    # Data query
    get_all_queries_sql = text(
        f"""
        SELECT q.*
        FROM query q
        WHERE {where_clause}
        ORDER BY q.created_at DESC
        LIMIT :limit OFFSET :offset;
        """
    )
    res = await db.execute(get_all_queries_sql, params=params)
    data = res.mappings().fetchall()

    # Collect all query_ids to fetch data_fetches in bulk
    query_ids = [row["query_id"] for row in data]

    # Fetch all data_fetches for these queries in one query
    data_fetches_by_query: dict = {}
    if query_ids:
        data_fetches_sql = text(
            """
            SELECT id, query_id, request_id, task_id, requestor, status,
                   created_at, started_at, completed_at, duration_ms,
                   query_params, row_count, error, cache_hit
            FROM data_fetch
            WHERE query_id = ANY(:query_ids)
            ORDER BY created_at DESC;
            """
        )
        df_res = await db.execute(data_fetches_sql, params={"query_ids": query_ids})
        df_rows = df_res.mappings().fetchall()

        for df_row in df_rows:
            try:
                df_model = GetDataFetchModel.model_validate(df_row)
                qid = df_row["query_id"]
                if qid not in data_fetches_by_query:
                    data_fetches_by_query[qid] = []
                data_fetches_by_query[qid].append(df_model)
            except ValidationError as e:
                logging.warning(f"Can't validate DataFetch object: {e}")

    result = []
    for row in data:
        try:
            query_model = GetQueryModel.model_validate(row)

            # Attach data_fetches if we have them for this query
            qid = row["query_id"]
            if qid in data_fetches_by_query:
                query_model.data_fetches = data_fetches_by_query[qid]

            result.append(query_model)
        except ValidationError as e:
            logging.error(f"Can't validate Query object from DB error: {e}")
            raise HTTPException(status_code=500, detail=str("Internal error"))

    return AdminQueriesResult(queries=result, total=total)
