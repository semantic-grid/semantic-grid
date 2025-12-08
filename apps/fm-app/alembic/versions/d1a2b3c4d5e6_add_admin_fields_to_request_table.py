"""add_admin_fields_to_request_table

Revision ID: d1a2b3c4d5e6
Revises: fcb56e2763ef
Create Date: 2025-12-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a2b3c4d5e6'
down_revision: Union[str, None] = 'fcb56e2763ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE request ADD COLUMN IF NOT EXISTS is_test boolean DEFAULT false;
        ALTER TABLE request ADD COLUMN IF NOT EXISTS is_fixed boolean DEFAULT false;
        ALTER TABLE request ADD COLUMN IF NOT EXISTS fixed_by varchar;
        ALTER TABLE request ADD COLUMN IF NOT EXISTS fixed_ts timestamp with time zone;
        ALTER TABLE request ADD COLUMN IF NOT EXISTS fix_comment text;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE request DROP COLUMN IF EXISTS is_test;
        ALTER TABLE request DROP COLUMN IF EXISTS is_fixed;
        ALTER TABLE request DROP COLUMN IF EXISTS fixed_by;
        ALTER TABLE request DROP COLUMN IF EXISTS fixed_ts;
        ALTER TABLE request DROP COLUMN IF EXISTS fix_comment;
        """
    )
