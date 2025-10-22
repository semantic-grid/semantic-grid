import base64
import hashlib
import json
import logging
import os
import uuid
from uuid import UUID

# TODO: do we need these imports here?
import plotly.graph_objects as go
from fastapi import APIRouter, Depends, HTTPException, Query, Security
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from fm_app.api.auth0 import VerifyGuestToken, VerifyToken
from fm_app.api.db_session import get_db, wh_session
from fm_app.api.model import (
    AddRequestModel,
    ChartRequest,
    ChartStructuredRequest,
    ChartType,
    CreateSessionModel,
    GetRequestModel,
    GetSessionModel,
    PatchSessionModel,
    RequestStatus,
    UpdateRequestStatusModel,
    WorkerRequest,
    AddLinkedRequestModel,
    GetDataResponse,
    View,
    UpdateRequestModel,
    GetQueryModel,
    Version,
    InteractiveRequestType,
    FlowType,
    DBType,
    QueryMetadata, ModelType, CreateQueryFromSqlModel,
)
from fm_app.db.admin_db import get_all_requests_admin, get_all_sessions_admin
from fm_app.db.db import (
    add_new_session,
    add_request,
    get_all_requests,
    get_all_sessions,
    get_request,
    get_session_by_id,
    update_review,
    update_session,
    delete_request_revert_session,
    update_query_metadata,
    update_request_status,
    get_query_by_id,
    get_request_by_id,
    update_request,
    get_queries,
)
from fm_app.stopwatch import stopwatch
from fm_app.workers.worker import wrk_add_request

token_auth_scheme = HTTPBearer()
auth = VerifyToken()
guest_auth = VerifyGuestToken()
api_router = APIRouter()

# Directory to store images
IMAGE_DIR = "static/charts"
HTML_DIR = "static/charts/html"
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(HTML_DIR, exist_ok=True)


import re
from typing import Optional


def replace_order_by(sql: str, new_order_by: Optional[str]) -> str:
    sql = sql.strip().rstrip(";")

    order_by_pattern = re.compile(
        r"\bORDER\s+BY\s+[^)]+?(?=(\bLIMIT\b|\bOFFSET\b|\bFETCH\b|$))",
        flags=re.IGNORECASE | re.DOTALL,
    )
    trailing_clause_pattern = re.compile(
        r"(\s+LIMIT\b.*|\s+OFFSET\b.*|\s+FETCH\b.*)$",
        flags=re.IGNORECASE | re.DOTALL,
    )

    if new_order_by:
        matches = list(order_by_pattern.finditer(sql))
        if matches:
            # Replace only the last one
            last = matches[-1]
            return (
                sql[: last.start()]
                + f"ORDER BY {new_order_by} "
                + sql[last.end() :]
            )
        else:
            # Append new ORDER BY before trailing LIMIT/OFFSET/FETCH
            m = trailing_clause_pattern.search(sql)
            if m:
                return (
                    sql[: m.start()]
                    + f" ORDER BY {new_order_by} "
                    + sql[m.start() :]
                )
            else:
                return f"{sql} ORDER BY {new_order_by} "
    else:
        # Remove only the *last* ORDER BY (if any)
        matches = list(order_by_pattern.finditer(sql))
        if not matches:
            return sql
        last = matches[-1]
        return sql[: last.start()] + " " + sql[last.end():]

import re
from typing import Optional, Tuple

