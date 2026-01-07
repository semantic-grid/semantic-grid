"""Shared Pydantic models for Semantic Grid v2."""

from sg_models.onboarding import (
    ColumnDescription,
    OnboardingPhase,
    OnboardingState,
    SchemaDescriptions,
    TableDescription,
    TableDescriptionStatus,
)
from sg_models.plan import PlanStep, QueryPlan
from sg_models.query import QueryMetadata, QueryResult
from sg_models.task import Task, TaskStatus
from sg_models.training import (
    CandidateRule,
    FeedbackLog,
    FeedbackType,
    PromptInstructions,
    QueryExample,
    QueryExamples,
    QueryFeedback,
)
from sg_models.ui import ChartSpec, ColumnSpec, GridSpec

__version__ = "0.1.0"

__all__ = [
    # Task
    "Task",
    "TaskStatus",
    # Plan
    "QueryPlan",
    "PlanStep",
    # Query
    "QueryResult",
    "QueryMetadata",
    # UI
    "GridSpec",
    "ColumnSpec",
    "ChartSpec",
    # Onboarding
    "OnboardingState",
    "OnboardingPhase",
    # Schema Descriptions
    "SchemaDescriptions",
    "TableDescription",
    "TableDescriptionStatus",
    "ColumnDescription",
    # Training
    "QueryExample",
    "QueryExamples",
    "QueryFeedback",
    "FeedbackLog",
    "FeedbackType",
    "CandidateRule",
    "PromptInstructions",
]
