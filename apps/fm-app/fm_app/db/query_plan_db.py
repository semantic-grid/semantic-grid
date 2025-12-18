"""Database operations for query_plan table."""

import json
import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fm_app.api.model import (
    CreateQueryPlanModel,
    GetQueryPlanModel,
    QueryPlanChainModel,
)


class UUIDEncoder(json.JSONEncoder):
    """JSON encoder that handles UUID objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


def json_dumps_safe(obj: Any) -> str:
    """JSON dumps with UUID support."""
    return json.dumps(obj, cls=UUIDEncoder)


# ============================================================================
# Query Plan CRUD Functions
# ============================================================================


async def create_query_plan(
    db: AsyncSession,
    data: CreateQueryPlanModel,
) -> GetQueryPlanModel:
    """Create a new query plan record."""
    logging.debug(
        "Creating query plan",
        extra={
            "session_id": str(data.session_id),
            "request_id": str(data.request_id),
            "parent_id": str(data.parent_id) if data.parent_id else None,
            "action": "db::create_query_plan",
        },
    )

    insert_sql = text(
        """
        INSERT INTO query_plan (
            session_id, request_id, parent_id,
            tables, primary_table, joins, columns_selected, columns_referenced,
            filters, aggregations, group_by, order_by, plan_limit,
            assumptions, default_params, plan_summary, estimated_complexity,
            reason_for_approval, relevant_schema,
            original_intent, amendment_feedback
        )
        VALUES (
            :session_id, :request_id, :parent_id,
            :tables, :primary_table, :joins, :columns_selected, :columns_referenced,
            :filters, :aggregations, :group_by, :order_by, :plan_limit,
            :assumptions, :default_params, :plan_summary, :estimated_complexity,
            :reason_for_approval, :relevant_schema,
            :original_intent, :amendment_feedback
        )
        RETURNING plan_id, session_id, request_id, parent_id,
                  tables, primary_table, joins, columns_selected, columns_referenced,
                  filters, aggregations, group_by, order_by, plan_limit,
                  assumptions, default_params, plan_summary, estimated_complexity,
                  reason_for_approval, relevant_schema,
                  original_intent, amendment_feedback,
                  created_at, updated_at
        """
    )

    try:
        result = await db.execute(
            insert_sql,
            params={
                "session_id": data.session_id,
                "request_id": data.request_id,
                "parent_id": data.parent_id,
                "tables": json_dumps_safe(data.tables),
                "primary_table": data.primary_table,
                "joins": json_dumps_safe(data.joins),
                "columns_selected": json_dumps_safe(data.columns_selected),
                "columns_referenced": json_dumps_safe(data.columns_referenced),
                "filters": json_dumps_safe(data.filters),
                "aggregations": json_dumps_safe(data.aggregations),
                "group_by": json_dumps_safe(data.group_by),
                "order_by": json_dumps_safe(data.order_by),
                "plan_limit": data.plan_limit,
                "assumptions": json_dumps_safe(data.assumptions),
                "default_params": json_dumps_safe(data.default_params),
                "plan_summary": data.plan_summary,
                "estimated_complexity": data.estimated_complexity,
                "reason_for_approval": data.reason_for_approval,
                "relevant_schema": data.relevant_schema,
                "original_intent": data.original_intent,
                "amendment_feedback": data.amendment_feedback,
            },
        )
        row = result.mappings().fetchone()
        await db.commit()

        return GetQueryPlanModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate QueryPlan object from DB: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error creating query plan: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def get_query_plan_by_id(
    db: AsyncSession,
    plan_id: UUID,
) -> Optional[GetQueryPlanModel]:
    """Get a query plan by its ID."""
    select_sql = text(
        """
        SELECT plan_id, session_id, request_id, parent_id,
               tables, primary_table, joins, columns_selected, columns_referenced,
               filters, aggregations, group_by, order_by, plan_limit,
               assumptions, default_params, plan_summary, estimated_complexity,
               reason_for_approval, relevant_schema,
               original_intent, amendment_feedback,
               created_at, updated_at
        FROM query_plan
        WHERE plan_id = :plan_id
        """
    )

    try:
        result = await db.execute(select_sql, params={"plan_id": plan_id})
        row = result.mappings().fetchone()

        if not row:
            return None

        return GetQueryPlanModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate QueryPlan object from DB: {e}")
        return None
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return None


async def get_query_plan_by_request_id(
    db: AsyncSession,
    request_id: UUID,
) -> Optional[GetQueryPlanModel]:
    """Get the query plan for a specific request."""
    select_sql = text(
        """
        SELECT plan_id, session_id, request_id, parent_id,
               tables, primary_table, joins, columns_selected, columns_referenced,
               filters, aggregations, group_by, order_by, plan_limit,
               assumptions, default_params, plan_summary, estimated_complexity,
               reason_for_approval, relevant_schema,
               original_intent, amendment_feedback,
               created_at, updated_at
        FROM query_plan
        WHERE request_id = :request_id
        """
    )

    try:
        result = await db.execute(select_sql, params={"request_id": request_id})
        row = result.mappings().fetchone()

        if not row:
            return None

        return GetQueryPlanModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate QueryPlan object from DB: {e}")
        return None
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return None


async def get_latest_plan_for_session(
    db: AsyncSession,
    session_id: UUID,
) -> Optional[GetQueryPlanModel]:
    """Get the most recent query plan for a session."""
    select_sql = text(
        """
        SELECT plan_id, session_id, request_id, parent_id,
               tables, primary_table, joins, columns_selected, columns_referenced,
               filters, aggregations, group_by, order_by, plan_limit,
               assumptions, default_params, plan_summary, estimated_complexity,
               reason_for_approval, relevant_schema,
               original_intent, amendment_feedback,
               created_at, updated_at
        FROM query_plan
        WHERE session_id = :session_id
        ORDER BY created_at DESC
        LIMIT 1
        """
    )

    try:
        result = await db.execute(select_sql, params={"session_id": session_id})
        row = result.mappings().fetchone()

        if not row:
            return None

        return GetQueryPlanModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate QueryPlan object from DB: {e}")
        return None
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return None


async def get_plan_chain(
    db: AsyncSession,
    plan_id: UUID,
) -> QueryPlanChainModel:
    """Get the full chain of query plans (amendment history) using recursive CTE.

    Returns plans from oldest (root) to newest (current).
    """
    # Recursive CTE to walk up the parent chain
    select_sql = text(
        """
        WITH RECURSIVE plan_chain AS (
            -- Base case: start with the given plan
            SELECT plan_id, session_id, request_id, parent_id,
                   tables, primary_table, joins, columns_selected, columns_referenced,
                   filters, aggregations, group_by, order_by, plan_limit,
                   assumptions, default_params, plan_summary, estimated_complexity,
                   reason_for_approval, relevant_schema,
                   original_intent, amendment_feedback,
                   created_at, updated_at,
                   1 as depth
            FROM query_plan
            WHERE plan_id = :plan_id

            UNION ALL

            -- Recursive case: get parent plans
            SELECT p.plan_id, p.session_id, p.request_id, p.parent_id,
                   p.tables, p.primary_table, p.joins, p.columns_selected,
                   p.columns_referenced, p.filters, p.aggregations, p.group_by,
                   p.order_by, p.plan_limit, p.assumptions, p.default_params,
                   p.plan_summary, p.estimated_complexity, p.reason_for_approval,
                   p.relevant_schema, p.original_intent, p.amendment_feedback,
                   p.created_at, p.updated_at,
                   pc.depth + 1
            FROM query_plan p
            INNER JOIN plan_chain pc ON p.plan_id = pc.parent_id
        )
        SELECT plan_id, session_id, request_id, parent_id,
               tables, primary_table, joins, columns_selected, columns_referenced,
               filters, aggregations, group_by, order_by, plan_limit,
               assumptions, default_params, plan_summary, estimated_complexity,
               reason_for_approval, relevant_schema,
               original_intent, amendment_feedback,
               created_at, updated_at
        FROM plan_chain
        ORDER BY depth DESC  -- Oldest first (root of chain)
        """
    )

    try:
        result = await db.execute(select_sql, params={"plan_id": plan_id})
        rows = result.mappings().fetchall()

        plans = [GetQueryPlanModel.model_validate(row) for row in rows]

        return QueryPlanChainModel(
            plans=plans,
            total_iterations=len(plans),
        )

    except ValidationError as e:
        logging.error(f"Can't validate QueryPlan objects from DB: {e}")
        return QueryPlanChainModel(plans=[], total_iterations=0)
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return QueryPlanChainModel(plans=[], total_iterations=0)


async def get_plans_for_session(
    db: AsyncSession,
    session_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[GetQueryPlanModel], int]:
    """Get all query plans for a session with pagination."""
    count_sql = text(
        """
        SELECT COUNT(*) FROM query_plan WHERE session_id = :session_id
        """
    )

    select_sql = text(
        """
        SELECT plan_id, session_id, request_id, parent_id,
               tables, primary_table, joins, columns_selected, columns_referenced,
               filters, aggregations, group_by, order_by, plan_limit,
               assumptions, default_params, plan_summary, estimated_complexity,
               reason_for_approval, relevant_schema,
               original_intent, amendment_feedback,
               created_at, updated_at
        FROM query_plan
        WHERE session_id = :session_id
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )

    try:
        count_result = await db.execute(count_sql, params={"session_id": session_id})
        total = count_result.scalar() or 0

        result = await db.execute(
            select_sql,
            params={"session_id": session_id, "limit": limit, "offset": offset},
        )
        rows = result.mappings().fetchall()

        plans = [GetQueryPlanModel.model_validate(row) for row in rows]
        return plans, total

    except ValidationError as e:
        logging.error(f"Can't validate QueryPlan objects from DB: {e}")
        return [], 0
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return [], 0


