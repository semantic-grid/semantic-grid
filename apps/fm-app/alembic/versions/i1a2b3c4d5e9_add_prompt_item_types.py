"""add_prompt_item_types

Revision ID: i1a2b3c4d5e9
Revises: h1a2b3c4d5e8
Create Date: 2025-12-11

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "i1a2b3c4d5e9"
down_revision: Union[str, None] = "h1a2b3c4d5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values to prompt_item_type
    # Also make the column nullable to support assembled prompts without a specific type
    op.execute(
        """
        -- Add new enum values
        ALTER TYPE prompt_item_type ADD VALUE IF NOT EXISTS 'SQLDialect';
        ALTER TYPE prompt_item_type ADD VALUE IF NOT EXISTS 'AssembledPrompt';
        ALTER TYPE prompt_item_type ADD VALUE IF NOT EXISTS 'RefSources';
        ALTER TYPE prompt_item_type ADD VALUE IF NOT EXISTS 'SlotSchema';

        -- Make prompt_item_type nullable
        ALTER TABLE prompt_version ALTER COLUMN prompt_item_type DROP NOT NULL;

        -- Also fix content_hash length - it should be 64 chars for full SHA256
        ALTER TABLE prompt_version ALTER COLUMN content_hash TYPE varchar(64);
        """
    )


def downgrade() -> None:
    # Note: PostgreSQL doesn't support removing enum values easily
    # Just revert the nullable change
    op.execute(
        """
        ALTER TABLE prompt_version ALTER COLUMN content_hash TYPE varchar(16);
        ALTER TABLE prompt_version ALTER COLUMN prompt_item_type SET NOT NULL;
        """
    )
