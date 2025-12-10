"""add_request_trace_table

Revision ID: h1a2b3c4d5e8
Revises: g1a2b3c4d5e7
Create Date: 2025-12-10

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "h1a2b3c4d5e8"
down_revision: Union[str, None] = "g1a2b3c4d5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        -- Create enum for trace step type
        CREATE TYPE trace_step_type AS ENUM (
            'request_context',
            'prompt_assembly',
            'mcp_call',
            'llm_call',
            'validation',
            'repair',
            'sql_execution',
            'error'
        );

        -- Create request_trace table for execution step tracking
        CREATE TABLE IF NOT EXISTS request_trace (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            request_id uuid NOT NULL,
            step_number integer NOT NULL,
            step_type trace_step_type NOT NULL,

            -- For LLM calls
            model varchar,
            tokens_in integer,
            tokens_out integer,
            input_hash varchar(16),
            output_raw text,
            output_parsed jsonb,

            -- For MCP calls
            tool_name varchar,
            tool_input jsonb,
            prompt_version_ids uuid[],

            -- For validation
            validation_type varchar,
            validation_success boolean,
            validation_errors jsonb,

            -- Common fields
            duration_ms integer,
            error text,
            metadata jsonb,
            created_at timestamp with time zone NOT NULL DEFAULT now(),

            PRIMARY KEY (id),
            CONSTRAINT request_trace_request_fk FOREIGN KEY (request_id)
                REFERENCES request(request_id) ON DELETE CASCADE
        );

        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_request_trace_request_id
            ON request_trace(request_id);
        CREATE INDEX IF NOT EXISTS idx_request_trace_step_type
            ON request_trace(step_type);
        CREATE INDEX IF NOT EXISTS idx_request_trace_created_at
            ON request_trace(created_at);

        -- Add trace_summary column to request table
        ALTER TABLE request ADD COLUMN IF NOT EXISTS trace_summary jsonb;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE request DROP COLUMN IF EXISTS trace_summary;
        DROP INDEX IF EXISTS idx_request_trace_created_at;
        DROP INDEX IF EXISTS idx_request_trace_step_type;
        DROP INDEX IF EXISTS idx_request_trace_request_id;
        DROP TABLE IF EXISTS request_trace;
        DROP TYPE IF EXISTS trace_step_type;
        """
    )
