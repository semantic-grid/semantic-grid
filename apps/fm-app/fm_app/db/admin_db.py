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
    QueryExplorerItem,
    QueryExplorerRequestSummary,
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
    res = await db.execute(get_all_session_sql, params={"limit": limit, "offset": offset})
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
    status: RequestStatus | None,
    search: str | None,
    has_feedback: bool | None,
    is_test: bool | None,
    is_fixed: bool | None,
    db: AsyncSession,
) -> AdminRequestsResult:
    """
    Get all requests for admin with user email, search, and total count.
    Joins with session table to get user_owner (Auth0 sub).

    If status is None, returns all requests (no status filter).
    """
    logging.debug(
        "Get all requests v2",
        extra={"admin": admin, "action": "db::get_all_requests_admin_v2"},
    )

    # Build WHERE clause
    where_conditions: list[str] = []
    params: dict = {"limit": limit, "offset": offset}

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

    # If status provided, filter by it
    if status is not None:
        where_conditions.append("r.status = :status")
        params["status"] = status
        if status not in statuses_without_sql:
            where_conditions.append("r.sql is not null")

    if search:
        where_conditions.append(
            "(r.request ILIKE :search OR r.sql ILIKE :search OR s.user_owner ILIKE :search)"
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

    # Build WHERE clause - handle empty conditions
    if where_conditions:
        where_clause = "WHERE " + " AND ".join(where_conditions)
    else:
        where_clause = ""

    # Count query
    count_sql = text(
        f"""
        SELECT COUNT(*) as total
        FROM request r
        LEFT JOIN session s ON r.session_id = s.session_id
        {where_clause};
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
        {where_clause}
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
            "(q.request ILIKE :search OR q.sql ILIKE :search OR q.summary ILIKE :search)"
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


class QueryExplorerResult:
    """Result container for query explorer with pagination metadata."""

    def __init__(self, queries: list[QueryExplorerItem], total: int):
        self.queries = queries
        self.total = total


async def get_query_explorer_data(
    limit: int,
    offset: int,
    admin: str,
    search: str | None,
    has_feedback: bool | None,
    db: AsyncSession,
) -> QueryExplorerResult:
    """
    Get query explorer data: queries with their full journey from intent to result.

    For each query, aggregates:
    - All contributing requests (from intent to final SQL)
    - Plan iterations and amendments
    - SQL generation attempts
    - Trace summaries (LLM calls, repairs, errors, duration)
    """
    logging.debug(
        "Get query explorer data",
        extra={"admin": admin, "action": "db::get_query_explorer_data"},
    )

    # Build WHERE clause for queries
    where_conditions = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if search:
        where_conditions.append(
            "(q.request ILIKE :search OR q.sql ILIKE :search OR q.summary ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    # Filter by has_feedback: queries where any contributing request has a rating
    # Rating is on the request table, so we need to check if any request for this query has rating
    if has_feedback:
        where_conditions.append(
            """EXISTS (
                SELECT 1 FROM request req
                WHERE req.query_id = q.query_id AND req.rating IS NOT NULL
            )"""
        )

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

    # Get queries with session info (join through request table)
    get_queries_sql = text(
        f"""
        SELECT q.*, r.session_id, s.user_owner
        FROM query q
        LEFT JOIN request r ON r.query_id = q.query_id
        LEFT JOIN session s ON r.session_id = s.session_id
        WHERE {where_clause}
        ORDER BY q.created_at DESC
        LIMIT :limit OFFSET :offset;
        """
    )
    res = await db.execute(get_queries_sql, params=params)
    queries_data = res.mappings().fetchall()

    if not queries_data:
        return QueryExplorerResult(queries=[], total=total)

    # Collect session_ids for batch fetching requests
    session_ids = list({row["session_id"] for row in queries_data if row["session_id"]})

    # Fetch all requests that contributed to these queries
    # A request contributes if it's in the same session and:
    # 1. Its query_id matches (direct link), OR
    # 2. It was created before/during query creation (intent, planning, etc.)
    requests_sql = text(
        """
        SELECT r.*
        FROM request r
        WHERE r.session_id = ANY(:session_ids)
        ORDER BY r.created_at ASC;
        """
    )
    req_res = await db.execute(requests_sql, params={"session_ids": session_ids})
    all_requests = req_res.mappings().fetchall()

    # Fetch traces for all these requests
    request_ids = [row["request_id"] for row in all_requests]
    traces_by_request: dict = {}
    if request_ids:
        traces_sql = text(
            """
            SELECT request_id,
                   COUNT(*) FILTER (WHERE step_type = 'llm_call') as llm_calls,
                   COUNT(*) FILTER (WHERE step_type = 'repair') as repairs,
                   COUNT(*) FILTER (WHERE step_type = 'error') as errors,
                   SUM(duration_ms) as total_duration_ms,
                   SUM(tokens_in) as total_tokens_in,
                   SUM(tokens_out) as total_tokens_out
            FROM request_trace
            WHERE request_id = ANY(:request_ids)
            GROUP BY request_id;
            """
        )
        traces_res = await db.execute(traces_sql, params={"request_ids": request_ids})
        for trace_row in traces_res.mappings().fetchall():
            traces_by_request[trace_row["request_id"]] = trace_row

    # Group requests by session for efficient lookup
    requests_by_session: dict = {}
    for req in all_requests:
        sid = req["session_id"]
        if sid not in requests_by_session:
            requests_by_session[sid] = []
        requests_by_session[sid].append(req)

    # Fetch data fetches for all queries
    query_ids = [row["query_id"] for row in queries_data]
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
        for df_row in df_res.mappings().fetchall():
            qid = df_row["query_id"]
            if qid not in data_fetches_by_query:
                data_fetches_by_query[qid] = []
            data_fetches_by_query[qid].append(df_row)

    # Build QueryExplorerItem for each query
    result = []
    for q_row in queries_data:
        query_id = q_row["query_id"]
        session_id = q_row["session_id"]
        query_created = q_row["created_at"]

        # Find contributing requests:
        # Only include requests that are part of THIS query's Plan→Query loop
        # 1. Find the request that directly generated this query (query_id match)
        # 2. Walk backwards to find planning requests until we hit another query's request
        session_requests = requests_by_session.get(session_id, [])

        # Sort by sequence_number or created_at to ensure proper ordering
        sorted_requests = sorted(
            session_requests,
            key=lambda r: (r.get("sequence_number") or 0, r["created_at"]),
        )

        # Find the index of the request that generated this query
        generating_request_idx = None
        for idx, req in enumerate(sorted_requests):
            if req.get("query_id") == query_id:
                generating_request_idx = idx
                break

        contributing = []
        if generating_request_idx is not None:
            # Walk backwards from the generating request
            # Stop when we hit a request that generated a DIFFERENT query
            for idx in range(generating_request_idx, -1, -1):
                req = sorted_requests[idx]
                other_query_id = req.get("query_id")
                # Stop if this request generated a different query (not None, not this query)
                if other_query_id is not None and other_query_id != query_id:
                    break
                contributing.insert(0, req)  # Insert at beginning to maintain order
        else:
            # Fallback: if no generating request found, include requests up to query creation
            for req in sorted_requests:
                if req["created_at"] <= query_created:
                    contributing.append(req)

        # Build request summaries
        request_summaries = []
        original_intent = None
        plan_iterations = 0
        total_sql_attempts = 0
        had_replan = False
        had_amendments = False
        total_duration_ms = 0
        total_tokens_in = 0
        total_tokens_out = 0

        for req in contributing:
            req_id = req["request_id"]

            # Use response_type from DB if available, otherwise infer from text
            request_type = req.get("response_type") or "initial"
            request_text = req.get("request") or ""
            structured = req.get("structured_response") or {}

            # If no response_type in DB, infer from text content (legacy)
            if request_type == "initial":
                # Check if this is a plan approval
                if request_text.startswith("Approved"):
                    request_type = "plan_approval"
                # Check if this is an amendment
                elif "amend" in request_text.lower() or "change" in request_text.lower():
                    request_type = "plan_amendment"
                    had_amendments = True

            # Track amendments
            if request_type == "plan_amendment":
                had_amendments = True

            # Check if this is a replan (structured_response contains replan_reason)
            if isinstance(structured, dict) and structured.get("replan_reason"):
                request_type = "replan"
                had_replan = True

            # Capture original intent from first request
            if original_intent is None and req.get("request"):
                # Skip approval messages for original intent
                if not request_text.startswith("Approved"):
                    original_intent = req["request"]

            # Count plan iterations from query_plan in request if available
            if req.get("query_plan"):
                plan_iterations += 1

            # Count SQL attempts (based on structured_response or trace)
            sql_attempts = 0
            if isinstance(structured, dict):
                attempts_data = structured.get("sql_attempts")
                if isinstance(attempts_data, int):
                    sql_attempts = attempts_data
            total_sql_attempts += sql_attempts

            # Get trace info
            trace = traces_by_request.get(req_id, {})
            has_trace = bool(trace)
            trace_llm_calls = trace.get("llm_calls", 0) or 0
            trace_repairs = trace.get("repairs", 0) or 0
            trace_errors = trace.get("errors", 0) or 0
            trace_duration = trace.get("total_duration_ms", 0) or 0

            total_duration_ms += trace_duration
            total_tokens_in += trace.get("total_tokens_in", 0) or 0
            total_tokens_out += trace.get("total_tokens_out", 0) or 0

            # Build outcome description
            outcome = None
            status = req.get("status")
            if status == "error":
                outcome = "Error occurred"
            elif req.get("query_id") == query_id:
                outcome = "Query generated"

            # Plan tables from query_plan JSONB if available
            plan_tables = None
            query_plan = req.get("query_plan")
            if isinstance(query_plan, dict) and query_plan.get("tables"):
                tables_data = query_plan["tables"]
                if isinstance(tables_data, list):
                    plan_tables = [
                        t.get("name") if isinstance(t, dict) else str(t) for t in tables_data
                    ]

            # Get plan summary from query_plan JSONB
            plan_summary = None
            if isinstance(query_plan, dict):
                plan_summary = query_plan.get("plan_summary")

            try:
                summary = QueryExplorerRequestSummary(
                    request_id=req_id,
                    created_at=req["created_at"],
                    request_type=request_type,
                    request_text=req.get("request") or "",
                    status=RequestStatus(status) if status else RequestStatus.error,
                    has_plan=bool(query_plan),
                    plan_summary=plan_summary,
                    plan_tables=plan_tables,
                    sql_attempts=sql_attempts,
                    sql_success=req.get("query_id") == query_id,
                    outcome=outcome,
                    has_trace=has_trace,
                    trace_llm_calls=trace_llm_calls,
                    trace_repairs=trace_repairs,
                    trace_errors=trace_errors,
                    trace_duration_ms=trace_duration,
                )
                request_summaries.append(summary)
            except ValidationError as e:
                logging.warning(f"Can't validate request summary: {e}")

        # Get rating from contributing requests (rating is on request, not query)
        request_rating = None
        for req in contributing:
            if req.get("rating") is not None:
                request_rating = req["rating"]
                break

        # Build data fetch models for this query
        query_data_fetches = []
        for df_row in data_fetches_by_query.get(query_id, []):
            try:
                query_data_fetches.append(GetDataFetchModel.model_validate(df_row))
            except ValidationError as e:
                logging.warning(f"Can't validate DataFetch: {e}")

        try:
            item = QueryExplorerItem(
                query_id=query_id,
                created_at=query_created,
                summary=q_row.get("summary"),
                sql=q_row.get("sql"),
                row_count=q_row.get("row_count"),
                rating=request_rating,
                session_id=session_id,
                user=q_row.get("user_owner"),
                original_intent=original_intent,
                plan_iterations=plan_iterations,
                sql_attempts=total_sql_attempts,
                total_duration_ms=total_duration_ms,
                total_tokens_in=total_tokens_in,
                total_tokens_out=total_tokens_out,
                requests=request_summaries,
                had_replan=had_replan,
                had_amendments=had_amendments,
                data_fetches=query_data_fetches,
            )
            result.append(item)
        except ValidationError as e:
            logging.error(f"Can't validate QueryExplorerItem: {e}")

    return QueryExplorerResult(queries=result, total=total)
