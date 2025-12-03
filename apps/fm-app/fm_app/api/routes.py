import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

# TODO: do we need these imports here?
import plotly.graph_objects as go
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import EventSourceResponse
from starlette import status

from fm_app.api.auth0 import VerifyGuestToken, VerifyToken
from fm_app.api.db_session import get_db, wh_engine
from fm_app.api.model import (
    AddLinkedRequestModel,
    AddRequestModel,
    ChartRequest,
    ChartStructuredRequest,
    ChartType,
    CreateQueryFromSqlModel,
    CreateSessionModel,
    DBType,
    FlowType,
    GetDataResponse,
    GetQueryModel,
    GetRequestModel,
    GetSessionModel,
    InteractiveRequestType,
    ModelType,
    PatchSessionModel,
    RequestStatus,
    UpdateRequestStatusModel,
    Version,
    View,
    WorkerRequest,
)
from fm_app.db.admin_db import get_all_requests_admin, get_all_sessions_admin
from fm_app.db.db import (
    add_new_session,
    add_request,
    delete_request_revert_session,
    get_all_requests,
    get_all_sessions,
    get_queries,
    get_query_by_id,
    get_request,
    get_request_by_id,
    get_session_by_id,
    update_request_status,
    update_review,
    update_session,
)
from fm_app.stopwatch import stopwatch
from fm_app.workers.worker import wrk_add_request

logger = logging.getLogger(__name__)

token_auth_scheme = HTTPBearer()
auth = VerifyToken()
guest_auth = VerifyGuestToken()
api_router = APIRouter()

# Directory to store images
IMAGE_DIR = "static/charts"
HTML_DIR = "static/charts/html"
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(HTML_DIR, exist_ok=True)


def serialize_value(value):
    """Convert non-JSON-serializable types to JSON-compatible formats."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    elif isinstance(value, Decimal):
        return float(value)
    elif value is None:
        return None
    else:
        return value


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
            return sql[: last.start()] + f"ORDER BY {new_order_by} " + sql[last.end() :]
        else:
            # Append new ORDER BY before trailing LIMIT/OFFSET/FETCH
            m = trailing_clause_pattern.search(sql)
            if m:
                return (
                    sql[: m.start()] + f" ORDER BY {new_order_by} " + sql[m.start() :]
                )
            else:
                return f"{sql} ORDER BY {new_order_by} "
    else:
        # Remove only the *last* ORDER BY (if any)
        matches = list(order_by_pattern.finditer(sql))
        if not matches:
            return sql
        last = matches[-1]
        return sql[: last.start()] + " " + sql[last.end() :]


# Trailing clauses we want to remove from the *inner* query:
# - final ORDER BY (up to LIMIT/OFFSET/FETCH or end)
# - trailing LIMIT/OFFSET/FETCH
# We’ll remove them conservatively from the very end, not touching CTEs/subqueries.
_ORDER_BY_TAIL_RE = re.compile(
    r"""            # from the last ORDER BY to end
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

# Accept bare identifiers or dotted (alias.column)
# We'll keep only the column piece for the outer query
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _strip_leading_comments(sql: str) -> str:
    """
    Strip leading SQL comments (both -- and /* */ style) from the query.
    Used for detecting if a query is a CTE.
    """
    lines = sql.strip().split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip empty lines and single-line comments
        if not stripped or stripped.startswith("--"):
            continue
        # If we hit a non-comment line, return from here
        if not stripped.startswith("/*"):
            return "\n".join(lines[i:])
        # Handle multi-line comments
        if "*/" in stripped:
            # Comment ends on this line, continue to next
            continue
        else:
            # Multi-line comment starts, need to find where it ends
            for j in range(i + 1, len(lines)):
                if "*/" in lines[j]:
                    return "\n".join(lines[j + 1 :])
            break
    return sql


def _strip_final_order_by_and_trailing(sql: str, is_cte: bool = False) -> str:
    s = sql.strip().rstrip(";")

    # Remove only the *last* ORDER BY at the tail
    matches = list(_ORDER_BY_TAIL_RE.finditer(s))
    if matches:
        last = matches[-1]
        s = s[: last.start()] + s[last.end() :]

    # Remove trailing LIMIT/OFFSET/FETCH from the remaining tail
    # The regex uses $ anchor so it only matches at the very end,
    # safe to use even for CTE queries (won't match LIMITs inside CTEs)
    m = _TRAILING_LIMIT_OFFSET_FETCH_RE.search(s)
    if m:
        s = s[: m.start()]

    return s.strip()


