"""Query training models for examples and feedback."""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class FeedbackType(str, Enum):
    """Type of feedback on generated SQL."""

    APPROVED = "approved"  # SQL was correct
    CORRECTED = "corrected"  # User provided corrected SQL
    REJECTED = "rejected"  # SQL was wrong, no correction provided


class QueryExample(BaseModel):
    """A query example for few-shot learning."""

    id: str = Field(..., description="Unique example ID")
    natural_language: str = Field(..., description="Natural language query")
    sql: str = Field(..., description="Correct SQL for the query")
    tables_used: list[str] = Field(default_factory=list, description="Tables referenced")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = Field(default=None, description="Who created this example")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    notes: str | None = Field(default=None, description="Additional notes")


class QueryFeedback(BaseModel):
    """Feedback record for SQL generation - used for rule distillation."""

    id: str = Field(..., description="Unique feedback ID")
    natural_language: str = Field(..., description="Original natural language query")
    generated_sql: str = Field(..., description="SQL that was generated")
    feedback_type: FeedbackType = Field(..., description="Type of feedback")
    corrected_sql: str | None = Field(default=None, description="User-provided correction")
    feedback_text: str | None = Field(
        default=None, description="User explanation of what was wrong"
    )
    tables_involved: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    distilled: bool = Field(default=False, description="Whether rules have been extracted")


class CandidateRule(BaseModel):
    """A business rule candidate extracted from feedback patterns."""

    id: str = Field(..., description="Unique rule ID")
    rule_text: str = Field(..., description="The rule in plain English")
    category: str = Field(..., description="Rule category")
    confidence: float = Field(default=0.0, description="Confidence score 0-1")
    evidence_count: int = Field(default=0, description="Number of supporting feedback records")
    source_feedback_ids: list[str] = Field(
        default_factory=list, description="Feedback IDs that led to this rule"
    )
    status: str = Field(default="pending", description="pending, approved, rejected")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QueryExamples(BaseModel):
    """Collection of query examples (query_examples.yaml)."""

    version: str = Field(default="1.0.0")
    provider_id: str = Field(..., description="Provider identifier")
    examples: list[QueryExample] = Field(default_factory=list)

    def get_example(self, example_id: str) -> QueryExample | None:
        """Get example by ID."""
        for ex in self.examples:
            if ex.id == example_id:
                return ex
        return None

    def add_example(self, example: QueryExample) -> None:
        """Add a new example."""
        self.examples.append(example)

    def count(self) -> int:
        """Count total examples."""
        return len(self.examples)


class FeedbackLog(BaseModel):
    """Collection of feedback records (feedback_log.yaml)."""

    version: str = Field(default="1.0.0")
    provider_id: str = Field(..., description="Provider identifier")
    feedback: list[QueryFeedback] = Field(default_factory=list)

    def add_feedback(self, fb: QueryFeedback) -> None:
        """Add a new feedback record."""
        self.feedback.append(fb)

    def get_undistilled(self) -> list[QueryFeedback]:
        """Get feedback records that haven't been distilled yet."""
        return [fb for fb in self.feedback if not fb.distilled]

    def get_corrections(self) -> list[QueryFeedback]:
        """Get only correction feedback (for rule distillation)."""
        return [fb for fb in self.feedback if fb.feedback_type == FeedbackType.CORRECTED]

    def count_by_type(self) -> dict[str, int]:
        """Count feedback by type."""
        counts: dict[str, int] = {}
        for fb in self.feedback:
            t = fb.feedback_type.value
            counts[t] = counts.get(t, 0) + 1
        return counts


class PromptInstructions(BaseModel):
    """Business rules / prompt instructions (prompt_instructions.yaml)."""

    version: str = Field(default="1.0.0")
    provider_id: str = Field(..., description="Provider identifier")
    rules: list[str] = Field(default_factory=list, description="List of business rules")
    candidate_rules: list[CandidateRule] = Field(
        default_factory=list, description="Rules pending approval"
    )

    def add_rule(self, rule: str) -> None:
        """Add an approved rule."""
        if rule not in self.rules:
            self.rules.append(rule)

    def get_pending_candidates(self) -> list[CandidateRule]:
        """Get candidate rules pending approval."""
        return [r for r in self.candidate_rules if r.status == "pending"]
