"""Database operations for prompt_version and request_trace tables."""

import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fm_app.api.model import (
    CreatePromptVersionModel,
    CreateTraceStepModel,
    GetPromptVersionModel,
    GetRequestTraceModel,
    GetTraceStepModel,
    TraceStepType,
    TraceSummary,
)

# ============================================================================
# Prompt Version Functions
# ============================================================================


async def get_or_create_prompt_version(
    db: AsyncSession,
    data: CreatePromptVersionModel,
) -> GetPromptVersionModel:
    """Get existing prompt version by hash or create new one.

    Uses content-addressable storage - same content always returns same record.
    """
    logging.debug(
        "Getting or creating prompt version",
        extra={
            "content_hash": data.content_hash,
            "prompt_item_type": data.prompt_item_type,
            "action": "db::get_or_create_prompt_version",
        },
    )

    # First try to find existing
    select_sql = text(
        """
        SELECT id, content_hash, source, source_version, prompt_item_type,
               content, metadata, created_at
        FROM prompt_version
        WHERE content_hash = :content_hash
        """
    )

    try:
        result = await db.execute(
            select_sql, params={"content_hash": data.content_hash}
        )
        row = result.mappings().fetchone()

        if row:
            logging.debug(
                "Found existing prompt version",
                extra={"content_hash": data.content_hash, "id": str(row["id"])},
            )
            return GetPromptVersionModel.model_validate(row)

        # Create new version
        metadata_json = json.dumps(data.metadata) if data.metadata else None

        insert_sql = text(
            """
            INSERT INTO prompt_version
                (content_hash, source, source_version, prompt_item_type, content, metadata)
            VALUES
                (:content_hash, :source, :source_version, :prompt_item_type, :content, :metadata)
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING id, content_hash, source, source_version, prompt_item_type,
                      content, metadata, created_at
            """
        )

        result = await db.execute(
            insert_sql,
            params={
                "content_hash": data.content_hash,
                "source": data.source,
                "source_version": data.source_version,
                "prompt_item_type": data.prompt_item_type.value,
                "content": data.content,
                "metadata": metadata_json,
            },
        )
        row = result.mappings().fetchone()
        await db.commit()

        if row:
            return GetPromptVersionModel.model_validate(row)

        # If insert returned nothing due to conflict, fetch existing
        result = await db.execute(
            select_sql, params={"content_hash": data.content_hash}
        )
        row = result.mappings().fetchone()
        return GetPromptVersionModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate PromptVersion object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def get_prompt_version_by_hash(
    db: AsyncSession,
    content_hash: str,
) -> Optional[GetPromptVersionModel]:
    """Get prompt version by content hash."""
    select_sql = text(
        """
        SELECT id, content_hash, source, source_version, prompt_item_type,
               content, metadata, created_at
        FROM prompt_version
        WHERE content_hash = :content_hash
        """
    )

    try:
        result = await db.execute(select_sql, params={"content_hash": content_hash})
        row = result.mappings().fetchone()

        if not row:
            return None

        return GetPromptVersionModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate PromptVersion object from DB: {e}")
        return None
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return None


async def get_prompt_version_by_id(
    db: AsyncSession,
    version_id: UUID,
) -> Optional[GetPromptVersionModel]:
    """Get prompt version by ID."""
    select_sql = text(
        """
        SELECT id, content_hash, source, source_version, prompt_item_type,
               content, metadata, created_at
        FROM prompt_version
        WHERE id = :version_id
        """
    )

    try:
        result = await db.execute(select_sql, params={"version_id": version_id})
        row = result.mappings().fetchone()

        if not row:
            return None

        return GetPromptVersionModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate PromptVersion object from DB: {e}")
        return None
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return None


# ============================================================================
# Request Trace Functions
# ============================================================================


async def create_trace_step(
    db: AsyncSession,
    data: CreateTraceStepModel,
) -> GetTraceStepModel:
    """Create a new trace step record."""
    logging.debug(
        "Creating trace step",
        extra={
            "request_id": str(data.request_id),
            "step_number": data.step_number,
            "step_type": data.step_type,
            "action": "db::create_trace_step",
        },
    )

    insert_sql = text(
        """
        INSERT INTO request_trace (
            request_id, step_number, step_type,
            model, tokens_in, tokens_out, input_hash, output_raw, output_parsed,
            tool_name, tool_input, prompt_version_ids,
            validation_type, validation_success, validation_errors,
            duration_ms, error, metadata
        )
        VALUES (
            :request_id, :step_number, :step_type,
            :model, :tokens_in, :tokens_out, :input_hash, :output_raw, :output_parsed,
            :tool_name, :tool_input, :prompt_version_ids,
            :validation_type, :validation_success, :validation_errors,
            :duration_ms, :error, :metadata
        )
        RETURNING id, request_id, step_number, step_type,
                  model, tokens_in, tokens_out, input_hash, output_raw, output_parsed,
                  tool_name, tool_input, prompt_version_ids,
                  validation_type, validation_success, validation_errors,
                  duration_ms, error, metadata, created_at
        """
    )

    try:
        result = await db.execute(
            insert_sql,
            params={
                "request_id": data.request_id,
                "step_number": data.step_number,
                "step_type": data.step_type.value,
                "model": data.model,
                "tokens_in": data.tokens_in,
                "tokens_out": data.tokens_out,
                "input_hash": data.input_hash,
                "output_raw": data.output_raw,
                "output_parsed": json.dumps(data.output_parsed)
                if data.output_parsed
                else None,
                "tool_name": data.tool_name,
                "tool_input": json.dumps(data.tool_input) if data.tool_input else None,
                "prompt_version_ids": data.prompt_version_ids,
                "validation_type": data.validation_type,
                "validation_success": data.validation_success,
                "validation_errors": json.dumps(data.validation_errors)
                if data.validation_errors
                else None,
                "duration_ms": data.duration_ms,
                "error": data.error,
                "metadata": json.dumps(data.metadata) if data.metadata else None,
            },
        )
        row = result.mappings().fetchone()
        await db.commit()

        return GetTraceStepModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate TraceStep object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def get_trace_steps_for_request(
    db: AsyncSession,
    request_id: UUID,
) -> list[GetTraceStepModel]:
    """Get all trace steps for a request ordered by step number."""
    select_sql = text(
        """
        SELECT id, request_id, step_number, step_type,
               model, tokens_in, tokens_out, input_hash, output_raw, output_parsed,
               tool_name, tool_input, prompt_version_ids,
               validation_type, validation_success, validation_errors,
               duration_ms, error, metadata, created_at
        FROM request_trace
        WHERE request_id = :request_id
        ORDER BY step_number ASC
        """
    )

    try:
        result = await db.execute(select_sql, params={"request_id": request_id})
        rows = result.mappings().fetchall()

        return [GetTraceStepModel.model_validate(row) for row in rows]

    except ValidationError as e:
        logging.error(f"Can't validate TraceStep objects from DB: {e}")
        return []
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return []