def _sanitize_sort_by(sort_by: Optional[str]) -> Optional[str]:
    if not sort_by:
        return None
    sb = sort_by.strip()
    # allow quoted accidental inputs like "token"
    is_quoted = (sb.startswith('"') and sb.endswith('"')) or (
        sb.startswith("`") and sb.endswith("`")
    )
    if is_quoted:
        sb = sb[1:-1].strip()
    if not _IDENTIFIER_RE.match(sb):
        return None
    # Use only the last segment (the final SELECT alias)
    return sb.split(".")[-1]


def validate_sort_column(
    sort_by: str,
    columns: Optional[list],
) -> tuple[bool, str]:
    """
    Validate sort_by against QueryMetadata columns.

    Args:
        sort_by: Column name to sort by
        columns: List of Column objects or dicts from QueryMetadata

    Returns:
        (is_valid, result_or_error)
        - If valid: (True, canonical_column_name)
        - If invalid: (False, error_message)
    """
    if not columns:
        return False, "Query metadata not available - cannot validate sort column"

    # Get valid column names from metadata (case-insensitive)
    # Handle both Column objects and dicts (from session metadata)
    valid_columns = {}
    for col in columns:
        column_name = None

        # Handle Column objects
        if hasattr(col, "column_name"):
            column_name = col.column_name
        # Handle dicts (from session metadata)
        elif isinstance(col, dict):
            column_name = col.get("column_name")

        if column_name:
            valid_columns[column_name.lower()] = column_name

    if not valid_columns:
        return False, "No columns found in query metadata"

    # Check if sort_by matches (case-insensitive)
    sort_by_lower = sort_by.lower()
    if sort_by_lower not in valid_columns:
        available = ", ".join(sorted(valid_columns.values()))
        return (
            False,
            f"Invalid sort column '{sort_by}'. Available columns: {available}",
        )

    # Return the canonical column name (from metadata)
    return True, valid_columns[sort_by_lower]


def _build_cte_pagination_postgres(
    body: str, sort_by: Optional[str], sort_order: str, include_total_count: bool
) -> tuple[str, str]:
    """
    PostgreSQL/MySQL: Support nested CTEs, can wrap WITH inside FROM.

    Returns (base_sql, order_by_prefix)
    """
    if include_total_count:
        base = f"""
            SELECT *, COUNT(*) OVER () AS total_count
            FROM (
            {body}
            ) AS __cte_wrapper
        """
        order_by_prefix = ""
    else:
        base = body
        order_by_prefix = ""

    return base, order_by_prefix


def _build_cte_pagination_clickhouse(
    body: str, sort_by: Optional[str], sort_order: str, include_total_count: bool
) -> tuple[str, str]:
    """
    ClickHouse/SQLite: Cannot have WITH inside FROM.
    Skip total_count for CTEs to maintain compatibility.

    Returns (base_sql, order_by_prefix)
    """
    # For ClickHouse, we cannot wrap CTE in FROM()
    # Skip total_count functionality for CTE queries
    base = body
    order_by_prefix = ""

    return base, order_by_prefix


def _build_regular_pagination(
    body: str, sort_by: Optional[str], sort_order: str, include_total_count: bool
) -> tuple[str, str]:
    """
    Standard subquery wrapping for non-CTE queries.
    Works across all SQL dialects.

    Returns (base_sql, order_by_prefix)
    """
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
    order_by_prefix = "t."

    return base, order_by_prefix


def build_sorted_paginated_sql_gen(
    user_sql: str,
    *,
    sort_by: Optional[str],
    sort_order: str,
    include_total_count: bool = False,
) -> str:
    """
    Build paginated SQL with optional sorting and total count.

    Handles CTE (WITH) queries specially based on database dialect:
    - PostgreSQL/MySQL: Supports nested CTEs, can add total_count
    - ClickHouse/SQLite: Cannot nest CTEs, skips total_count for CTEs
    - Regular queries: Standard subquery wrapping for all dialects

    Args:
        user_sql: Original SQL query
        sort_by: Column name to sort by (optional)
        sort_order: 'asc' or 'desc'
        include_total_count: Whether to add COUNT(*) OVER() for total rows

    Returns:
        Modified SQL with pagination, sorting, and optional total count
    """
    from fm_app.utils import get_cached_warehouse_dialect

    # Check if query is a CTE before stripping
    # Strip leading comments first to properly detect CTEs
    user_sql_no_comments = _strip_leading_comments(user_sql)
    starts_with_cte = user_sql_no_comments.strip().upper().startswith("WITH")

    # Strip ORDER BY and optionally LIMIT/OFFSET
    # For CTE queries, we only strip final ORDER BY, not LIMIT
    # (to avoid matching LIMIT inside CTEs)
    body = _strip_final_order_by_and_trailing(user_sql, is_cte=starts_with_cte)

    if starts_with_cte:
        dialect = get_cached_warehouse_dialect()

        if dialect in ("postgres", "postgresql", "mysql"):
            base, order_by_prefix = _build_cte_pagination_postgres(
                body, sort_by, sort_order, include_total_count
            )
        else:
            # ClickHouse, SQLite, or unknown dialect
            # Use safe approach that works without nested CTEs
            base, order_by_prefix = _build_cte_pagination_clickhouse(
                body, sort_by, sort_order, include_total_count
            )
    else:
        # Regular query without CTE
        base, order_by_prefix = _build_regular_pagination(
            body, sort_by, sort_order, include_total_count
        )

    # Add sorting if requested
    col = _sanitize_sort_by(sort_by)
    if col:
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        base += f"\nORDER BY {order_by_prefix}{col} {direction}"

    # Add pagination
    base += "\nLIMIT :limit\nOFFSET :offset"

    return base


