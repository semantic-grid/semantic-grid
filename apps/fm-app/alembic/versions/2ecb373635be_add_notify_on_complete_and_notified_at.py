"""add_notify_on_complete_and_notified_at

Revision ID: 2ecb373635be
Revises: fcb56e2763ef
Create Date: 2025-11-26 16:47:13.544907

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ecb373635be'
down_revision: Union[str, None] = 'fcb56e2763ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add notify_on_complete column to requests table
    op.add_column('requests', sa.Column('notify_on_complete', sa.Boolean(), nullable=True))
    op.execute("UPDATE requests SET notify_on_complete = false WHERE notify_on_complete IS NULL")
    op.alter_column('requests', 'notify_on_complete', nullable=False, server_default=sa.false())

    # Add notified_at column to requests table
    op.add_column('requests', sa.Column('notified_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove columns
    op.drop_column('requests', 'notified_at')
    op.drop_column('requests', 'notify_on_complete')
