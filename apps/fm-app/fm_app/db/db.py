import csv
import json
from io import StringIO
from typing import Any, Optional
from uuid import UUID, uuid4

from clickhouse_driver import Client
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from uuid_extensions import uuid7

from fm_app.api.model import (
    AddRequestModel,
    CreateQueryModel,
    CreateSessionModel,
    GetQueryModel,
    GetRequestModel,
    GetSessionModel,
    PatchSessionModel,
    RequestStatus,
    UpdateQueryModel,
    UpdateRequestModel,
)


async def add_new_session(
    session: CreateSessionModel, user_owner: str, db: AsyncSession
) -> GetSessionModel:
    logging.debug(
        "Adding new session for user",
        extra={"user_owner": user_owner, "action": "db::add_session"},
    )
    session_id = uuid7()
    add_session_sql = text(
        """
    INSERT INTO session (name, tags, user_owner, session_id, parent, refs)
    VALUES (:name, :tags, :user_owner, :session_id, :parent, :refs) 
    RETURNING session_id, name, tags, user_owner as "user", created_at, parent, refs;
    """
    )
    res = await db.execute(
        add_session_sql,
        params={
            "name": session.name,
            "tags": session.tags,
            "user_owner": user_owner,
            "session_id": session_id,
            "parent": session.parent,
            "refs": (
                json.dumps(session.refs.model_dump(), default=str)
                if session.refs
                else None
            ),
        },
    )
    data = res.mappings().fetchone()
    await db.commit()
    try:
        result = GetSessionModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Session object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def get_session_by_id(session_id: UUID, db: AsyncSession) -> GetSessionModel:
    logging.debug(
        "Get session for user",
        extra={"action": "db::get_session", "id": session_id},
    )
    get_session_sql = text(
        """
        SELECT session_id, name, tags, user_owner AS "user", created_at, metadata, refs, parent
        FROM session
        WHERE session_id = :session_id;
        """
    )
    res = await db.execute(get_session_sql, params={"session_id": session_id})
    data = res.mappings().fetchone()
    try:
        result = GetSessionModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Session object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def get_all_sessions(user_owner: str, db: AsyncSession) -> list[GetSessionModel]:
    logging.debug(
        "Get all sessions for user",
        extra={"user_owner": user_owner, "action": "db::get_all_sessions"},
    )
    get_all_session_sql = text(
        """
    SELECT 
        s.session_id, 
        s.name, tags, 
        s.user_owner as "user", 
        s.created_at, 
        s.metadata, 
        s.refs, 
        s.parent,
        COUNT(r.id) AS message_count
    FROM session s
    LEFT JOIN 
         request r 
         ON s.session_id = r.session_id
    WHERE 
        s.user_owner = :user_owner
    GROUP BY 
        s.session_id, 
        s.name, 
        s.tags, 
        s.user_owner, 
        s.created_at, 
        s.metadata, 
        s.refs, 
        s.parent
    ;
    """
    )
    res = await db.execute(get_all_session_sql, params={"user_owner": user_owner})
    data = res.mappings().fetchall()
    result = []
    for s in data:
        try:
            result.append(GetSessionModel.model_validate(s))

        except ValidationError as e:
            logging.error(f"Can't validate Session object from DB error: {e}")
            raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def update_session(
    session_id: UUID,
    user_owner: str,
    session_patch: PatchSessionModel,
    db: AsyncSession,
) -> GetSessionModel:
    logging.debug(
        "Update session",
        extra={
            "user_owner": user_owner,
            "action": "db::update_sessions",
            "session_id": session_id,
            "session_patch": session_patch,
        },
    )

    await check_session_ownership(session_id=session_id, user_owner=user_owner, db=db)
    update_session_sql = text(
        """
    UPDATE session SET
    name = :name, tags = :tags, updated_at = now()
    WHERE user_owner = :user_owner AND session_id = :session_id
    RETURNING session_id, name, tags, user_owner as "user", created_at, metadata, refs, parent;
    """
    )
    res = await db.execute(
        update_session_sql,
        params={
            "user_owner": user_owner,
            "session_id": session_id,
            "name": session_patch.name,
            "tags": session_patch.tags,
        },
    )
    data = res.mappings().fetchone()
    await db.commit()
    try:
        result = GetSessionModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Session object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def update_session_name(
    session_id: UUID, user_owner: str, name: str, db: AsyncSession
) -> GetSessionModel:
    logging.debug(
        "Update session",
        extra={
            "user_owner": user_owner,
            "action": "db::update_sessions",
            "session_id": session_id,
            "name": name,
        },
    )
    update_session_sql = text(
        """
        UPDATE session SET
        name = :name, updated_at = now()
        WHERE user_owner = :user_owner AND session_id = :session_id
        RETURNING session_id, name, tags, user_owner as "user", created_at, metadata, refs, parent;
    """
    )
    res = await db.execute(
        update_session_sql,
        params={"user_owner": user_owner, "session_id": session_id, "name": name},
    )
    data = res.mappings().fetchone()
    await db.commit()
    try:
        result = GetSessionModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Session object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def update_query_metadata(
    session_id: UUID, user_owner: str, metadata: dict[str, Any], db: AsyncSession
) -> GetSessionModel:
    logging.debug(
        "Update session memory",
        extra={
            "user_owner": user_owner,
            "action": "db::update_sessions",
            "session_id": session_id,
            "metadata": metadata,
        },
    )
    metadata_json = json.dumps(metadata, default=str)
    update_session_sql = text(
        """
        UPDATE session SET
        metadata = :metadata, updated_at = now()
        WHERE user_owner = :user_owner AND session_id = :session_id
        RETURNING session_id, metadata, name, tags, user_owner as "user", created_at, parent;
    """
    )
    res = await db.execute(
        update_session_sql,
        params={
            "user_owner": user_owner,
            "session_id": session_id,
            "metadata": metadata_json,
        },
    )
    data = res.mappings().fetchone()
    await db.commit()
    # print("data", data)
    try:
        result = GetSessionModel.model_validate(data)
    except ValidationError as e:
        logging.error(f"Can't validate Session object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def check_session_ownership(session_id: UUID, user_owner: str, db: AsyncSession):
    check_session_ownership_sql = text(
        """
    SELECT session_id FROM session
    WHERE user_owner = :user_owner
    AND session_id = :session_id;
    """
    )
    res = await db.execute(
        check_session_ownership_sql,
        params={"user_owner": user_owner, "session_id": session_id},
    )
    data = res.mappings().fetchall()
    if len(data) == 0:
        raise HTTPException(status_code=404, detail="Session not found")


async def add_request(
    session_id: UUID, user_owner: str, add_req: AddRequestModel, db: AsyncSession
) -> tuple[GetRequestModel, str]:
    logging.debug(
        "Add request",
        extra={
            "user_owner": user_owner,
            "action": "db::add_request",
            "session_id": session_id,
            "request": add_req,
        },
    )
    await check_session_ownership(session_id=session_id, user_owner=user_owner, db=db)

    request_id = uuid7()
    task_id = str(uuid7())
    status = RequestStatus.new if not add_req.query_id else RequestStatus.done
    refs_dict = add_req.refs.model_dump() if add_req.refs else None
    add_req_sql = text(
        """
        INSERT 
        INTO request (session_id, request_id, task_id, sequence_number, request, status, refs, query_id)
        VALUES (
            :session_id, 
            :request_id, 
            :task_id, 
            (SELECT COALESCE(MAX(sequence_number), -1) + 1 FROM request WHERE session_id = :session_id), 
            :request, 
            :status, 
            :refs,
            :query_id
        )
        RETURNING 
            session_id, 
            request_id, 
            sequence_number, 
            created_at, 
            request, 
            response, 
            status, 
            refs,
            query_id
        ;
    """
    )
    res = await db.execute(
        add_req_sql,
        params={
            "session_id": session_id,
            "request_id": request_id,
            "status": status,
            "task_id": task_id,
            "request": add_req.request,
            "refs": json.dumps(refs_dict) if refs_dict else None,
            "query_id": add_req.query_id if add_req.query_id else None,
        },
    )
    data = res.mappings().fetchone()
    await db.commit()
    try:
        result = GetRequestModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Request object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))
    return result, task_id


