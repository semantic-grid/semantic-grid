"""add_v2_message_notify_trigger

Adds PostgreSQL NOTIFY trigger for v2 message status changes.

Similar to v1's request_update trigger, this sends notifications when message
status changes, enabling real-time SSE updates for persistent events.

Transient events (thinking, validating, etc.) still use in-memory EventBus.

Revision ID: be04411eab45
Revises: 7cac97c6b726
Create Date: 2025-01-09 16:30:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "be04411eab45"
down_revision: Union[str, None] = "7cac97c6b726"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create PostgreSQL trigger function and trigger for v2 message notifications.

    Emits pg_notify event whenever a message row is inserted or updated.
    This enables SSE clients to receive real-time updates for persistent events.
    """
    op.execute(
        """
        -- Create trigger function to send notifications on message changes
        CREATE OR REPLACE FUNCTION notify_v2_message_update()
        RETURNS trigger AS $$
        BEGIN
            -- Notify on INSERT or when status/error changes
            IF (TG_OP = 'INSERT')
               OR (OLD.status IS DISTINCT FROM NEW.status)
               OR (OLD.error IS DISTINCT FROM NEW.error) THEN

                -- Send notification to 'v2_message_update' channel
                PERFORM pg_notify(
                    'v2_message_update',
                    json_build_object(
                        'message_id', NEW.id,
                        'session_id', NEW.session_id::text,
                        'role', NEW.role,
                        'kind', NEW.kind,
                        'status', NEW.status,
                        'has_error', (NEW.error IS NOT NULL),
                        'created_at', EXTRACT(EPOCH FROM NEW.created_at),
                        'operation', TG_OP
                    )::text
                );
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        -- Create trigger on messages table
        CREATE TRIGGER v2_message_update_trigger
        AFTER INSERT OR UPDATE ON messages
        FOR EACH ROW
        EXECUTE FUNCTION notify_v2_message_update();

        -- Create index for efficient SSE queries (if not exists from migration)
        CREATE INDEX IF NOT EXISTS idx_messages_session_created
        ON messages(session_id, created_at DESC);
    """
    )


def downgrade() -> None:
    """
    Remove the trigger, trigger function, and index.
    """
    op.execute(
        """
        -- Drop trigger
        DROP TRIGGER IF EXISTS v2_message_update_trigger ON messages;

        -- Drop trigger function
        DROP FUNCTION IF EXISTS notify_v2_message_update();

        -- Drop index (keep if used by other queries)
        -- DROP INDEX IF EXISTS idx_messages_session_created;
    """
    )