def build_sorted_paginated_sql(
    user_sql: str,
    *,
    sort_by: Optional[str],
    sort_order: str,
    include_total_count: bool = False,
    dialect: Optional[str] = None,
) -> str:
    """
    Build paginated SQL with sorting and optional total count.

    Handles dialect-specific quirks for ClickHouse, PostgreSQL, and Trino.

    Args:
        user_sql: The base SQL query
        sort_by: Column name to sort by (None for no sorting)
        sort_order: Sort direction ('asc' or 'desc')
        include_total_count: Whether to include total_count column
        dialect: Database dialect (auto-detected if None)

    Returns:
        SQL query string with pagination and sorting
    """
    from fm_app.utils.dialect import get_cached_warehouse_dialect

    # Strip trailing semicolon from input SQL (breaks Trino)
    user_sql = user_sql.strip().rstrip(";")

    # Auto-detect dialect if not provided
    if dialect is None:
        dialect = get_cached_warehouse_dialect()

    # Handle Trino case-sensitive column names
    if sort_by:
        if dialect == "trino":
            # Quote column name for case-sensitivity in Trino
            # Escape any existing quotes by doubling them
            sort_by_quoted = f'"{sort_by.replace('"', '""')}"'
            order_clause = f"\n        ORDER BY {sort_by_quoted} {sort_order}"
        else:
            # ClickHouse, Postgres, etc. - no quoting needed
            order_clause = f"\n        ORDER BY {sort_by} {sort_order}"
    else:
        # IMPORTANT: For Trino, pagination without ORDER BY is non-deterministic
        # Add a default ORDER BY for stability
        if dialect == "trino":
            order_clause = "\n        ORDER BY 1 ASC"
        else:
            order_clause = ""

    # Optimize COUNT query for Trino (avoid window function overhead)
    if include_total_count:
        if dialect == "trino":
            # Trino: Use scalar subquery for count to avoid double execution
            # Window function with OVER() can cause the CTE to execute twice
            return f"""
        SELECT
          t.*,
          (SELECT COUNT(*) FROM ({user_sql}) AS count_subquery) AS total_count
        FROM ({user_sql}) AS t
        {order_clause}
        OFFSET :offset LIMIT :limit
        """
        else:
            # ClickHouse/Postgres: Window function is efficient
            # CTE is materialized in ClickHouse, so COUNT(*) OVER() is fast
            return f"""
        WITH orig_sql AS (
          {user_sql}
        )
        SELECT
          t.*,
          COUNT(*) OVER () AS total_count
        FROM orig_sql AS t
        {order_clause}
        LIMIT :limit OFFSET :offset
        """
    else:
        # Simple pagination without count
        if dialect == "trino":
            return f"""
            SELECT
            t.*
            FROM ({user_sql}) AS t
            {order_clause}
            OFFSET :offset LIMIT :limit
            """
        else:
            return f"""
            SELECT
            t.*
            FROM ({user_sql}) AS t
            {order_clause}
            LIMIT :limit OFFSET :offset
            """


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

    # Deterministic command parsing
    # Check if the request starts with a slash command
    request_text = user_request.request.strip()
    if request_text.startswith("/"):
        command = request_text.split()[0].lower() if request_text else ""

        # Map commands to request types
        if command in ["/help", "/new"]:
            # Override request_type to discovery
            user_request.request_type = InteractiveRequestType.discovery
            # Keep the original request text so LLM can see the command context

    (response, task_id) = await add_request(
        user_owner=user_owner, session_id=session_id, add_req=user_request, db=db
    )

    stopwatch.reset()

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
            request=query.summary or query.intent or "Starting from existing query",
            request_type=InteractiveRequestType.linked_query,
            flow=FlowType.interactive,
            model=(
                query.ai_context.get("model")
                if query.ai_context is not None
                else ModelType.openai_default
            ),
            db=DBType.v2,
            refs=None,
            query_id=query_id,  # link to the query
        ),
        db=db,
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
            query.ai_context.get("model")
            if query.ai_context is not None
            else ModelType.openai_default
        ),
        db=DBType.v2,
        refs=None,
        query=query,
    )

    wrk_arg = wrk_req.model_dump()
    task = wrk_add_request.apply_async(args=[wrk_arg], task_id=task_id)
    logging.info(
        "Send task for request from query",
        extra={"action": "send_task", "task_id": task, "query_id": query_id},
    )

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
            request=f"Generate query from SQL: {query_data.sql}",  # query.request,
            request_type=InteractiveRequestType.manual_query,
            flow=FlowType.interactive,
            model=(
                query_data.ai_context.get("model")
                if query_data.ai_context is not None
                else ModelType.openai_default
            ),
            db=DBType.v2,
            refs=None,
            query_id=None,  # link to the query
        ),
        db=db,
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
            query_data.ai_context.get("model")
            if query_data.ai_context is not None
            else ModelType.openai_default
        ),
        db=DBType.v2,
        refs=None,
        query=None,
    )

    wrk_arg = wrk_req.model_dump()
    task = wrk_add_request.apply_async(args=[wrk_arg], task_id=task_id)
    logging.info(
        "Send task for request from SQL",
        extra={"action": "send_task", "task_id": task, "sql": query_data.sql},
    )

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
    """Delete a request and revert the session to the state
    before this request was added."""
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
    sql = ""
    current_view = View(sort_by=sort_by, sort_order=sort_order) if sort_by else None

    # Step 1: Fetch SQL from QueryMetadata store
    query_response = await get_query_by_id(query_id=query_id, db=db)
    if query_response:
        sql = query_response.sql if query_response.sql else ""
        sql = sql.strip().rstrip(";")

        # Validate sort_by against QueryMetadata columns
        if sort_by:
            is_valid, result = validate_sort_column(sort_by, query_response.columns)
            if not is_valid:
                raise HTTPException(status_code=400, detail=result)
            # Use canonical column name from metadata
            sort_by = result

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

                # Validate sort_by against QueryMetadata columns
                if sort_by:
                    is_valid, result = validate_sort_column(
                        sort_by, request_response.query.columns
                    )
                    if not is_valid:
                        raise HTTPException(status_code=400, detail=result)
                    # Use canonical column name from metadata
                    sort_by = result

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

                # Get columns from session metadata for validation
                columns = session_response.metadata.get("columns", [])

                # Get saved view if no sort provided by user
                saved_view = session_response.metadata.get("view")
                if not sort_by and saved_view:
                    # Use saved view if user didn't provide sort_by
                    current_view = View(
                        sort_by=saved_view.get("sort_by"),
                        sort_order=saved_view.get("sort_order"),
                    )
                    sort_by = saved_view.get("sort_by")
                    sort_order = saved_view.get("sort_order", "asc")

                # Validate sort_by (whether from user or saved view)
                if sort_by:
                    is_valid, result = validate_sort_column(sort_by, columns)
                    if not is_valid:
                        raise HTTPException(status_code=400, detail=result)
                    # Use canonical column name from metadata
                    sort_by = result
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
        include_total_count=True,  # or False if you don't need it
    )
    # print('SQL', combined_sql)

    # Use engine.connect() directly like db-meta (more reliable for PostgreSQL)
    with wh_engine.connect() as conn:
        try:
            result = conn.execute(
                text(combined_sql),
                {
                    "limit": limit,
                    "offset": offset,
                },
            )
            # Manual dict conversion (avoid .mappings() which can fail on connection drops)
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            # Extract total_count if present
            # (may not be present for ClickHouse CTE queries)
            # Handle case-insensitive column name for Trino
            if rows:
                total_count = None
                for k in rows[0].keys():
                    if k.lower() == "total_count":
                        total_count = rows[0].get(k, 0)
                        break
                if total_count is None:
                    total_count = 0
            else:
                total_count = 0

            payload = GetDataResponse(
                query_id=query_id,
                limit=limit,
                offset=offset,
                rows=[
                    {
                        k: serialize_value(v)
                        for k, v in row.items()
                        if k.lower() != "total_count"
                    }
                    for row in rows
                ],
                total_rows=total_count,
            )

            # Make a stable ETag
            etag = compute_etag(
                {
                    "query_id": str(query_id),
                    "limit": limit,
                    "offset": offset,
                    "total_rows": total_count,
                    # Fingerprint first/last row only to avoid huge hashes
                    "rows_fp": hashlib.sha256(
                        json.dumps(
                            {
                                "first": payload.rows[0] if payload.rows else None,
                                "last": payload.rows[-1] if payload.rows else None,
                            },
                            sort_keys=True,
                            default=str,
                        ).encode()
                    ).hexdigest(),
                }
            )

            headers = {
                "ETag": etag,
                "Cache-Control": (
                    "public, max-age=0, s-maxage=600, stale-while-revalidate=1200"
                ),
                "Vary": "Authorization, Accept, Accept-Encoding",
            }

            return Response(
                content=payload.model_dump_json(),  # v1: payload.json()
                media_type="application/json",
                headers=headers,
            )

        except Exception as err:
            error_msg = str(err)
            error_lower = error_msg.lower()

            # Provide better error messages for common issues
            if "unknown column" in error_lower or (
                "column" in error_lower and "not found" in error_lower
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Column error: {error_msg}. "
                    "This may indicate a mismatch between query and sort column.",
                )
            elif "syntax error" in error_lower:
                raise HTTPException(
                    status_code=500,
                    detail=f"SQL syntax error: {error_msg}",
                )
            elif "timeout" in error_lower or "timed out" in error_lower:
                raise HTTPException(
                    status_code=504,
                    detail=f"Query timeout: {error_msg}",
                )
            else:
                # Generic error
                raise HTTPException(
                    status_code=500, detail=f"Error executing query: {error_msg}"
                )


