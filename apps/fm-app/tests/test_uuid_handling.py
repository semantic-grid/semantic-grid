"""
Unit tests for UUID handling in v2 API

Tests that UUID objects are properly converted to strings at boundaries:
- Database queries
- Pydantic model creation
- Worker serialization
"""

import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from fm_app.api.v2.model import Message, MessageKind, MessageRole, MessageStatus


def test_message_accepts_string_session_id():
    """Test that Message model accepts string session_id"""
    session_id_str = str(uuid4())

    message = Message(
        id=str(uuid4()),
        session_id=session_id_str,
        content="test content",
        content_type="text/markdown",
        role=MessageRole.USER,
        kind=MessageKind.CHAT,
        persistent=True,
        status=MessageStatus.PENDING,
    )

    assert message.session_id == session_id_str
    assert isinstance(message.session_id, str)


def test_message_rejects_uuid_session_id():
    """Test that Message model rejects UUID object for session_id"""
    session_id_uuid = uuid4()

    with pytest.raises(ValidationError) as exc_info:
        Message(
            id=str(uuid4()),
            session_id=session_id_uuid,  # This should fail
            content="test content",
            content_type="text/markdown",
            role=MessageRole.USER,
            kind=MessageKind.CHAT,
            persistent=True,
            status=MessageStatus.PENDING,
        )

    # Check that the error mentions session_id and string_type
    error = exc_info.value
    assert any("session_id" in str(e) for e in error.errors())
    assert any("string" in str(e).lower() for e in error.errors())


def test_uuid_to_string_conversion():
    """Test that UUID objects are properly converted to strings"""
    session_id_uuid = uuid4()
    session_id_str = str(session_id_uuid)

    # Verify conversion
    assert isinstance(session_id_uuid, UUID)
    assert isinstance(session_id_str, str)
    assert session_id_str == str(session_id_uuid)

    # Verify string format (8-4-4-4-12 pattern)
    assert len(session_id_str) == 36
    assert session_id_str.count('-') == 4


def test_message_serialization_with_string_session_id():
    """Test that Message can be serialized/deserialized through JSON"""
    session_id_str = str(uuid4())

    message = Message(
        id=str(uuid4()),
        session_id=session_id_str,
        content="test content",
        content_type="text/markdown",
        role=MessageRole.USER,
        kind=MessageKind.CHAT,
        persistent=True,
        status=MessageStatus.PENDING,
    )

    # Serialize to dict (like Celery does)
    message_dict = message.model_dump()
    assert isinstance(message_dict['session_id'], str)

    # Serialize to JSON
    message_json = message.model_dump_json()
    assert isinstance(message_json, str)

    # Deserialize back
    message_dict_from_json = json.loads(message_json)
    message_restored = Message(**message_dict_from_json)

    assert message_restored.session_id == session_id_str
    assert isinstance(message_restored.session_id, str)


def test_worker_request_with_string_session_id():
    """Test that WorkerMessageRequest accepts string session_id"""
    from fm_app.workers.v2.model import (
        WorkerMessageRequest,
        FlowTypeV2,
        MessageProcessingStrategy,
        ModelType,
        DBType,
    )

    session_id_str = str(uuid4())

    worker_request = WorkerMessageRequest(
        session_id=session_id_str,
        message_id=str(uuid4()),
        user="test_user",
        content="test content",
        content_type="text/markdown",
        kind=MessageKind.CHAT,
        flow=FlowTypeV2.DIRECT,
        strategy=MessageProcessingStrategy.SMART_ROUTING,
        model=ModelType.anthropic_default,
        db=DBType.v2,
    )

    assert worker_request.session_id == session_id_str
    assert isinstance(worker_request.session_id, str)

    # Test serialization (for Celery)
    request_dict = worker_request.model_dump()
    assert isinstance(request_dict['session_id'], str)

    # Test deserialization
    restored_request = WorkerMessageRequest(**request_dict)
    assert restored_request.session_id == session_id_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
