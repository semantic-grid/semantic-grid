"""add_columns_referenced_to_query_plan

Revision ID: k1a2b3c4d5e1
Revises: j1a2b3c4d5e0
Create Date: 2025-12-15

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "k1a2b3c4d5e1"
down_revision: Union[str, None] = "j1a2b3c4d5e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns_referenced if it doesn't exist (idempotent)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'query_plan' AND column_name = 'columns_referenced'
            ) THEN
                ALTER TABLE query_plan ADD COLUMN columns_referenced JSONB DEFAULT '[]';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE query_plan DROP COLUMN IF EXISTS columns_referenced;
        """
    )
