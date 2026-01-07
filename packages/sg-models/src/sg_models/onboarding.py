"""Onboarding state models for database configuration workflow."""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class OnboardingPhase(str, Enum):
    """Phase of the onboarding workflow."""

    NOT_STARTED = "not_started"
    INIT = "init"
    SCHEMA = "schema"
    DOMAIN = "domain"
    BUSINESS_RULES = "business_rules"
    QUERY_TRAINING = "query_training"
    COMPLETE = "complete"


class TableDescriptionStatus(str, Enum):
    """Status of a table's description."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    SKIPPED = "skipped"
    REMOVED = "removed"  # Table no longer exists in database


# =============================================================================
# Schema Descriptions (stored in schema_descriptions.yaml)
# =============================================================================


class ColumnDescription(BaseModel):
    """Description of a database column."""

    name: str = Field(..., description="Column name")
    type: str | None = Field(default=None, description="Column data type")
    description: str | None = Field(default=None, description="Column description")


class TableDescription(BaseModel):
    """Description of a database table."""

    model_config = {"populate_by_name": True}

    name: str = Field(..., description="Table name (without schema)")
    schema_name: str = Field(default="public", description="Schema name", alias="schema")
    catalog_name: str | None = Field(
        default=None, description="Catalog name (for Trino 3-level hierarchy)", alias="catalog"
    )
    full_name: str | None = Field(default=None, description="Fully qualified name")
    description: str | None = Field(default=None, description="Table description")
    status: TableDescriptionStatus = Field(
        default=TableDescriptionStatus.PENDING, description="Description status"
    )
    columns: list[ColumnDescription] = Field(
        default_factory=list, description="Column descriptions"
    )

    def get_full_name(self) -> str:
        """Get the fully qualified table name."""
        if self.full_name:
            return self.full_name
        if self.catalog_name:
            return f"{self.catalog_name}.{self.schema_name}.{self.name}"
        return f"{self.schema_name}.{self.name}"


class SchemaDescriptions(BaseModel):
    """Schema descriptions file (schema_descriptions.yaml)."""

    version: str = Field(default="1.0.0")
    provider_id: str = Field(..., description="Provider identifier")
    dialect: str | None = Field(default=None, description="SQL dialect")
    generated_at: datetime | None = Field(default=None)
    tables: list[TableDescription] = Field(default_factory=list)

    def get_table(self, full_name: str) -> TableDescription | None:
        """Get table by full name."""
        for t in self.tables:
            if t.full_name == full_name:
                return t
        return None

    def get_described_tables(self) -> list[str]:
        """Get list of table names that have been described."""
        return [
            t.full_name or f"{t.schema_name}.{t.name}"
            for t in self.tables
            if t.status in (TableDescriptionStatus.APPROVED, TableDescriptionStatus.SKIPPED)
        ]

    def count_by_status(self) -> dict[str, int]:
        """Count tables by status."""
        counts: dict[str, int] = {}
        for t in self.tables:
            status = t.status.value
            counts[status] = counts.get(status, 0) + 1
        return counts


# =============================================================================
# Onboarding State (stored in onboarding_state.yaml) - Progress tracking only
# =============================================================================


class CandidateRule(BaseModel):
    """A business rule candidate from distillation."""

    rule_id: str = Field(..., description="Unique rule identifier")
    rule_text: str = Field(..., description="The rule in plain English")
    category: str = Field(..., description="Rule category (synonym, logic, filter, etc.)")
    confidence: float = Field(default=0.0, description="Confidence score 0-1")
    evidence_count: int = Field(default=0, description="Number of supporting examples")
    status: str = Field(default="pending", description="pending, approved, rejected")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OnboardingState(BaseModel):
    """Persisted state for the onboarding workflow (progress tracking only)."""

    provider_id: str = Field(..., description="Provider identifier")
    phase: OnboardingPhase = Field(
        default=OnboardingPhase.NOT_STARTED, description="Current phase"
    )

    # Phase 0: Init
    database_url_configured: bool = Field(default=False)
    connection_verified: bool = Field(default=False)
    dialect_detected: str | None = Field(default=None, description="Detected SQL dialect")
    catalogs_discovered: list[str] = Field(
        default_factory=list, description="Discovered catalogs (Trino 3-level hierarchy)"
    )
    schemas_discovered: list[str] = Field(default_factory=list)
    tables_discovered: list[str] = Field(default_factory=list)

    # Phase 1: Schema - progress only (descriptions in schema_descriptions.yaml)
    tables_total: int = Field(default=0)
    current_table: str | None = Field(default=None)

    # Phase 2: Domain
    domain_model_generated: bool = Field(default=False)
    domain_model_approved: bool = Field(default=False)
    pending_domain_model: str | None = Field(default=None)

    # Phase 3: Business Rules
    entities_total: int = Field(default=0)
    entities_interviewed: int = Field(default=0)
    rules_captured: int = Field(default=0)
    current_entity: str | None = Field(default=None)
    pending_rules: list[CandidateRule] = Field(default_factory=list)

    # Phase 4: Query Training
    examples_added: int = Field(default=0)

    # Timestamps
    started_at: datetime | None = Field(default=None)
    last_updated_at: datetime | None = Field(default=None)

    def progress_percentage(self, tables_described: int = 0) -> float:
        """Calculate overall progress as a percentage."""
        # Base progress when entering each phase
        phase_weights = {
            OnboardingPhase.NOT_STARTED: 0,
            OnboardingPhase.INIT: 10,
            OnboardingPhase.SCHEMA: 10,  # Starts at 10, progresses to 40
            OnboardingPhase.DOMAIN: 40,  # Starts at 40, progresses to 60
            OnboardingPhase.BUSINESS_RULES: 60,
            OnboardingPhase.QUERY_TRAINING: 80,
            OnboardingPhase.COMPLETE: 100,
        }

        base = phase_weights.get(self.phase, 0)

        # Add sub-progress within phases
        if self.phase == OnboardingPhase.SCHEMA and self.tables_total > 0:
            sub_progress = (tables_described / self.tables_total) * 30  # 10 -> 40
            return base + sub_progress
        elif self.phase == OnboardingPhase.BUSINESS_RULES and self.entities_total > 0:
            sub_progress = (self.entities_interviewed / self.entities_total) * 20  # 60 -> 80
            return base + sub_progress

        return base

    def next_action(self) -> str:
        """Get the recommended next action."""
        if self.phase == OnboardingPhase.NOT_STARTED:
            return "Call onboarding_start to begin"
        elif self.phase == OnboardingPhase.INIT:
            return "Waiting for connection verification"
        elif self.phase == OnboardingPhase.SCHEMA:
            return "Call onboarding_next to describe next table"
        elif self.phase == OnboardingPhase.DOMAIN:
            if self.pending_domain_model:
                return "Approve or edit the domain model"
            return "Call domain_generate to create domain model"
        elif self.phase == OnboardingPhase.BUSINESS_RULES:
            if self.pending_rules:
                return "Review pending business rules"
            return "Business rules phase (not yet implemented)"
        elif self.phase == OnboardingPhase.QUERY_TRAINING:
            return "Add query examples or run distillation"
        else:
            return "Onboarding complete"
