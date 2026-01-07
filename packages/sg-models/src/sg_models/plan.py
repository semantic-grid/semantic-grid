"""Query planning models."""

from enum import Enum

from pydantic import BaseModel, Field


class PlanStepType(str, Enum):
    """Type of step in a query plan."""

    SELECT_TABLES = "select_tables"
    JOIN_TABLES = "join_tables"
    FILTER_DATA = "filter_data"
    AGGREGATE = "aggregate"
    SORT = "sort"
    LIMIT = "limit"
    TRANSFORM = "transform"


class PlanStep(BaseModel):
    """A single step in a query plan."""

    step_number: int = Field(..., description="Step order in the plan")
    step_type: PlanStepType = Field(..., description="Type of operation")
    description: str = Field(..., description="Human-readable description of the step")
    tables: list[str] = Field(default_factory=list, description="Tables involved in this step")
    columns: list[str] = Field(default_factory=list, description="Columns involved")
    conditions: list[str] = Field(default_factory=list, description="Filter conditions")
    reasoning: str | None = Field(default=None, description="Why this step is needed")


class QueryPlan(BaseModel):
    """A plan for executing a natural language query."""

    intent: str = Field(..., description="Original user intent")
    steps: list[PlanStep] = Field(default_factory=list, description="Ordered list of plan steps")
    tables_used: list[str] = Field(default_factory=list, description="All tables to be queried")
    estimated_complexity: str = Field(
        default="medium", description="Estimated query complexity: low, medium, high"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Potential issues or clarifications needed"
    )
    approved: bool = Field(default=False, description="Whether the plan has been approved")
    approval_notes: str | None = Field(default=None, description="Notes from approval")

    def summary(self) -> str:
        """Generate a human-readable summary of the plan."""
        lines = [f"Plan for: {self.intent}", f"Tables: {', '.join(self.tables_used)}", "Steps:"]
        for step in self.steps:
            lines.append(f"  {step.step_number}. {step.description}")
        if self.warnings:
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")
        return "\n".join(lines)
