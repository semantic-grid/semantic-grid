"""add_v2_schema_messages_and_api_version

Revision ID: 7cac97c6b726
Revises: b725927e9e64
Create Date: 2025-11-09 12:40:49.140464

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7cac97c6b726'
down_revision: Union[str, None] = 'b725927e9e64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add api_version column to session table (singular, not plural)
    op.add_column('session', sa.Column('api_version', sa.String(10), server_default='v1'))

    # Backfill existing sessions as v1
    op.execute("UPDATE session SET api_version = 'v1' WHERE api_version IS NULL")

    # Create messages table
    op.execute("""
        CREATE TABLE messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,

            -- Content (polymorphic: text, JSON, or reference to attachment)
            content JSONB NOT NULL,
            content_type VARCHAR(100) DEFAULT 'text/markdown',

            -- Classification
            role VARCHAR(50) NOT NULL,
            kind VARCHAR(50) NOT NULL,
            persistent BOOLEAN NOT NULL DEFAULT TRUE,

            -- Metadata
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            metadata JSONB DEFAULT '{}',

            -- Relationships
            parent_id UUID REFERENCES messages(id) ON DELETE SET NULL,
            thread_id UUID,
            tags TEXT[] DEFAULT '{}',

            -- Status
            status VARCHAR(50) DEFAULT 'pending',
            error TEXT
        )
    """)

    # Create indexes for messages
    op.create_index('idx_messages_session', 'messages', ['session_id', 'created_at'])
    op.create_index('idx_messages_thread', 'messages', ['thread_id'])
    op.create_index('idx_messages_parent', 'messages', ['parent_id'])
    op.create_index('idx_messages_role_kind', 'messages', ['role', 'kind'])

    # Create message_queries table
    op.execute("""
        CREATE TABLE message_queries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,

            -- Core query details
            sql_query TEXT NOT NULL,
            row_count INTEGER,
            execution_time_ms INTEGER,

            -- Lineage & provenance
            prompt_hash VARCHAR(64),
            mcp_call_hash VARCHAR(64),
            profile VARCHAR(100),

            -- Link to v1 query table (for backward compatibility)
            v1_query_id UUID,

            -- Extended metadata (can store v1 QueryMetadata fields as JSONB)
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    # Create indexes for message_queries
    op.create_index('idx_message_queries_message', 'message_queries', ['message_id'])
    op.create_index('idx_message_queries_v1_query', 'message_queries', ['v1_query_id'])

    # Create message_attachments table
    op.execute("""
        CREATE TABLE message_attachments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,

            -- Content type
            content_type VARCHAR(100) NOT NULL,

            -- Storage (one of these)
            content_url TEXT,
            content_data BYTEA,

            -- Metadata
            filename VARCHAR(255),
            size_bytes INTEGER,
            metadata JSONB DEFAULT '{}'
        )
    """)

    # Create index for message_attachments
    op.create_index('idx_message_attachments_message', 'message_attachments', ['message_id'])


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('message_attachments')
    op.drop_table('message_queries')
    op.drop_table('messages')

    # Remove api_version column from session
    op.drop_column('session', 'api_version')