# Trailing clauses we want to remove from the *inner* query:
# - final ORDER BY (up to LIMIT/OFFSET/FETCH or end)
# - trailing LIMIT/OFFSET/FETCH
# We’ll remove them conservatively from the very end, not touching CTEs/subqueries.
_ORDER_BY_TAIL_RE = re.compile(
    r"""            # from the last ORDER BY to end (stopping before a nested clause isn't trivial, so do only tail)
    (               # capture group for replacement
      \s+ORDER\s+BY\s+[^;]*?    # ORDER BY ... (non-greedy)
      (?=(\s+LIMIT\b|\s+OFFSET\b|\s+FETCH\b|$))  # up to LIMIT/OFFSET/FETCH or end
    )
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

_TRAILING_LIMIT_OFFSET_FETCH_RE = re.compile(
    r"(\s+LIMIT\b.*|\s+OFFSET\b.*|\s+FETCH\b.*)$",
    re.IGNORECASE | re.DOTALL,
)

# Accept bare identifiers or dotted (alias.column); we’ll keep only the column piece for the outer query.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")

def _strip_final_order_by_and_trailing(sql: str) -> str:
    s = sql.strip().rstrip(";")

    # Remove only the *last* ORDER BY at the tail
    matches = list(_ORDER_BY_TAIL_RE.finditer(s))
    if matches:
        last = matches[-1]
        s = s[: last.start()] + s[last.end():]

    # Remove trailing LIMIT/OFFSET/FETCH from the remaining tail
    m = _TRAILING_LIMIT_OFFSET_FETCH_RE.search(s)
    if m:
        s = s[: m.start()]

    return s.strip()

def _sanitize_sort_by(sort_by: Optional[str]) -> Optional[str]:
    if not sort_by:
        return None
    sb = sort_by.strip()
    # allow quoted accidental inputs like "token"
    if (sb.startswith('"') and sb.endswith('"')) or (sb.startswith('`') and sb.endswith('`')):
        sb = sb[1:-1].strip()
    if not _IDENTIFIER_RE.match(sb):
        return None
    # Use only the last segment (the final SELECT alias)
    return sb.split(".")[-1]

def build_sorted_paginated_sql(
    user_sql: str,
    *,
    sort_by: Optional[str],
    sort_order: str,  # 'asc' | 'desc' (validated by FastAPI)
    include_total_count: bool = False,  # set True if you want COUNT() OVER () AS total_count
) -> str:
    body = _strip_final_order_by_and_trailing(user_sql)

    if include_total_count:
        outer_select = "SELECT t.*, COUNT(*) OVER () AS total_count"
    else:
        outer_select = "SELECT t.*"

    base = f"""
        {outer_select}
        FROM (
        {body}
        ) AS t
    """

    col = _sanitize_sort_by(sort_by)
    if col:
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        # Always anchor to outer alias to avoid ambiguity from CTEs/joins
        base += f"\nORDER BY t.{col} {direction}"

    # Always page on the outer query
    base += "\nLIMIT :limit\nOFFSET :offset"
    return base

async def verify_any_token(
    guest: dict = Depends(guest_auth.verify), user: dict = Depends(auth.verify)
):
    return guest or user  # If guest verification fails, check regular user verification


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_sql_hash(sql: str) -> str:
    return sha256_str(sql.strip().rstrip(";"))


def compute_rows_fingerprint(rows: list[dict]) -> str:
    """
    Cheap, stable fingerprint over a subset of the data.
    Avoid hashing the entire result for very large pages:
      - take first & last row, total_rows count, and limit/offset
    """
    if not rows:
        return sha256_str("empty")
    first = rows[0]
    last = rows[-1]
    # use json dumps with sort_keys for stability
    return sha256_str(
        json.dumps({"first": first, "last": last}, sort_keys=True, default=str)
    )


def compute_etag(payload: dict) -> str:
    """Stable weak ETag from JSON payload."""
    raw = json.dumps(payload, sort_keys=True, default=str)
    return f'W/"{hashlib.sha256(raw.encode()).hexdigest()}"'

@api_router.post("/session")
async def create_session(
    session: CreateSessionModel,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetSessionModel:
    if auth_result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token")
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    response = await add_new_session(session=session, user_owner=user_owner, db=db)
    return response


@api_router.get("/session")
async def get_sessions(
    db: AsyncSession = Depends(get_db), auth_result: dict = Depends(verify_any_token)
) -> list[GetSessionModel]:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    response = await get_all_sessions(user_owner=user_owner, db=db)
    return response


@api_router.get("/session/{session_id}")
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetSessionModel:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    response = await get_session_by_id(session_id=session_id, db=db)
    return response


@api_router.get("/admin/sessions")
async def admin_get_all_sessions(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auth_result: dict = Security(auth.verify, scopes=["admin:sessions"]),
) -> list[GetSessionModel]:
    if auth_result is None or auth_result.get("sub") is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    admin = auth_result.get("sub")
    response = await get_all_sessions_admin(
        limit=limit, offset=offset, admin=admin, db=db
    )
    return response


@api_router.patch("/session/{session_id}")
async def change_session(
    session_id: UUID,
    session_patch: PatchSessionModel,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetSessionModel:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    response = await update_session(
        user_owner=user_owner, session_id=session_id, session_patch=session_patch, db=db
    )
    return response


@api_router.post("/request/{session_id}")
async def create_request(
    session_id: UUID,
    user_request: AddRequestModel,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetRequestModel:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    (response, task_id) = await add_request(
        user_owner=user_owner, session_id=session_id, add_req=user_request, db=db
    )

    stopwatch.reset()
    print(">>> API CALL", stopwatch.lap())

    wrk_req = WorkerRequest(
        session_id=session_id,
        request_id=response.request_id,
        user=user_owner,
        request=response.request,
        request_type=user_request.request_type,
        response=response.response,
        status=response.status,
        flow=user_request.flow,
        model=user_request.model,
        db=user_request.db,
        refs=user_request.refs,
    )
    wrk_arg = wrk_req.model_dump()
    task = wrk_add_request.apply_async(args=[wrk_arg], task_id=task_id)
    logging.info("Send task", extra={"action": "send_task", "task_id": task})

    return response


@api_router.post("/request/{session_id}/for_query/{query_id}")
async def create_request_for_query(
    session_id: UUID,
    query_id: UUID,
    user_request: AddRequestModel,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetRequestModel:

    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    query = await get_query_by_id(query_id=query_id, db=db)
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Referred query not found"
        )

    (response, task_id) = await add_request(
        user_owner=user_owner, session_id=session_id, add_req=user_request, db=db
    )
    wrk_req = WorkerRequest(
        session_id=session_id,
        request_id=response.request_id,
        user=user_owner,
        request=response.request,
        request_type=user_request.request_type,
        response=response.response,
        status=response.status,
        flow=user_request.flow,
        model=user_request.model,
        db=user_request.db,
        refs=user_request.refs,
        query=query,
    )
    wrk_arg = wrk_req.model_dump()
    task = wrk_add_request.apply_async(args=[wrk_arg], task_id=task_id)
    logging.info("Send task", extra={"action": "send_task", "task_id": task})

    return response


@api_router.post("/request/{session_id}/from_query/{query_id}")
async def create_request_from_query(
    session_id: UUID,
    query_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetRequestModel:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    query = await get_query_by_id(query_id=query_id, db=db)
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Referred query not found"
        )

    # create a request from the query
    # (response, task_id) = await add_request(
    #    user_owner=user_owner,
    #    session_id=session_id,
    #    add_req=AddRequestModel(
    #        version=Version.interactive,
    #        request=query.request,
    #        request_type=InteractiveRequestType.tbd,
    #        flow=FlowType.interactive,
    #        model=(
    #            query.ai_context.get("model") if query.ai_context is not None else None
    #        ),
    #        db=DBType.v2,
    #        refs=None,
    #        query_id=query_id,  # link to the query
    #    ),
    #    db=db,
    # )
    # update the request with the query's SQL and summary
    # await update_request(
    #    db=db,
    #    update=UpdateRequestModel(
    #        request_id=response.request_id,
    #        sql=query.sql,  # use the SQL from the query
    #        intent=query.intent,
    #        response=query.summary,
    #    ),
    # )
    # update the session with the new request name
    # await update_session(
    #    user_owner=user_owner,
    #    session_id=session_id,
    #    session_patch=PatchSessionModel(name=f"request from query"),
    #    db=db,
    # )
    # metadata = QueryMetadata(
    #    id=uuid.uuid4(),
    #    sql=query.sql,
    #    summary=query.summary,
    #    result=query.summary,
    #    columns=query.columns,
    #    row_count=query.row_count,
    # )
    # await update_query_metadata(
    #    session_id=session_id,
    #    user_owner=user_owner,
    #    metadata=metadata.model_dump(),
    #    db=db,
    # )

    (response, task_id) = await add_request(
        user_owner=user_owner,
        session_id=session_id,
        add_req=AddRequestModel(
            version=Version.interactive,
            request=f"Starting from existing query", # query.request,
            request_type=InteractiveRequestType.linked_query,
            flow=FlowType.interactive,
            model=(
                query.ai_context.get("model") if query.ai_context is not None else ModelType.openai_default
            ),
            db=DBType.v2,
            refs=None,
            query_id=query_id,  # link to the query
        ),
        db=db
    )
    wrk_req = WorkerRequest(
        session_id=session_id,
        request_id=response.request_id,
        user=user_owner,
        request=f"Describe query: {query.sql}",  # query.request,
        request_type=InteractiveRequestType.linked_query,
        response=response.response,
        status=response.status,
        flow=FlowType.interactive,
        model=(
            query.ai_context.get(
                "model") if query.ai_context is not None else ModelType.openai_default
        ),
        db=DBType.v2,
        refs=None,
        query=query,
    )

    wrk_arg = wrk_req.model_dump()
    task = wrk_add_request.apply_async(args=[wrk_arg], task_id=task_id)
    logging.info("Send task for request from query", extra={"action": "send_task", "task_id": task, "query_id": query_id})

    return response


@api_router.post("/request/{session_id}/from_sql")
async def create_request_from_sql(
    session_id: UUID,
    query_data: CreateQueryFromSqlModel,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetRequestModel:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    # create a request from the query
    # (response, task_id) = await add_request(
    #    user_owner=user_owner,
    #    session_id=session_id,
    #    add_req=AddRequestModel(
    #        version=Version.interactive,
    #        request=query.request,
    #        request_type=InteractiveRequestType.tbd,
    #        flow=FlowType.interactive,
    #        model=(
    #            query.ai_context.get("model") if query.ai_context is not None else None
    #        ),
    #        db=DBType.v2,
    #        refs=None,
    #        query_id=query_id,  # link to the query
    #    ),
    #    db=db,
    # )
    # update the request with the query's SQL and summary
    # await update_request(
    #    db=db,
    #    update=UpdateRequestModel(
    #        request_id=response.request_id,
    #        sql=query.sql,  # use the SQL from the query
    #        intent=query.intent,
    #        response=query.summary,
    #    ),
    # )
    # update the session with the new request name
    # await update_session(
    #    user_owner=user_owner,
    #    session_id=session_id,
    #    session_patch=PatchSessionModel(name=f"request from query"),
    #    db=db,
    # )
    # metadata = QueryMetadata(
    #    id=uuid.uuid4(),
    #    sql=query.sql,
    #    summary=query.summary,
    #    result=query.summary,
    #    columns=query.columns,
    #    row_count=query.row_count,
    # )
    # await update_query_metadata(
    #    session_id=session_id,
    #    user_owner=user_owner,
    #    metadata=metadata.model_dump(),
    #    db=db,
    # )

    (response, task_id) = await add_request(
        user_owner=user_owner,
        session_id=session_id,
        add_req=AddRequestModel(
            version=Version.interactive,
            request=f"Generate query from SQL: {query_data.sql}", # query.request,
            request_type=InteractiveRequestType.manual_query,
            flow=FlowType.interactive,
            model=(
                query_data.ai_context.get("model") if query_data.ai_context is not None else ModelType.openai_default
            ),
            db=DBType.v2,
            refs=None,
            query_id=None,  # link to the query
        ),
        db=db
    )
    wrk_req = WorkerRequest(
        session_id=session_id,
        request_id=response.request_id,
        user=user_owner,
        request=f"Generate query from SQL: {query_data.sql}",  # query.request,
        request_type=InteractiveRequestType.linked_query,
        response=response.response,
        status=response.status,
        flow=FlowType.interactive,
        model=(
            query_data.ai_context.get(
                "model") if query_data.ai_context is not None else ModelType.openai_default
        ),
        db=DBType.v2,
        refs=None,
        query=None,
    )

    wrk_arg = wrk_req.model_dump()
    task = wrk_add_request.apply_async(args=[wrk_arg], task_id=task_id)
    logging.info("Send task for request from SQL", extra={"action": "send_task", "task_id": task, "sql": query_data.sql})

    return response


@api_router.post("/session/{session_id}/linked")
async def create_linked_session_request(
    session_id: UUID,  # existing session ID to link to
    linked_request: AddLinkedRequestModel,  # request data
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetRequestModel:
    """Create a request in a new session that is linked to the previous session."""
    if auth_result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token")
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    try:
        # create new session
        session = CreateSessionModel(
            name=linked_request.name,
            tags=linked_request.tags,
            parent=session_id,
            refs=linked_request.refs,
        )
        session_response = await add_new_session(
            session=session, user_owner=user_owner, db=db
        )

        # create request in the new session
        add_req = AddRequestModel(
            version=linked_request.version,
            request=linked_request.request,
            flow=linked_request.flow,
            model=linked_request.model,
            db=linked_request.db,
            refs=linked_request.refs,
        )
        (response, task_id) = await add_request(
            user_owner=user_owner,
            session_id=session_response.session_id,
            add_req=add_req,
            db=db,
        )
        wrk_req = WorkerRequest(
            session_id=response.session_id,
            request_id=response.request_id,
            user=user_owner,
            request=response.request,
            response=response.response,
            parent_session_id=session_id,
            status=response.status,
            flow=linked_request.flow,
            model=linked_request.model,
            db=linked_request.db,
            refs=linked_request.refs,
        )
        wrk_arg = wrk_req.model_dump()
        task = wrk_add_request.apply_async(args=[wrk_arg], task_id=task_id)
        logging.info("Send task", extra={"action": "send_task", "task_id": task})
        response.session = session_response
        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create linked session: {str(e)}",
        )


@api_router.get("/request/{session_id}/{seq_num}")
async def get_single_request(
    session_id: UUID,
    seq_num: int,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetRequestModel:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    response = await get_request(
        user_owner=user_owner, session_id=session_id, seq_num=seq_num, db=db
    )
    response.session = await get_session_by_id(session_id, db=db)
    return response


@api_router.get("/session/get_requests/{session_id}")
async def get_requests_for_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> list[GetRequestModel]:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    response = await get_all_requests(
        user_owner=user_owner, session_id=session_id, db=db
    )
    return response


@api_router.patch("/request/{request_id}")
async def update_single_request(
    request_id: UUID,
    user_request: UpdateRequestStatusModel,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
) -> GetRequestModel:
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    if user_request.rating is not None and user_request.review is not None:
        response = await update_review(
            rating=user_request.rating,
            review=user_request.review,
            db=db,
            request_id=request_id,
            user_owner=user_owner,
        )
    elif user_request.status is not None:
        response = await update_request_status(
            status=user_request.status, db=db, request_id=request_id, err=None
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wrong request format",
        )

    return response


@api_router.delete("/request/{request_id}")
async def delete_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
):
    """Delete a request and revert the session to the state before this request was added."""
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )
    response = await delete_request_revert_session(
        db=db,
        request_id=request_id,
        user_owner=user_owner,
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "message": "Request deleted and session reverted",
            "request_id": str(request_id),
            "session_id": str(response) if response else None,
        },
    )


@api_router.get("/admin/requests")
async def admin_get_all_requests(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_param: RequestStatus = Query(RequestStatus.done, alias="status"),
    auth_result: dict = Security(auth.verify, scopes=["admin:requests"]),
) -> list[GetRequestModel]:
    if auth_result is None or auth_result.get("sub") is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an admin"
        )
    admin = auth_result.get("sub")
    print("admin", admin, limit, offset, status_param)
    response = await get_all_requests_admin(
        limit=limit, offset=offset, status=status_param, admin=admin, db=db
    )
    return response


@api_router.post("/chart")
async def generate_chart(request: ChartRequest):
    # TODO: add server-to-server authentication !!!

    python_code = request.code
    # a hack to ensure that Kaleido is imported
    if python_code.find("plotly") > -1 and python_code.find("kaleido") == -1:
        python_code = f"""
            import kaleido\n
            import plotly.io as pio\n
            print(kaleido.__file__) # debug\n
            {python_code}\n
        """
        python_code = python_code.replace(
            'img_bytes = fig.to_image(format="png")',
            'img_bytes = fig.to_image(format="png", engine="kaleido")',
        )
    # print("code", python_code)

    try:
        # Local execution context
        local_vars = {}

        # Execute AI-generated Python code
        exec(python_code, {}, local_vars)
        # print("exec ok")

        # Retrieve the base64 image string
        img_b64 = local_vars.get("img_b64", None)
        # print(img_b64)

        if img_b64 is not None:
            # Generate a unique filename
            filename = f"{uuid.uuid4().hex}.png"
            file_path = os.path.join(IMAGE_DIR, filename)
            # print(file_path)

            # Decode and save the image
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(img_b64))

            # print("image saved")
            # Return the URL
            return JSONResponse(
                content={
                    "chart_url": f"/charts/{filename}",
                    "chart_base64": f"data:image/png;base64,{img_b64}",
                }
            )
        else:
            # print("failed to generate image")
            raise HTTPException(status_code=400, detail="No image generated")

    except Exception as e:
        # print(e)
        raise HTTPException(status_code=500, detail=str(e))


# Serve saved chart images
@api_router.get(
    "/chart/{filename}",
    response_class=FileResponse,
    responses={
        200: {"description": "Returns a PNG image file", "content": {"image/png": {}}},
        404: {
            "description": "Chart not found",
            "content": {"application/json": {"example": {"detail": "Chart not found"}}},
        },
    },
)
async def get_chart(filename: str):
    file_path = os.path.join(IMAGE_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Chart not found")

    return FileResponse(file_path, media_type="image/png")


@api_router.post("/chart/html")
async def generate_chart_html(request: ChartStructuredRequest):
    # print(request.chart_type, request.labels, request.rows)
    fig = "<html><body>Chart not generated</body></html>"
    try:
        if request.chart_type == ChartType.bar:
            zipped = list(zip(*request.rows))
            x = zipped[0]
            y = zipped[1] if len(zipped) == 2 else zipped[len(zipped) - 1]
            y = [float(i) for i in y]
            fig = go.Figure(data=[go.Bar(x=x, y=y)])
        elif request.chart_type == ChartType.pie:
            zipped = list(zip(*request.rows))
            x = zipped[0]
            y = zipped[1] if len(zipped) == 2 else zipped[len(zipped) - 1]
            y = [float(i) for i in y]
            fig = go.Figure(data=[go.Pie(labels=x, values=y)])

        content = fig.to_html(full_html=True, include_plotlyjs="cdn")
        # N.B. to avoid 'Quirk mode' in the browser
        content = f"<!DOCTYPE html>\n{content}"
        # print(content)
        filename = f"{uuid.uuid4().hex}.html"
        file_path = os.path.join(HTML_DIR, filename)
        # print(file_path)

        # Decode and save the image
        with open(file_path, "wb") as f:
            f.write(content.encode())
            # Return the URL
        return JSONResponse(
            content={
                "chart_url": f"/charts/html/{filename}",
            }
        )
    except Exception as e:
        # print(e)
        raise HTTPException(status_code=500, detail=str(e))


# Serve saved chart images
@api_router.get(
    "/chart/html/{filename}",
    response_class=FileResponse,
    responses={
        200: {"description": "Returns a HTML file", "content": {"text/html": {}}},
        404: {
            "description": "Chart not found",
            "content": {"application/json": {"example": {"detail": "Chart not found"}}},
        },
    },
)
async def get_chart_html(filename: str):
    file_path = os.path.join(HTML_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Chart not found")

    return FileResponse(file_path, media_type="text/html")


@api_router.get("/query")
async def get_all_queries(
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[GetQueryModel]:

    response = await get_queries(db=db, limit=limit, offset=offset)

    return response


@api_router.get("/data/{query_id}")
async def get_query_data(
    query_id: UUID,
    limit: int = 100,
    offset: int = 0,
    sort_by: Optional[str] = None,
    sort_order: str = Query("asc", regex="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    original_sql = ""
    sql = ""
    current_view = View(sort_by=sort_by, sort_order=sort_order) if sort_by else None

    # Step 1: Fetch SQL from QueryMetadata store
    query_response = await get_query_by_id(query_id=query_id, db=db)
    if query_response:
        sql = query_response.sql if query_response.sql else ""
        sql = sql.strip().rstrip(";")
        # since we don't have any context except query_id, we don't store View

    else:
        request_response = await get_request_by_id(
            request_id=query_id, db=db, user_owner=""
        )
        if request_response:
            if request_response.query:
                sql = request_response.query.sql if request_response.query.sql else ""
                sql = sql.strip().rstrip(";")
                current_view = (
                    request_response.view if request_response.view else current_view
                )
                sort_by = current_view.sort_by if current_view else (sort_by or "")
                sort_order = (
                    current_view.sort_order if current_view else (sort_order or "")
                )
                new_order_clause = (
                    f"{sort_by} {sort_order.upper()}"
                    if sort_by and sort_order
                    else None
                )
                # sql = replace_order_by(sql, new_order_clause)
                # await update_request(
                #    db=db,
                #    update=UpdateRequestModel(
                #        request_id=query_id, view=current_view, sql=sql
                #    ),
                # )
            else:
                raise HTTPException(
                    status_code=400, detail="Query not found in request"
                )

        else:
            session_response = await get_session_by_id(session_id=query_id, db=db)
            if session_response:
                if not session_response.metadata:
                    raise HTTPException(
                        status_code=400, detail="No metadata found in session"
                    )

                sql = session_response.metadata.get("sql", "").strip().rstrip(";")
                # Determine whether to update stored SQL
                if sort_by:
                    saved_view = session_response.metadata.get("view")
                    current_view = (
                        View(
                            sort_by=saved_view.get("sort_by"),
                            sort_order=saved_view.get("sort_order"),
                        )
                        if saved_view
                        else None
                    )
                    sort_by = current_view.sort_by if current_view else (sort_by or "")
                    sort_order = (
                        current_view.sort_order if current_view else (sort_order or "")
                    )
                    # new_order_clause = (
                    #    f"{sort_by} {sort_order.upper()}"
                    #    if sort_by and sort_order
                    #    else None
                    # )
                    # updated_sql = replace_order_by(sql, new_order_clause)

                    # if updated_sql != sql:
                    #    # Persist new SQL with updated ORDER BY
                    #    session_response.metadata["sql"] = updated_sql
                    #    session_response.metadata["view"] = current_view
                    #    await update_query_metadata(
                    #        query_id,
                    #        session_response.user,
                    #        session_response.metadata,
                    #        db,
                    #    )
                    #    sql = updated_sql  # use the new version

            else:
                raise HTTPException(status_code=404, detail="Query not found")

    if not sql:
        raise HTTPException(status_code=400, detail="Query has no SQL attached")

    # Step 3: Execute count and main query
    # count_sql = f"SELECT count(*) FROM ({sql}) AS subquery;"
    # query_sql = f"SELECT * FROM ({sql}) AS subquery LIMIT :limit OFFSET :offset"
    # combined_sql = f"""
    #    SELECT
    #        t.*,
    #        COUNT(*) OVER () AS total_count
    #    FROM ({sql}) AS t
    #    LIMIT :limit
    #    OFFSET :offset
    # """
    combined_sql = build_sorted_paginated_sql(
        sql,
        sort_by=sort_by,
        sort_order=sort_order,
        include_total_count=True,     # or False if you don't need it
    )
    # print('SQL', combined_sql)

    with wh_session() as session:
        try:
            result = session.execute(
                text(combined_sql),
                {
                    "limit": limit,
                    "offset": offset,
                },
            )
            rows = result.mappings().fetchall()

            if rows:
                total_count = rows[0]["total_count"]
            else:
                total_count = 0

            payload = GetDataResponse(
                query_id=query_id,
                limit=limit,
                offset=offset,
                rows=[{k: v for k, v in row.items() if k != "total_count"} for row in
                      rows],
                total_rows=total_count,
            )

            # Make a stable ETag
            etag = compute_etag({
                "query_id": str(query_id),
                "limit": limit,
                "offset": offset,
                "total_rows": total_count,
                # Fingerprint first/last row only to avoid huge hashes
                "rows_fp": hashlib.sha256(
                    json.dumps({
                        "first": payload.rows[0] if payload.rows else None,
                        "last": payload.rows[-1] if payload.rows else None,
                    }, sort_keys=True, default=str).encode()
                ).hexdigest(),
            })

            headers = {
                "ETag": etag,
                "Cache-Control": "public, max-age=0, s-maxage=600, stale-while-revalidate=1200",
                "Vary": "Authorization, Accept, Accept-Encoding",
            }

            return Response(
                content=payload.model_dump_json(),  # v1: payload.json()
                media_type="application/json",
                headers=headers,
            )

        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error executing query: {str(e)}"
            )


@api_router.get("/query/{query_id}")
async def get_query_data(
    query_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> GetQueryModel:
    query_response = await get_query_by_id(query_id=query_id, db=db)
    if not query_response:
        raise HTTPException(status_code=404, detail="Query not found")

    return query_response
