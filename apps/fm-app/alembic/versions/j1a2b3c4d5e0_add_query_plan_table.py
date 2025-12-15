"""add_query_plan_table

Revision ID: j1a2b3c4d5e0
Revises: i1a2b3c4d5e9
Create Date: 2025-12-15

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "j1a2b3c4d5e0"
down_revision: Union[str, None] = "i1a2b3c4d5e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        -- Create query_plan table
        CREATE TABLE query_plan (
            id BIGINT GENERATED ALWAYS AS IDENTITY,
            plan_id UUID NOT NULL DEFAULT gen_random_uuid(),

            -- Relationships
            session_id UUID NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
            request_id UUID NOT NULL REFERENCES request(request_id) ON DELETE CASCADE,
            parent_id UUID REFERENCES query_plan(plan_id) ON DELETE SET NULL,

            -- Plan content (JSONB arrays for flexibility)
            tables JSONB DEFAULT '[]',
            primary_table VARCHAR,
            joins JSONB DEFAULT '[]',
            columns_selected JSONB DEFAULT '[]',
            filters JSONB DEFAULT '[]',
            aggregations JSONB DEFAULT '[]',
            group_by JSONB DEFAULT '[]',
            order_by JSONB DEFAULT '[]',
            plan_limit VARCHAR,
            assumptions JSONB DEFAULT '[]',
            default_params JSONB DEFAULT '[]',
            plan_summary TEXT NOT NULL,
            estimated_complexity VARCHAR DEFAULT 'moderate',
            reason_for_approval TEXT,
            relevant_schema TEXT,

            -- Intent tracking
            original_intent TEXT NOT NULL,
            amendment_feedback TEXT,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            PRIMARY KEY (plan_id)
        );

        -- Indexes for query_plan
        CREATE INDEX idx_query_plan_plan_id ON query_plan(plan_id);
        CREATE INDEX idx_query_plan_session_id ON query_plan(session_id);
        CREATE INDEX idx_query_plan_request_id ON query_plan(request_id);
        CREATE INDEX idx_query_plan_parent_id ON query_plan(parent_id);

        -- Add plan_id column to query table
        ALTER TABLE query ADD COLUMN plan_id UUID REFERENCES query_plan(plan_id) ON DELETE SET NULL;
        CREATE INDEX idx_query_plan_id ON query(plan_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        -- Remove plan_id from query table
        DROP INDEX IF EXISTS idx_query_plan_id;
        ALTER TABLE query DROP COLUMN IF EXISTS plan_id;

        -- Drop query_plan table and indexes
        DROP INDEX IF EXISTS idx_query_plan_parent_id;
        DROP INDEX IF EXISTS idx_query_plan_request_id;
        DROP INDEX IF EXISTS idx_query_plan_session_id;
        DROP INDEX IF EXISTS idx_query_plan_plan_id;
        DROP TABLE IF EXISTS query_plan;
        """
    )
