"""add_needs_fixing_to_request

Revision ID: m1a2b3c4d5e3
Revises: l1a2b3c4d5e2
Create Date: 2025-01-05

Adds needs_fixing boolean column to the request table
for admins to flag requests that need prompt engineering fixes.

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m1a2b3c4d5e3"
down_revision: Union[str, None] = "l1a2b3c4d5e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE request ADD COLUMN IF NOT EXISTS needs_fixing boolean DEFAULT false;

        -- Index for filtering requests that need fixing
        CREATE INDEX IF NOT EXISTS idx_request_needs_fixing
        ON request(needs_fixing) WHERE needs_fixing = true;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_request_needs_fixing;
        ALTER TABLE request DROP COLUMN IF EXISTS needs_fixing;
        """
    )