async def get_request(
    session_id: UUID, user_owner: str, seq_num: int, db: AsyncSession
) -> GetRequestModel:
    logging.debug(
        "Get request",
        extra={
            "user_owner": user_owner,
            "action": "db::get_request",
            "session_id": session_id,
            "request_num": seq_num,
        },
    )
    await check_session_ownership(session_id=session_id, user_owner=user_owner, db=db)
    get_req_sql = text(
        """
        SELECT
            request.*,
            query.query_id AS query__query_id,
            query.request AS query__request,
            query.sql AS query__sql,
            query.intent AS query__intent,
            query.summary AS query__summary,
            query.description AS query__description,
            query.explanation AS query__explanation,
            query.err AS query__err,
            query.created_at AS query__created_at,
            query.updated_at AS query__updated_at,
            query.row_count AS query__row_count,
            query.columns AS query__columns,
            query.ai_generated AS query__ai_generated,
            query.ai_context AS query__ai_context,
            query.data_source AS query__data_source,
            query.db_dialect AS query__db_dialect,
            query.parent_id AS query__parent_id
        FROM request
        LEFT JOIN query
          ON request.query_id IS NOT NULL AND request.query_id = query.query_id
        WHERE
            request.session_id = :session_id AND
            request.sequence_number = :seq_num;
    """
    )
    res = await db.execute(
        get_req_sql, params={"session_id": session_id, "seq_num": seq_num}
    )
    row = res.mappings().fetchone()

    # Flatten and nest 'query__*' into a 'query' subdict
    data = {}
    query_data = {}

    for key, value in row.items():
        if key.startswith("query__"):
            subkey = key[len("query__") :]
            query_data[subkey] = value
        else:
            data[key] = value

    # Assign nested query object if any of its fields are present
    data["query"] = (
        query_data if any(v is not None for v in query_data.values()) else None
    )

    try:
        result = GetRequestModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Request object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def get_request_by_id(
    request_id: UUID, user_owner: str, db: AsyncSession
) -> Optional[GetRequestModel]:
    logging.debug(
        "Get request",
        extra={
            "user_owner": user_owner,
            "action": "db::get_request",
            "request_id": request_id,
        },
    )
    # await check_session_ownership(session_id=session_id, user_owner=user_owner, db=db)
    get_req_sql = text(
        """
        SELECT
            request.*,
            query.query_id AS query__query_id,
            query.request AS query__request,
            query.sql AS query__sql,
            query.intent AS query__intent,
            query.summary AS query__summary,
            query.description AS query__description,
            query.explanation AS query__explanation,
            query.err AS query__err,
            query.created_at AS query__created_at,
            query.updated_at AS query__updated_at,
            query.row_count AS query__row_count,
            query.columns AS query__columns,
            query.ai_generated AS query__ai_generated,
            query.ai_context AS query__ai_context,
            query.data_source AS query__data_source,
            query.db_dialect AS query__db_dialect,
            query.parent_id AS query__parent_id
        FROM request
        LEFT JOIN query
          ON request.query_id IS NOT NULL AND request.query_id = query.query_id
        WHERE
            request.request_id = :request_id;
    """
    )
    res = await db.execute(get_req_sql, params={"request_id": request_id})
    row = res.mappings().fetchone()
    if not row:
        return None

    # Flatten and nest 'query__*' into a 'query' subdict
    data = {}
    query_data = {}

    for key, value in row.items():
        if key.startswith("query__"):
            subkey = key[len("query__") :]
            query_data[subkey] = value
        else:
            data[key] = value

    # Assign nested query object if any of its fields are present
    data["query"] = (
        query_data if any(v is not None for v in query_data.values()) else None
    )

    try:
        result = GetRequestModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Request object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))
    return result


