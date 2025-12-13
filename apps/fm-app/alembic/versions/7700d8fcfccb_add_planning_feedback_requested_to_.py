"""add_planning_feedback_requested_to_request_status_enum

Revision ID: 7700d8fcfccb
Revises: h1a2b3c4d5e8
Create Date: 2025-12-12 16:54:14.042463

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "7700d8fcfccb"
down_revision: Union[str, None] = "i1a2b3c4d5e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new status values for multi-step query planning flow
    op.execute(
        "ALTER TYPE request_status_type ADD VALUE IF NOT EXISTS 'Planning';"
    )
    op.execute(
        "ALTER TYPE request_status_type ADD VALUE IF NOT EXISTS 'FeedbackRequested';"
    )
    # Add query_plan column to store the plan as JSONB
    op.execute(
        """
        ALTER TABLE request
        ADD COLUMN IF NOT EXISTS query_plan JSONB;
        """
    )


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values
    pass