@api_router.get("/data/sse/{query_id}")
async def stream_data_fetch(
    query_id: UUID,
    request: Request,
    limit: int = 100,
    offset: int = 0,
    sort_by: Optional[str] = None,
    sort_order: str = Query("asc", regex="^(asc|desc)$"),
    notify_on_complete: bool = Query(False),
    user_email: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_result: dict = Depends(verify_any_token),
):
    """
    SSE endpoint for async data fetching.

    Flow:
    1. Validates query and auth
    2. Launches Celery task for data fetching
    3. Streams progress events to client
    4. Returns final data when ready
    """
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    logger.info(
        f"SSE data fetch request for query {query_id}",
        extra={
            "query_id": str(query_id),
            "notify_on_complete": notify_on_complete,
            "has_email": bool(user_email),
            "user_email_provided": user_email is not None,
        },
    )

    # TODO: temp return empty response !!!
    # raise HTTPException(status_code=204, detail="No content")

    # Get SQL from query metadata
    # Note: query_id parameter can be query_id, request_id, or session_id
    # for backward compatibility. We extract the actual query_id to use throughout
    sql = ""
    actual_query_id = None

    query_response = await get_query_by_id(query_id=query_id, db=db)
    if query_response:
        sql = query_response.sql if query_response.sql else ""
        sql = sql.strip().rstrip(";")
        actual_query_id = query_response.query_id

        # Validate sort_by
        if sort_by:
            is_valid, result = validate_sort_column(sort_by, query_response.columns)
            if not is_valid:
                raise HTTPException(status_code=400, detail=result)
            sort_by = result
    else:
        # Try request
        request_response = await get_request_by_id(
            request_id=query_id, db=db, user_owner=""
        )
        if request_response and request_response.query:
            sql = request_response.query.sql if request_response.query.sql else ""
            sql = sql.strip().rstrip(";")
            actual_query_id = request_response.query.query_id
            if sort_by:
                is_valid, result = validate_sort_column(
                    sort_by, request_response.query.columns
                )
                if not is_valid:
                    raise HTTPException(status_code=400, detail=result)
                sort_by = result
        else:
            # Try session
            session_response = await get_session_by_id(session_id=query_id, db=db)
            if session_response and session_response.metadata:
                sql = session_response.metadata.get("sql", "").strip().rstrip(";")
                columns = session_response.metadata.get("columns", [])
                if sort_by:
                    is_valid, result = validate_sort_column(sort_by, columns)
                    if not is_valid:
                        raise HTTPException(status_code=400, detail=result)
                    sort_by = result
                # Session doesn't have a query_id
                # (shouldn't be used for notifications)
                actual_query_id = None
            else:
                raise HTTPException(status_code=404, detail="Query not found")

    if not sql:
        raise HTTPException(status_code=400, detail="Query has no SQL attached")

    # Use actual_query_id for tracking and notifications
    # (fallback to input for backward compat)
    tracking_id = str(actual_query_id) if actual_query_id else str(query_id)

    # Check if there's already a running task for this query
    from fm_app.cache.task_tracker import (
        add_task_subscriber,
        get_running_task,
        set_running_task,
    )
    from fm_app.workers.worker import wrk_fetch_data

    running_task_info = await get_running_task(tracking_id)

    if running_task_info:
        # Task already running - reconnect to it and add this user as subscriber
        task_id = running_task_info["task_id"]
        task = wrk_fetch_data.AsyncResult(task_id)
        is_reconnecting = True

        # Add this user as a subscriber
        await add_task_subscriber(tracking_id, user_email, notify_on_complete)

        logger.info(f"Reconnecting to existing task {task_id} for query {tracking_id}")
    else:
        is_reconnecting = False
        # Launch new Celery task
        task_args = {
            "query_id": tracking_id,
            "sql": sql,
            "limit": limit,
            "offset": offset,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "notify_on_complete": notify_on_complete,
            "user_email": user_email,
        }

        task = wrk_fetch_data.apply_async(args=[task_args])
        task_id = task.id

        # Store task info in Redis with initial subscriber
        await set_running_task(tracking_id, task_id, notify_on_complete, user_email)
        logger.info(
            f"Started new task {task_id} for query {tracking_id}",
            extra={
                "task_id": task_id,
                "query_id": tracking_id,
                "notify_on_complete": notify_on_complete,
                "has_email": bool(user_email),
            },
        )

    async def event_generator():
        """Stream task progress via SSE."""
        import time

        try:
            if is_reconnecting:
                yield {
                    "event": "reconnected",
                    "data": json.dumps(
                        {
                            "task_id": task_id,
                            "query_id": str(query_id),
                            "status": "reconnected",
                            "message": "Reconnected to running query",
                        }
                    ),
                }
            else:
                yield {
                    "event": "started",
                    "data": json.dumps(
                        {
                            "task_id": task_id,
                            "query_id": str(query_id),
                            "status": "started",
                        }
                    ),
                }

            # Poll task status
            max_wait = 300  # 5 minutes max
            start_time = time.time()
            poll_interval = 0.5  # Poll every 500ms
            count_sent = False  # Track if count event was sent
            busy_warning_sent = False  # Track if busy warning was sent
            busy_warning_threshold = 5  # Warn if task pending for 5 seconds

            while time.time() - start_time < max_wait:
                # Check if client disconnected
                if await request.is_disconnected():
                    # Cancel the task if client disconnected
                    task.revoke(terminate=True)
                    break

                # Check task status
                result = task

                # Check if task is stuck in PENDING (workers busy)
                if (
                    result.state == "PENDING"
                    and not busy_warning_sent
                    and time.time() - start_time > busy_warning_threshold
                ):
                    yield {
                        "event": "workers_busy",
                        "data": json.dumps(
                            {
                                "status": "workers_busy",
                                "message": (
                                    "All workers are currently busy. "
                                    "Your query is queued and will start shortly."
                                ),
                            }
                        ),
                    }
                    busy_warning_sent = True

                # Check for counting complete state (only send once)
                if result.state == "COUNTING_COMPLETE" and not count_sent:
                    meta = result.info
                    yield {
                        "event": "count",
                        "data": json.dumps(
                            {
                                "status": "counting_complete",
                                "query_id": meta.get("query_id"),
                                "total_rows": meta.get("total_rows"),
                            }
                        ),
                    }
                    count_sent = True

                if result.ready():
                    # Task completed
                    task_result = result.get()

                    if task_result.get("status") == "success":
                        yield {
                            "event": "data",
                            "data": json.dumps(
                                {
                                    "status": "success",
                                    "query_id": task_result.get("query_id"),
                                    "rows": task_result.get("rows"),
                                    "total_rows": task_result.get("total_rows"),
                                    "limit": task_result.get("limit"),
                                    "offset": task_result.get("offset"),
                                }
                            ),
                        }
                    else:
                        yield {
                            "event": "error",
                            "data": json.dumps(
                                {
                                    "status": "error",
                                    "error": task_result.get("error", "Unknown error"),
                                }
                            ),
                        }
                    break

                # Still running - send progress update
                yield {
                    "event": "progress",
                    "data": json.dumps(
                        {"status": "running", "elapsed": int(time.time() - start_time)}
                    ),
                }

                await asyncio.sleep(poll_interval)
            else:
                # Timeout
                task.revoke(terminate=True)
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"status": "error", "error": "Query execution timeout"}
                    ),
                }
        except GeneratorExit:
            # Client disconnected - revoke the task
            task.revoke(terminate=True)
            logger.info(f"Client disconnected, task {task_id} revoked")
        except Exception as e:
            # Unexpected error - revoke the task
            task.revoke(terminate=True)
            logger.error(f"Error in SSE stream: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"status": "error", "error": str(e)}),
            }

    return EventSourceResponse(event_generator())


