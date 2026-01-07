"""Task models for workflow tracking."""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a task in the workflow."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    """A task in a workflow."""

    id: str = Field(..., description="Unique task identifier")
    name: str = Field(..., description="Human-readable task name")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current task status")
    description: str | None = Field(default=None, description="Task description")

    # Timing
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    # Results
    result: dict | None = Field(default=None, description="Task result data")
    error: str | None = Field(default=None, description="Error message if failed")

    # Metadata
    metadata: dict = Field(default_factory=dict, description="Additional task metadata")