# ============================================================================
# Query Table Integration
# ============================================================================


async def update_query_plan_id(
    db: AsyncSession,
    query_id: UUID,
    plan_id: UUID,
) -> bool:
    """Link a query to the plan that produced it."""
    update_sql = text(
        """
        UPDATE query
        SET plan_id = :plan_id
        WHERE query_id = :query_id
        """
    )

    try:
        await db.execute(
            update_sql,
            params={"query_id": query_id, "plan_id": plan_id},
        )
        await db.commit()
        return True

    except SQLAlchemyError as e:
        logging.error(f"Failed to update query plan_id: {e}")
        return False


async def get_plan_for_query(
    db: AsyncSession,
    query_id: UUID,
) -> Optional[GetQueryPlanModel]:
    """Get the plan that produced a specific query."""
    select_sql = text(
        """
        SELECT qp.plan_id, qp.session_id, qp.request_id, qp.parent_id,
               qp.tables, qp.primary_table, qp.joins, qp.columns_selected,
               qp.columns_referenced, qp.filters,
               qp.aggregations, qp.group_by, qp.order_by, qp.plan_limit,
               qp.assumptions, qp.default_params, qp.plan_summary,
               qp.estimated_complexity, qp.reason_for_approval, qp.relevant_schema,
               qp.original_intent, qp.amendment_feedback,
               qp.created_at, qp.updated_at
        FROM query_plan qp
        INNER JOIN query q ON q.plan_id = qp.plan_id
        WHERE q.query_id = :query_id
        """
    )

    try:
        result = await db.execute(select_sql, params={"query_id": query_id})
        row = result.mappings().fetchone()

        if not row:
            return None

        return GetQueryPlanModel.model_validate(row)

    except ValidationError as e:
        logging.error(f"Can't validate QueryPlan object from DB: {e}")
        return None
    except SQLAlchemyError as e:
        logging.error(f"SQL execution error: {e}")
        return None
