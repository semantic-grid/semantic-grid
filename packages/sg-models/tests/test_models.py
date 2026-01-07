"""Tests for sg-models."""

from sg_models import (
    ChartSpec,
    ColumnSpec,
    GridSpec,
    OnboardingPhase,
    OnboardingState,
    PlanStep,
    QueryMetadata,
    QueryPlan,
    QueryResult,
    Task,
    TaskStatus,
)
from sg_models.plan import PlanStepType
from sg_models.ui import ChartType, ColumnFormatter


def test_task_creation():
    """Test Task model creation."""
    task = Task(id="test-1", name="Test Task")
    assert task.id == "test-1"
    assert task.name == "Test Task"
    assert task.status == TaskStatus.PENDING


def test_query_plan_summary():
    """Test QueryPlan summary generation."""
    plan = QueryPlan(
        intent="Show top users",
        tables_used=["users", "orders"],
        steps=[
            PlanStep(
                step_number=1,
                step_type=PlanStepType.SELECT_TABLES,
                description="Select from users and orders tables",
            ),
            PlanStep(
                step_number=2,
                step_type=PlanStepType.AGGREGATE,
                description="Count orders per user",
            ),
        ],
    )
    summary = plan.summary()
    assert "Show top users" in summary
    assert "users" in summary
    assert "orders" in summary


def test_query_result_serialization():
    """Test QueryResult can be serialized."""
    result = QueryResult(
        data=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
        columns=["id", "name"],
        column_types={"id": "INTEGER", "name": "VARCHAR"},
        metadata=QueryMetadata(
            query_id="q-123",
            sql="SELECT id, name FROM users",
        ),
    )
    data = result.to_dict()
    assert len(data["data"]) == 2
    assert data["columns"] == ["id", "name"]


def test_grid_spec():
    """Test GridSpec model."""
    spec = GridSpec(
        columns=[
            ColumnSpec(field="id", formatter=ColumnFormatter.NUMBER),
            ColumnSpec(field="balance", formatter=ColumnFormatter.CURRENCY, decimals=2),
        ],
        chart_suggestion=ChartSpec(
            chart_type=ChartType.BAR,
            x_field="name",
            y_field="balance",
        ),
    )
    assert len(spec.columns) == 2
    assert spec.columns[1].formatter == ColumnFormatter.CURRENCY
    assert spec.chart_suggestion.chart_type == ChartType.BAR


def test_onboarding_state_progress():
    """Test OnboardingState progress calculation."""
    state = OnboardingState(
        provider_id="test",
        phase=OnboardingPhase.SCHEMA,
        tables_total=10,
        tables_described=5,
    )
    progress = state.progress_percentage()
    # Should be between INIT (10) and DOMAIN (40), inclusive
    assert 10 < progress <= 40


def test_onboarding_state_next_action():
    """Test OnboardingState next action."""
    state = OnboardingState(
        provider_id="test",
        phase=OnboardingPhase.NOT_STARTED,
    )
    assert "onboarding_start" in state.next_action()

    state.phase = OnboardingPhase.SCHEMA
    state.pending_description = "Test description"
    state.current_table = "users"
    assert "users" in state.next_action()
