"""add_prompt_version_table

Revision ID: g1a2b3c4d5e7
Revises: f1e2d3c4b5a6
Create Date: 2025-12-10

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "g1a2b3c4d5e7"
down_revision: Union[str, None] = "f1e2d3c4b5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        -- Create enum for prompt item type
        CREATE TYPE prompt_item_type AS ENUM (
            'DBStruct',
            'QueryExample',
            'Instruction',
            'SQLDialect',
            'DataSample',
            'DataDescription'
        );

        -- Create prompt_version table for content-addressable prompt storage
        CREATE TABLE IF NOT EXISTS prompt_version (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            content_hash varchar(16) NOT NULL,
            source varchar NOT NULL DEFAULT 'db_meta',
            source_version varchar,
            prompt_item_type prompt_item_type NOT NULL,
            content text NOT NULL,
            metadata jsonb,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            PRIMARY KEY (id),
            CONSTRAINT prompt_version_hash_unique UNIQUE (content_hash)
        );

        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_prompt_version_hash ON prompt_version(content_hash);
        CREATE INDEX IF NOT EXISTS idx_prompt_version_type ON prompt_version(prompt_item_type);
        CREATE INDEX IF NOT EXISTS idx_prompt_version_created_at ON prompt_version(created_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_prompt_version_created_at;
        DROP INDEX IF EXISTS idx_prompt_version_type;
        DROP INDEX IF EXISTS idx_prompt_version_hash;
        DROP TABLE IF EXISTS prompt_version;
        DROP TYPE IF EXISTS prompt_item_type;
        """
    )
