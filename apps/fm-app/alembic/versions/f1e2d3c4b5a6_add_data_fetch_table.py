"""add_data_fetch_table

Revision ID: f1e2d3c4b5a6
Revises: d1a2b3c4d5e6
Create Date: 2025-12-10

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, None] = "d1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        -- Create enum for data fetch status
        CREATE TYPE data_fetch_status_type AS ENUM (
            'pending',
            'running',
            'success',
            'error',
            'cancelled',
            'timed_out'
        );

        -- Create data_fetch table
        CREATE TABLE IF NOT EXISTS data_fetch (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            query_id uuid NOT NULL,
            request_id uuid,
            task_id varchar,
            requestor varchar NOT NULL DEFAULT 'user',
            status data_fetch_status_type NOT NULL DEFAULT 'pending',
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            started_at timestamp with time zone,
            completed_at timestamp with time zone,
            duration_ms integer,
            query_params jsonb,
            row_count integer,
            error text,
            cache_hit boolean DEFAULT false,
            PRIMARY KEY (id),
            CONSTRAINT data_fetch_query_fk FOREIGN KEY (query_id)
                REFERENCES query(query_id) ON DELETE CASCADE,
            CONSTRAINT data_fetch_request_fk FOREIGN KEY (request_id)
                REFERENCES request(request_id) ON DELETE SET NULL
        );

        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_data_fetch_query_id ON data_fetch(query_id);
        CREATE INDEX IF NOT EXISTS idx_data_fetch_request_id ON data_fetch(request_id);
        CREATE INDEX IF NOT EXISTS idx_data_fetch_created_at ON data_fetch(created_at);
        CREATE INDEX IF NOT EXISTS idx_data_fetch_status ON data_fetch(status);
        CREATE INDEX IF NOT EXISTS idx_data_fetch_task_id ON data_fetch(task_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_data_fetch_task_id;
        DROP INDEX IF EXISTS idx_data_fetch_status;
        DROP INDEX IF EXISTS idx_data_fetch_created_at;
        DROP INDEX IF EXISTS idx_data_fetch_request_id;
        DROP INDEX IF EXISTS idx_data_fetch_query_id;
        DROP TABLE IF EXISTS data_fetch;
        DROP TYPE IF EXISTS data_fetch_status_type;
        """
    )
