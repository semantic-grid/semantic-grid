"""
Simple unit tests for UUID to string conversion

These tests verify the conversion logic without importing the full app.
"""

from uuid import UUID, uuid4


def test_uuid_to_string_conversion():
    """Test basic UUID to string conversion"""
    session_id_uuid = uuid4()
    session_id_str = str(session_id_uuid)

    # Verify conversion
    assert isinstance(session_id_uuid, UUID)
    assert isinstance(session_id_str, str)
    assert session_id_str == str(session_id_uuid)

    # Verify string format (8-4-4-4-12 pattern)
    assert len(session_id_str) == 36
    assert session_id_str.count('-') == 4


def test_uuid_string_roundtrip():
    """Test converting UUID to string and back"""
    original_uuid = uuid4()
    uuid_as_string = str(original_uuid)
    reconstructed_uuid = UUID(uuid_as_string)

    assert original_uuid == reconstructed_uuid


def test_database_params_with_uuid():
    """Simulate how we pass UUIDs to database queries"""
    session_id = uuid4()

    # What we do in db_v2.py: convert to string for params
    params = {
        "session_id": str(session_id),
        "user_owner": "test_user",
    }

    assert isinstance(params["session_id"], str)
    assert UUID(params["session_id"]) == session_id


def test_pydantic_model_simulation():
    """Simulate Pydantic model creation with string session_id"""
    from pydantic import BaseModel, ValidationError
    import pytest

    class MessageSimulation(BaseModel):
        session_id: str
        content: str

    # This should work
    msg1 = MessageSimulation(
        session_id=str(uuid4()),
        content="test"
    )
    assert isinstance(msg1.session_id, str)

    # This should fail (UUID object not accepted for str field)
    with pytest.raises(ValidationError):
        MessageSimulation(
            session_id=uuid4(),  # UUID object, not string
            content="test"
        )


def test_worker_serialization_simulation():
    """Simulate how worker requests are serialized"""
    import json

    session_id = uuid4()

    # Create a dict like WorkerMessageRequest.model_dump() does
    worker_request = {
        "session_id": str(session_id),  # Must be string
        "message_id": str(uuid4()),
        "user": "test_user",
        "content": "test content",
    }

    # Serialize through JSON (like Celery does)
    json_str = json.dumps(worker_request)

    # Deserialize
    restored = json.loads(json_str)

    # Verify session_id is still a string
    assert isinstance(restored["session_id"], str)
    assert UUID(restored["session_id"]) == session_id


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