async def get_request_trace(
    db: AsyncSession,
    request_id: UUID,
) -> Optional[GetRequestTraceModel]:
    """Get full trace for a request including summary statistics."""
    steps = await get_trace_steps_for_request(db, request_id)

    if not steps:
        return None

    # Compute summary
    llm_calls = 0
    mcp_calls = 0
    validations = 0
    repairs = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_duration_ms = 0
    has_errors = False

    for step in steps:
        if step.step_type == TraceStepType.llm_call:
            llm_calls += 1
            total_tokens_in += step.tokens_in or 0
            total_tokens_out += step.tokens_out or 0
        elif step.step_type == TraceStepType.mcp_call:
            mcp_calls += 1
        elif step.step_type == TraceStepType.validation:
            validations += 1
        elif step.step_type == TraceStepType.repair:
            repairs += 1
        elif step.step_type == TraceStepType.error:
            has_errors = True

        total_duration_ms += step.duration_ms or 0

        if step.error:
            has_errors = True

    summary = TraceSummary(
        total_steps=len(steps),
        llm_calls=llm_calls,
        mcp_calls=mcp_calls,
        validations=validations,
        repairs=repairs,
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        total_duration_ms=total_duration_ms,
        has_errors=has_errors,
    )

    return GetRequestTraceModel(
        request_id=request_id,
        steps=steps,
        summary=summary,
    )


async def update_request_trace_summary(
    db: AsyncSession,
    request_id: UUID,
) -> None:
    """Update the trace_summary field on the request table."""
    trace = await get_request_trace(db, request_id)

    if not trace:
        return

    update_sql = text(
        """
        UPDATE request
        SET trace_summary = :trace_summary
        WHERE request_id = :request_id
        """
    )

    try:
        await db.execute(
            update_sql,
            params={
                "request_id": request_id,
                "trace_summary": json.dumps(trace.summary.model_dump()),
            },
        )
        await db.commit()

    except SQLAlchemyError as e:
        logging.error(f"Failed to update trace summary: {e}")


# ============================================================================
# Admin Functions
# ============================================================================


async def get_requests_with_traces(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[GetRequestTraceModel], int]:
    """Get requests that have traces with pagination."""
    # Get total count of requests with traces
    count_sql = text(
        """
        SELECT COUNT(DISTINCT request_id) as total
        FROM request_trace
        """
    )

    try:
        count_result = await db.execute(count_sql)
        total = count_result.scalar() or 0

        # Get distinct request_ids with traces, ordered by most recent
        requests_sql = text(
            """
            SELECT DISTINCT request_id
            FROM request_trace
            ORDER BY request_id DESC
            LIMIT :limit OFFSET :offset
            """
        )

        result = await db.execute(
            requests_sql, params={"limit": limit, "offset": offset}
        )
        request_ids = [row[0] for row in result.fetchall()]

        # Get full trace for each request
        traces = []
        for request_id in request_ids:
            trace = await get_request_trace(db, request_id)
            if trace:
                traces.append(trace)

        return traces, total

    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return [], 0


async def get_all_prompt_versions(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    prompt_item_type: Optional[str] = None,
) -> tuple[list[GetPromptVersionModel], int]:
    """Get all prompt versions with pagination and optional filtering."""
    # Build count query
    count_sql = "SELECT COUNT(*) FROM prompt_version"
    params = {}

    if prompt_item_type:
        count_sql += " WHERE prompt_item_type = :prompt_item_type"
        params["prompt_item_type"] = prompt_item_type

    try:
        count_result = await db.execute(text(count_sql), params=params)
        total = count_result.scalar() or 0

        # Build select query
        select_sql = """
            SELECT id, content_hash, source, source_version, prompt_item_type,
                   content, metadata, created_at
            FROM prompt_version
        """

        if prompt_item_type:
            select_sql += " WHERE prompt_item_type = :prompt_item_type"

        select_sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset

        result = await db.execute(text(select_sql), params=params)
        rows = result.mappings().fetchall()

        versions = [GetPromptVersionModel.model_validate(row) for row in rows]
        return versions, total

    except ValidationError as e:
        logging.error(f"Can't validate PromptVersion objects from DB: {e}")
        return [], 0
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return [], 0