@api_router.delete("/data/{query_id}")
async def cancel_data_fetch(
    query_id: UUID,
    auth_result: dict = Depends(verify_any_token),
):
    """
    Cancel or unsubscribe from a running data fetch.

    Behavior:
    - If user is the only subscriber → cancel the Celery task entirely
    - If other users are subscribed → just unsubscribe this user (task continues)

    Returns:
        - status: "cancelled" if task was terminated
        - status: "unsubscribed" if user was removed but task continues
        - status: "not_found" if no running task exists
    """
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    # Get user email from auth result (for subscriber tracking)
    user_email = auth_result.get("email") or auth_result.get(
        "https://semantic-grid.com/email"
    )

    from fm_app.cache.task_tracker import (
        clear_running_task,
        get_running_task,
        remove_task_subscriber,
    )
    from fm_app.workers.worker import wrk_fetch_data

    tracking_id = str(query_id)
    running_task_info = await get_running_task(tracking_id)

    if not running_task_info:
        logger.info(f"No running task found for query {tracking_id}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "not_found",
                "message": "No running task found for this query",
                "query_id": tracking_id,
            },
        )

    task_id = running_task_info["task_id"]
    subscribers = running_task_info.get("subscribers", [])

    # Check if this user is the only subscriber
    user_is_only_subscriber = len(subscribers) <= 1 and (
        not subscribers or subscribers[0].get("user_email") == user_email
    )

    if user_is_only_subscriber or not user_email:
        # Cancel the entire task
        task = wrk_fetch_data.AsyncResult(task_id)
        task.revoke(terminate=True)
        await clear_running_task(tracking_id)

        logger.info(
            f"Cancelled task {task_id} for query {tracking_id}",
            extra={
                "task_id": task_id,
                "query_id": tracking_id,
                "user": user_owner,
            },
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "cancelled",
                "message": "Fetch cancelled",
                "query_id": tracking_id,
            },
        )
    else:
        # Just unsubscribe this user
        removed, remaining = await remove_task_subscriber(tracking_id, user_email)

        logger.info(
            f"Unsubscribed user from query {tracking_id}",
            extra={
                "query_id": tracking_id,
                "user_email": user_email,
                "remaining_subscribers": remaining,
            },
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "unsubscribed",
                "message": "Unsubscribed from shared fetch",
                "query_id": tracking_id,
                "remaining_subscribers": remaining,
            },
        )


