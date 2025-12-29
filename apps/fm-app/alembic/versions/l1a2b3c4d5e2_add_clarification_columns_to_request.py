"""add_response_type_payload_columns

Revision ID: l1a2b3c4d5e2
Revises: k1a2b3c4d5e1
Create Date: 2025-12-19

Adds response_type and payload columns to the request table
to support the unified "ask user" pattern for all response types.

See: docs/plans/phase1-ask-user-primitive.md

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l1a2b3c4d5e2"
down_revision: Union[str, None] = "k1a2b3c4d5e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        -- Response type discriminator
        -- Values: "query", "plan_approval", "clarification", "chat", "error", etc.
        ALTER TABLE request ADD COLUMN IF NOT EXISTS response_type TEXT;

        -- Type-specific payload (shape varies by response_type)
        ALTER TABLE request ADD COLUMN IF NOT EXISTS payload JSONB;

        -- Index for filtering by response type
        CREATE INDEX IF NOT EXISTS idx_request_response_type
        ON request(response_type) WHERE response_type IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_request_response_type;
        ALTER TABLE request DROP COLUMN IF EXISTS payload;
        ALTER TABLE request DROP COLUMN IF EXISTS response_type;
        """
    )