async def get_schema(db: AsyncSession):
    get_schema_sql = text(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position;
        """
    )
    res = await db.execute(get_schema_sql)
    for row in res.fetchall():
        print(row)


async def get_all_requests(
    session_id: UUID, user_owner: str, db: AsyncSession
) -> list[GetRequestModel]:
    logging.debug(
        "Get all request",
        extra={
            "user_owner": user_owner,
            "action": "db::get_request",
            "session_id": session_id,
        },
    )
    # await get_schema(db=db)
    await check_session_ownership(session_id=session_id, user_owner=user_owner, db=db)
    get_req_sql = text(
        """
        SELECT
            request.*,
            query.query_id AS query__query_id,
            query.request AS query__request,
            query.sql AS query__sql,
            query.intent AS query__intent,
            query.summary AS query__summary,
            query.description AS query__description,
            query.explanation AS query__explanation,
            query.err AS query__err,
            query.created_at AS query__created_at,
            query.updated_at AS query__updated_at,
            query.row_count AS query__row_count,
            query.columns AS query__columns,
            query.ai_generated AS query__ai_generated,
            query.ai_context AS query__ai_context,
            query.data_source AS query__data_source,
            query.db_dialect AS query__db_dialect,
            query.parent_id AS query__parent_id
        FROM request
        LEFT JOIN query
          ON request.query_id IS NOT NULL AND request.query_id = query.query_id
        WHERE
            request.session_id = :session_id;
    """
    )
    res = await db.execute(get_req_sql, params={"session_id": session_id})
    data = res.mappings().fetchall()
    result = []
    for row in data:
        # Flatten and nest 'query__*' into a 'query' subdict
        data = {}
        query_data = {}

        for key, value in row.items():
            if key.startswith("query__"):
                subkey = key[len("query__") :]
                query_data[subkey] = value
            else:
                data[key] = value

        # Assign nested query object if any of its fields are present
        data["query"] = (
            query_data if any(v is not None for v in query_data.values()) else None
        )
        # print("row", data)
        try:
            result.append(GetRequestModel.model_validate(data))
        except ValidationError as e:
            logging.error(f"Can't validate Request object from DB error: {e}")
            raise HTTPException(status_code=500, detail=str("Internal error"))

    return result


async def update_request_failure(
    err: Optional[str],
    status: RequestStatus,
    db: AsyncSession,
    task_id: Optional[str] = None,
):
    try:
        update_sql = text(
            """
            UPDATE request 
            SET 
                err=:err, 
                status=:status 
            WHERE task_id=:task_id
        """
        )
        await db.execute(
            update_sql, params={"err": err, "status": status, "task_id": task_id}
        )
        # if result.mappings().fetchone().rowcount != 1:
        #    logging.error(
        #        f"SQL error update more than one request for task_id={task_id}"
        #    )
        #    return
        await db.commit()

    except SQLAlchemyError as e:
        logging.error(f"SQL execution error {e}")


async def update_request(db: AsyncSession, update: UpdateRequestModel):
    try:
        labels = json.dumps(update.raw_data_labels) if update.raw_data_labels else None
        rows = json.dumps(update.raw_data_rows) if update.raw_data_rows else None
        refs_json = json.dumps(update.refs) if update.refs else None
        view_json = update.view.model_dump_json() if update.view else None

        update_sql = text(
            """
            UPDATE request 
            SET 
                status=COALESCE(:status, status),
                response=COALESCE(:response, response),
                err=COALESCE(:err, err),
                sql=COALESCE(:sql, sql),
                intent=COALESCE(:intent, intent),
                assumptions=COALESCE(:assumptions, assumptions),
                intro=COALESCE(:intro, intro),
                outro=COALESCE(:outro, outro),
                raw_data_labels=COALESCE(:raw_data_labels, raw_data_labels),
                raw_data_rows=COALESCE(:raw_data_rows, raw_data_rows),
                csv=COALESCE(:csv, csv),
                chart=COALESCE(:chart, chart),
                chart_url=COALESCE(:chart_url, chart_url),
                refs=COALESCE(:refs, refs),
                linked_session_id=COALESCE(:linked_session_id, linked_session_id),
                updated_at = now(),
                query_id = COALESCE(:query_id, query_id),
                view = COALESCE(:view_json, view)
            WHERE request_id=:request_id
        """
        )
        await db.execute(
            update_sql,
            params={
                "status": update.status,
                "response": update.response,
                "err": update.err,
                "sql": update.sql,
                "intent": update.intent,
                "assumptions": update.assumptions,
                "intro": update.intro,
                "outro": update.outro,
                "raw_data_labels": labels,
                "raw_data_rows": rows,
                "csv": update.csv,
                "chart": update.chart,
                "chart_url": update.chart_url,
                "request_id": update.request_id,
                "refs": refs_json,
                "linked_session_id": update.linked_session_id,
                "query_id": update.query_id,
                "view_json": view_json,
            },
        )

        # if result.mappings().fetchone().rowcount != 1:
        #    logging.error(
        #        f"SQL error update more than one request for request_id={request_id}"
        #    )
        #    return
        await db.commit()

    except SQLAlchemyError as e:
        logging.error(f"SQL execution error {e}")


async def update_request_status(
    status: RequestStatus,
    err: Optional[str],
    db: AsyncSession,
    request_id: Optional[UUID] = None,
) -> Optional[GetRequestModel]:
    try:
        update_sql = text(
            """
            UPDATE request 
            SET err=:err, status=:status 
            WHERE request_id=:request_id
            RETURNING *;    
        """
        )
        result = await db.execute(
            update_sql, params={"request_id": request_id, "status": status, "err": err}
        )

        row = result.mappings().fetchone()
        if not row:
            logging.error(f"No rows updated for request_id={request_id}")
            return None
        await db.commit()
        return GetRequestModel.model_validate(row)

    except SQLAlchemyError as e:
        logging.error(f"SQL execution error {e}")


async def update_review(
    rating: int, review: str, db: AsyncSession, request_id: UUID, user_owner: str
):
    try:
        update_sql = text(
            """
            UPDATE request 
            SET rating=:rating, review=:review 
            WHERE request_id=:request_id
            RETURNING *;
        """
        )
        result = await db.execute(
            update_sql,
            params={"rating": rating, "review": review, "request_id": request_id},
        )
        row = result.mappings().fetchone()
        if not row:
            logging.error(f"No rows updated for request_id={request_id}")
            return None
        await db.commit()
        return GetRequestModel.model_validate(row)

    except SQLAlchemyError as e:
        logging.error(f"SQL execution error {e}")


async def delete_request_revert_session(
    request_id: UUID, db: AsyncSession, user_owner: str
) -> Optional[UUID]:
    # step 1. load session by request_id
    # step 2. load previous request for this session (if exists)
    # step 3. if previous request exists, and has SQL, update session query metadata with it
    # step 4. delete request by request_id
    try:
        get_session_sql = text(
            """
            SELECT session_id FROM request WHERE request_id = :request_id;
        """
        )
        res = await db.execute(get_session_sql, params={"request_id": request_id})
        session_data = res.mappings().fetchone()
        if not session_data:
            logging.error(f"No session found for request_id={request_id}")
            return None
        session_id = session_data["session_id"]

        # step 2. load previous request for this session (if exists)
        get_prev_request_sql = text(
            """
            SELECT * FROM request 
            WHERE session_id = :session_id 
            AND sequence_number < (
                SELECT sequence_number FROM request WHERE request_id = :request_id
            )
            ORDER BY sequence_number DESC
            LIMIT 1;
        """
        )
        res = await db.execute(
            get_prev_request_sql,
            params={"session_id": session_id, "request_id": request_id},
        )
        prev_request_data = res.mappings().fetchone()

        # step 3. if previous request exists, and has SQL, update session query metadata with it
        if prev_request_data and prev_request_data.get("sql"):
            update_session_sql = text(
                """
                UPDATE session SET metadata = jsonb_set(metadata, '{sql}', :query) 
                WHERE session_id = :session_id;
            """
            )
            await db.execute(
                update_session_sql,
                params={
                    "session_id": session_id,
                    "query": prev_request_data.get("sql"),
                },
            )

        # step 4. delete request by request_id
        delete_request_sql = text(
            """
            DELETE FROM request WHERE request_id = :request_id;
        """
        )
        await db.execute(delete_request_sql, params={"request_id": request_id})
        await db.commit()
        return session_id

    except SQLAlchemyError as e:
        logging.error(f"SQL execution error {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def run_wh_request(request: str, db: Session):
    # try:
    result = db.execute(text(request))
    data = result.mappings().fetchall()
    rows = [dict(row) for row in data]
    if len(rows) == 0:
        return None
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

    csv_result = output.getvalue()
    output.close()
    logging.debug("Produced CSV", extra={"action": "create_csv", "content": csv_result})
    return csv_result


# except SQLAlchemyError as e:
#     logging.error(f"SQL execution error {e}")


def run_structured_wh_request_dataframe(request: str, db: Session):
    # Extract from SQLAlchemy engine
    url = db.bind.url

    # Use clickhouse-driver directly
    client = Client(
        host=url.host,
        port=url.port or 9000,
        user=url.username,
        password=url.password,
        database=url.database,
        settings={
            "max_execution_time": 300,
            "max_bytes_before_external_group_by": 1_000_000_000,
            "max_bytes_before_external_sort": 1_000_000_000,
        },
    )

    rows, columns = client.execute(request, with_column_types=True)
    return rows, columns


def run_structured_wh_request_native(request: str, db: Session):
    # Extract from SQLAlchemy engine
    url = db.bind.url

    # Use clickhouse-driver directly
    client = Client(
        host=url.host,
        port=url.port or 9000,
        user=url.username,
        password=url.password,
        database=url.database,
        settings={
            "max_execution_time": 300,
            "max_bytes_before_external_group_by": 1_000_000_000,
            "max_bytes_before_external_sort": 1_000_000_000,
        },
    )

    rows, columns = client.execute(request, with_column_types=True)
    if not rows:
        return {"csv": None, "rows": 0}

    column_names = [name for name, _ in columns]
    if len(rows) > 1000:
        logging.error("Too many rows in result", extra={"rows": len(rows)})
        return {"csv": None, "rows": len(rows)}

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=column_names)
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(zip(column_names, row)))

    return {"csv": output.getvalue(), "rows": len(rows)}


def run_structured_wh_request_raw(request: str, db: Session):
    # Get raw ClickHouse driver connection from SQLAlchemy session
    raw_conn = db.connection().connection  # clickhouse_driver.Connection
    cursor = raw_conn.cursor()

    # Execute the query directly
    cursor.execute(request)

    # Fetch rows and column names
    rows = cursor.fetchall()
    if not rows:
        return {"csv": None, "rows": 0}

    column_names = [desc[0] for desc in cursor.description]
    if len(rows) > 1000:
        logging.error(
            "Too many rows in the result",
            extra={"action": "create_csv", "rows": len(rows)},
        )
        return {"csv": None, "rows": len(rows)}

    # Convert to CSV
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=column_names)
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(zip(column_names, row)))

    csv_result = output.getvalue()
    output.close()

    logging.debug("Produced CSV", extra={"action": "create_csv", "content": csv_result})
    return {"csv": csv_result, "rows": len(rows)}


def run_structured_wh_request(request: str, db: Session):
    # try:
    result = db.execute(text(request))
    data = result.mappings().fetchall()
    rows = [dict(row) for row in data]
    if len(rows) == 0:
        return {"csv": None, "rows": 0}
    if len(rows) > 1000:
        logging.error(
            "Too many rows in the result",
            extra={"action": "create_csv", "rows": len(rows)},
        )
        return {"csv": None, "rows": len(rows)}
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

    csv_result = output.getvalue()
    output.close()
    logging.debug("Produced CSV", extra={"action": "create_csv", "content": csv_result})
    return {"csv": csv_result, "rows": len(rows)}


import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def count_wh_request(request: str, db: Session) -> Optional[int]:
    try:
        # Strip trailing semicolon if present
        cleaned_request = request.strip().rstrip(";")

        # Wrap the query in a subquery and alias it
        count_sql = text(
            f"""
            SELECT COUNT(*) AS count FROM (
                {cleaned_request}
            ) AS subquery
        """
        )

        result = db.execute(count_sql)
        return result.scalar()

    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return None


# except SQLAlchemyError as e:
#     logging.error(f"SQL execution error {e}")


async def get_history(
    db: AsyncSession, session_id: UUID, include_responses: bool = False
):
    try:
        get_history_sql = text(
            """
        select request, response  from request
        where status = 'Done'
        and session_id = :session_id
        -- and updated_at < now() - interval '1 hour'
        order by sequence_number desc
        limit 10;
        """
        )
        result = await db.execute(get_history_sql, params={"session_id": session_id})
        result = result.mappings().fetchall()
        data = list(reversed(result))
        if not data:
            return []
        history = list()
        for item in data:
            history.append({"role": "user", "content": item.get("request")})
            if include_responses:
                history.append({"role": "assistant", "content": item.get("response")})
        return history

    except SQLAlchemyError as e:
        logging.error(f"SQL execution error {e}")


async def create_query(
    db: AsyncSession,
    init: CreateQueryModel,
) -> GetQueryModel:
    logging.debug(
        "Create query",
        extra={
            "action": "db::create_query",
            "query": init,
        },
    )
    columns_json = (
        json.dumps([col.model_dump() for col in init.columns]) if init.columns else None
    )

    add_query_sql = text(
        """
        INSERT 
            INTO query (query_id, request, intent, summary, description, sql, row_count, columns, ai_generated, ai_context, data_source, db_dialect, explanation, parent_id)
            VALUES (:query_id, :request, :intent, :summary, :description, :sql, :row_count, :columns, :ai_generated, :ai_context, :data_source, :db_dialect, :explanation, :parent_id)
            RETURNING query_id, request, intent, summary, description, sql, row_count, columns, ai_generated, ai_context, data_source, db_dialect, explanation, parent_id;
        """
    )
    query_id = uuid4()
    res = await db.execute(
        add_query_sql,
        params={
            "query_id": query_id,
            "request": init.request,
            "status": RequestStatus.new,
            "intent": init.intent,
            "summary": init.summary,
            "description": init.description,
            "sql": init.sql,
            "row_count": init.row_count,
            "columns": columns_json,
            "ai_generated": init.ai_generated,
            "ai_context": json.dumps(init.ai_context) if init.ai_context else None,
            "data_source": init.data_source,
            "db_dialect": init.db_dialect,
            "explanation": json.dumps(init.explanation) if init.explanation else None,
            "parent_id": init.parent_id,
        },
    )
    data = res.mappings().fetchone()
    await db.commit()
    try:
        result = GetQueryModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Request object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))

    return result


async def update_query(
    db: AsyncSession,
    update: UpdateQueryModel,
) -> GetQueryModel:
    logging.debug(
        "Update query",
        extra={
            "action": "db::update_query",
            "query": update,
        },
    )
    update_query_sql = text(
        """
        UPDATE query 
        SET row_count = :row_count, explanation = :explanation, err = :err, updated_at = now()
        WHERE query_id = :query_id
        RETURNING query_id, created_at, request, intent, summary, description, sql, row_count, columns, ai_generated, ai_context, data_source, db_dialect, explanation;
        """
    )
    res = await db.execute(
        update_query_sql,
        params={
            "query_id": update.query_id,
            "row_count": update.row_count,
            "explanation": (
                json.dumps(update.explanation) if update.explanation else None
            ),
            "err": update.err,
        },
    )
    data = res.mappings().fetchone()
    await db.commit()
    try:
        result = GetQueryModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Request object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))

    return result


async def get_query_by_id(
    db: AsyncSession,
    query_id: UUID,
) -> Optional[GetQueryModel]:
    logging.debug(
        "Get query",
        extra={
            "action": "db::update_query",
            "query_id": query_id,
        },
    )
    get_query_sql = text(
        """
        SELECT query_id, request, intent, summary, description, sql, row_count, columns, ai_generated, ai_context, data_source, db_dialect, explanation, parent_id
        FROM query
        WHERE query_id = :query_id;
        """
    )
    res = await db.execute(get_query_sql, params={"query_id": query_id})
    data = res.mappings().fetchone()
    if not data:
        return None

    try:
        result = GetQueryModel.model_validate(data)

    except ValidationError as e:
        logging.error(f"Can't validate Query object from DB error: {e}")
        raise HTTPException(status_code=500, detail=str("Internal error"))

    return result


async def get_queries(
    db: AsyncSession,
    limit: Optional[int] = 100,
    offset: Optional[int] = 0,
) -> list[GetQueryModel]:
    logging.debug(
        "Get queries",
        extra={
            "action": "db::get_queries",
        },
    )
    get_queries_sql = text(
        """
        SELECT query_id, request, intent, summary, description, sql, row_count, columns, ai_generated, ai_context, data_source, db_dialect, explanation, parent_id
        FROM query
        LIMIT limit = :limit 
        OFFSET offset = :offset;
        """
    )
    res = await db.execute(get_queries_sql, params={"limit": limit, "offset": offset})
    data = res.mappings().fetchall()

    result = []
    for row in data:
        try:
            result.append(GetQueryModel.model_validate(row))
        except ValidationError as e:
            logging.error(f"Can't validate Query object from DB error: {e}")
            raise HTTPException(status_code=500, detail=str("Internal error"))

    return result