class UpdateNotificationRequest(BaseModel):
    """Request body for updating notification settings."""

    notify: bool
    user_email: Optional[str] = None


@api_router.patch("/data/{query_id}")
async def update_data_fetch_notification(
    query_id: UUID,
    update_request: UpdateNotificationRequest,
    auth_result: dict = Depends(verify_any_token),
):
    """
    Update notification settings for a running data fetch.

    Allows users to add or remove email notification for when the fetch completes.

    Request body:
        - notify: bool - Whether to send notification on complete
        - user_email: str (optional) - Email for notification
          (uses auth email if not provided)

    Returns:
        - status: "updated" if notification setting was updated
        - status: "not_found" if no running task exists
    """
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    # Get user email from request or auth result
    user_email = (
        update_request.user_email
        or auth_result.get("email")
        or auth_result.get("https://semantic-grid.com/email")
    )

    if not user_email and update_request.notify:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email required for notifications",
        )

    from fm_app.cache.task_tracker import (
        get_running_task,
        update_subscriber_notification,
    )

    tracking_id = str(query_id)
    running_task_info = await get_running_task(tracking_id)

    if not running_task_info:
        logger.info(f"No running task found for query {tracking_id}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "not_found",
                "message": "No running task found for this query",
                "query_id": tracking_id,
            },
        )

    # Update notification preference
    success = await update_subscriber_notification(
        tracking_id, user_email, update_request.notify
    )

    if success:
        logger.info(
            f"Updated notification for query {tracking_id}",
            extra={
                "query_id": tracking_id,
                "user_email": user_email,
                "notify": update_request.notify,
            },
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "updated",
                "notify": update_request.notify,
                "user_email": user_email,
                "query_id": tracking_id,
            },
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update notification settings",
        )


