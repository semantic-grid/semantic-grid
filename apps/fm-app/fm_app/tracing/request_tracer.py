"""Request tracer for collecting execution steps through flow."""

import hashlib
import time
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from fm_app.api.model import (
    CreatePromptVersionModel,
    CreateTraceStepModel,
    PromptItemType,
    TraceStepType,
)
from fm_app.db.trace_db import (
    create_trace_step,
    get_or_create_prompt_version,
    update_request_trace_summary,
)
from fm_app.mcp_servers.db_meta import PromptItemResult


def compute_hash(content: str) -> str:
    """Compute SHA256 hash for content (first 16 chars)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class RequestTracer:
    """Collects trace steps throughout a request's flow execution.

    Usage:
        tracer = RequestTracer(request_id, db)

        # Trace request context (refs, linked queries, history)
        await tracer.trace_request_context(
            user_request="show me top wallets",
            refs={"cols": ["wallet"], "rows": [...]},
            linked_query_id=uuid,
            history_length=5,
        )

        # Trace MCP call with prompt items
        await tracer.trace_mcp_call(
            tool_name="prompt_items_v2",
            tool_input={"db": "wh_v2", "user_request": "..."},
            prompt_items=result.items,
            duration_ms=150,
        )

        # Trace LLM call
        await tracer.trace_llm_call(
            model="claude-3-5-sonnet",
            input_messages=messages,
            output_raw=response_text,
            output_parsed={"sql": "...", "summary": "..."},
            tokens_in=1500,
            tokens_out=500,
            duration_ms=2000,
        )

        # Trace validation
        await tracer.trace_validation(
            validation_type="sql_preflight",
            success=False,
            errors=[{"error": "syntax error"}],
            duration_ms=50,
        )

        # Finalize and update request summary
        await tracer.finalize()
    """

    def __init__(self, request_id: UUID, db: AsyncSession):
        self.request_id = request_id
        self.db = db
        self.step_number = 0
        self._prompt_version_ids: list[UUID] = []

    async def trace_request_context(
        self,
        user_request: str,
        session_id: Optional[UUID] = None,
        linked_query: Optional[dict[str, Any]] = None,
        parent_query_id: Optional[UUID] = None,
        refs: Optional[dict[str, Any]] = None,
        history_length: int = 0,
        intent: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Trace the request context including refs, linked queries, and history.

        Args:
            user_request: The user's natural language request
            session_id: Current session ID
            linked_query: Previous/linked query details (id, sql, summary)
            parent_query_id: Parent query ID from refs.parent
            refs: Reference data (cols, rows) selected by user
            history_length: Number of previous messages in conversation
            intent: Analyzed intent type
            metadata: Additional context metadata
        """
        self.step_number += 1

        # Build context metadata
        context_data = {
            "user_request": user_request,
            "user_request_hash": compute_hash(user_request),
            "session_id": str(session_id) if session_id else None,
            "history_length": history_length,
            "intent": intent,
        }

        # Add linked/parent query info
        if linked_query:
            context_data["linked_query"] = {
                "query_id": str(linked_query.get("query_id"))
                if linked_query.get("query_id")
                else None,
                "summary": linked_query.get("summary"),
                "sql_hash": compute_hash(linked_query.get("sql", ""))
                if linked_query.get("sql")
                else None,
            }

        if parent_query_id:
            context_data["parent_query_id"] = str(parent_query_id)

        # Add refs info (selected rows/columns)
        if refs:
            context_data["refs"] = {
                "has_cols": bool(refs.get("cols")),
                "cols_count": len(refs.get("cols", [])) if refs.get("cols") else 0,
                "has_rows": bool(refs.get("rows")),
                "rows_count": len(refs.get("rows", [])) if refs.get("rows") else 0,
                "parent": str(refs.get("parent")) if refs.get("parent") else None,
            }

        await create_trace_step(
            self.db,
            CreateTraceStepModel(
                request_id=self.request_id,
                step_number=self.step_number,
                step_type=TraceStepType.request_context,
                metadata={**(metadata or {}), **context_data},
            ),
        )

    async def trace_mcp_call(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        prompt_items: Optional[list[PromptItemResult]] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Trace an MCP tool call, registering prompt versions if provided."""
        self.step_number += 1

        # Register prompt versions and collect IDs
        prompt_version_ids = []
        if prompt_items:
            for item in prompt_items:
                if item.content_hash and item.text:
                    version = await get_or_create_prompt_version(
                        self.db,
                        CreatePromptVersionModel(
                            content_hash=item.content_hash,
                            source="db_meta",
                            source_version="2.0.0",
                            prompt_item_type=item.prompt_item_type,
                            content=item.text,
                            metadata=item.metadata,
                        ),
                    )
                    prompt_version_ids.append(version.id)
                    self._prompt_version_ids.append(version.id)

        await create_trace_step(
            self.db,
            CreateTraceStepModel(
                request_id=self.request_id,
                step_number=self.step_number,
                step_type=TraceStepType.mcp_call,
                tool_name=tool_name,
                tool_input=tool_input,
                prompt_version_ids=prompt_version_ids if prompt_version_ids else None,
                duration_ms=duration_ms,
                error=error,
                metadata=metadata,
            ),
        )

    async def trace_llm_call(
        self,
        model: str,
        input_messages: Any,
        output_raw: Optional[str] = None,
        output_parsed: Optional[dict[str, Any]] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Trace an LLM call with input/output and token usage."""
        self.step_number += 1

        # Compute hash of input for deduplication/analysis
        input_str = str(input_messages)
        input_hash = compute_hash(input_str)

        await create_trace_step(
            self.db,
            CreateTraceStepModel(
                request_id=self.request_id,
                step_number=self.step_number,
                step_type=TraceStepType.llm_call,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                input_hash=input_hash,
                output_raw=output_raw,
                output_parsed=output_parsed,
                duration_ms=duration_ms,
                error=error,
                metadata=metadata,
            ),
        )

    async def trace_validation(
        self,
        validation_type: str,
        success: bool,
        errors: Optional[list[dict[str, Any]]] = None,
        duration_ms: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Trace a validation step (metadata validation, SQL preflight, etc.)."""
        self.step_number += 1

        await create_trace_step(
            self.db,
            CreateTraceStepModel(
                request_id=self.request_id,
                step_number=self.step_number,
                step_type=TraceStepType.validation,
                validation_type=validation_type,
                validation_success=success,
                validation_errors=errors,
                duration_ms=duration_ms,
                metadata=metadata,
            ),
        )

    async def trace_repair(
        self,
        repair_attempt: int,
        error_message: str,
        duration_ms: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Trace a repair attempt after validation failure."""
        self.step_number += 1

        await create_trace_step(
            self.db,
            CreateTraceStepModel(
                request_id=self.request_id,
                step_number=self.step_number,
                step_type=TraceStepType.repair,
                error=error_message,
                duration_ms=duration_ms,
                metadata={
                    **(metadata or {}),
                    "repair_attempt": repair_attempt,
                },
            ),
        )

    async def trace_sql_execution(
        self,
        sql: str,
        row_count: Optional[int] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Trace SQL execution against the warehouse."""
        self.step_number += 1

        await create_trace_step(
            self.db,
            CreateTraceStepModel(
                request_id=self.request_id,
                step_number=self.step_number,
                step_type=TraceStepType.sql_execution,
                output_raw=sql,
                duration_ms=duration_ms,
                error=error,
                metadata={
                    **(metadata or {}),
                    "row_count": row_count,
                    "sql_hash": compute_hash(sql),
                },
            ),
        )

    async def trace_error(
        self,
        error_message: str,
        error_type: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Trace an error that occurred during flow execution."""
        self.step_number += 1

        await create_trace_step(
            self.db,
            CreateTraceStepModel(
                request_id=self.request_id,
                step_number=self.step_number,
                step_type=TraceStepType.error,
                error=error_message,
                metadata={
                    **(metadata or {}),
                    "error_type": error_type,
                },
            ),
        )

    async def trace_prompt_assembly(
        self,
        slot_name: str,
        prompt_hash: str,
        duration_ms: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
        prompt_content: Optional[str] = None,
    ) -> None:
        """Trace prompt assembly step and optionally store prompt content.

        Args:
            slot_name: Name of the prompt slot being assembled
            prompt_hash: Hash of the assembled prompt content
            duration_ms: Time taken to assemble the prompt
            metadata: Additional metadata about the assembly
            prompt_content: The full assembled prompt text (stored in prompt_version)
        """
        self.step_number += 1

        # Store prompt content in prompt_version table if provided
        prompt_version_id = None
        if prompt_content:
            # Use full hash for content-addressable storage
            full_hash = hashlib.sha256(prompt_content.encode("utf-8")).hexdigest()
            version = await get_or_create_prompt_version(
                self.db,
                CreatePromptVersionModel(
                    content_hash=full_hash,
                    source="prompt_assembler",
                    source_version="1.0.0",
                    prompt_item_type=PromptItemType.assembled_prompt,
                    content=prompt_content,
                    metadata={
                        "slot_name": slot_name,
                        "short_hash": prompt_hash or full_hash[:16],
                    },
                ),
            )
            prompt_version_id = version.id
            self._prompt_version_ids.append(version.id)

        await create_trace_step(
            self.db,
            CreateTraceStepModel(
                request_id=self.request_id,
                step_number=self.step_number,
                step_type=TraceStepType.prompt_assembly,
                input_hash=prompt_hash,
                prompt_version_ids=[prompt_version_id] if prompt_version_id else None,
                duration_ms=duration_ms,
                metadata={
                    **(metadata or {}),
                    "slot_name": slot_name,
                },
            ),
        )

    async def finalize(self) -> None:
        """Finalize tracing by updating the request's trace_summary."""
        await update_request_trace_summary(self.db, self.request_id)

    @property
    def prompt_version_ids(self) -> list[UUID]:
        """Get all registered prompt version IDs for this trace."""
        return self._prompt_version_ids


class TracingTimer:
    """Context manager for timing operations."""

    def __init__(self):
        self.start_time: Optional[float] = None
        self.duration_ms: Optional[int] = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            elapsed = time.perf_counter() - self.start_time
            self.duration_ms = int(elapsed * 1000)
        return False