@api_router.get("/query/{query_id}")
async def get_query_metadata(
    query_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> GetQueryModel:
    query_response = await get_query_by_id(query_id=query_id, db=db)
    if not query_response:
        raise HTTPException(status_code=404, detail="Query not found")

    return query_response


@api_router.get("/sse/{session_id}")
async def stream_request_updates(
    session_id: UUID,
    request: Request,
    auth_result: dict = Depends(verify_any_token),
):
    """
    Server-Sent Events endpoint for real-time request status updates.

    Listens to PostgreSQL NOTIFY events on the 'request_update' channel
    and streams updates for the specified session to connected clients.

    The trigger sends notifications with this payload:
    {
        "request_id": "uuid",
        "session_id": "uuid",
        "status": "status_enum",
        "updated_at": timestamp,
        "has_response": bool,
        "has_error": bool,
        "sequence_number": int
    }
    """
    user_owner = auth_result.get("sub")
    if user_owner is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No user name"
        )

    # Convert UUID to string for comparison
    session_id_str = str(session_id)

    from fm_app.config import get_settings

    settings = get_settings()

    # Build PostgreSQL connection URL for asyncpg (non-SQLAlchemy)
    db_url = (
        f"postgresql://{settings.database_user}:{settings.database_pass}"
        f"@{settings.database_server}:{settings.database_port}/{settings.database_db}"
    )

    async def event_generator():
        """Generate SSE events from PostgreSQL notifications."""
        conn = None
        notify_queue = asyncio.Queue()

        def notification_callback(connection, pid, channel, payload):
            """Callback for PostgreSQL notifications."""
            # Put notification into queue for async processing
            notify_queue.put_nowait(payload)

        try:
            # Create asyncpg connection for LISTEN
            conn = await asyncpg.connect(db_url)

            # Add listener with callback that puts notifications in queue
            await conn.add_listener("request_update", notification_callback)

            logging.info(
                "SSE connection established",
                extra={
                    "action": "sse_connect",
                    "session_id": session_id_str,
                    "user": user_owner,
                },
            )

            # Send initial connection event
            yield {
                "event": "connected",
                "data": json.dumps(
                    {
                        "session_id": session_id_str,
                        "timestamp": asyncio.get_event_loop().time(),
                    }
                ),
            }

            # Listen for notifications
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    logging.info(
                        "SSE client disconnected",
                        extra={
                            "action": "sse_disconnect",
                            "session_id": session_id_str,
                            "user": user_owner,
                        },
                    )
                    break

                # Wait for notification with timeout
                try:
                    # Get notification from queue with timeout
                    # to check for disconnections periodically
                    payload_str = await asyncio.wait_for(
                        notify_queue.get(),
                        timeout=5.0,  # Check for disconnections every 5 seconds
                    )

                    # Parse the notification payload
                    payload = json.loads(payload_str)

                    # Filter: only send notifications for this session
                    if payload.get("session_id") == session_id_str:
                        logging.debug(
                            "SSE notification sent",
                            extra={
                                "action": "sse_notify",
                                "session_id": session_id_str,
                                "request_id": payload.get("request_id"),
                                "status": payload.get("status"),
                            },
                        )

                        # Send as SSE event
                        yield {"event": "request_update", "data": json.dumps(payload)}

                except asyncio.TimeoutError:
                    # No notification received, send keep-alive comment
                    # SSE spec: lines starting with ':' are comments (keep-alive)
                    yield {"comment": "keep-alive"}
                    continue

        except asyncio.CancelledError:
            logging.info(
                "SSE connection cancelled",
                extra={
                    "action": "sse_cancel",
                    "session_id": session_id_str,
                },
            )
            raise

        except Exception as e:
            logging.error(
                "SSE error",
                extra={
                    "action": "sse_error",
                    "session_id": session_id_str,
                    "error": str(e),
                },
            )
            # Send error event to client
            yield {
                "event": "error",
                "data": json.dumps(
                    {"error": "Internal server error", "session_id": session_id_str}
                ),
            }

        finally:
            # Clean up: stop listening and close connection
            if conn is not None:
                try:
                    await conn.remove_listener("request_update", notification_callback)
                    await conn.close()
                    logging.info(
                        "SSE connection closed",
                        extra={
                            "action": "sse_close",
                            "session_id": session_id_str,
                        },
                    )
                except Exception as e:
                    logging.error(
                        "Error closing SSE connection",
                        extra={
                            "action": "sse_close_error",
                            "error": str(e),
                        },
                    )

    return EventSourceResponse(event_generator())
