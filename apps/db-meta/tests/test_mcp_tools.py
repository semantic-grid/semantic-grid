"""
Tests for db-meta MCP tools.

Tests all MCP endpoints:
1. prompt_items - Legacy combined prompt items
2. prompt_items_v2 - Structured prompt items with lineage
3. preflight_query - SQL validation
4. validate_plan - Query plan validation

These tests verify:
- Correct response structure
- Item type filtering
- Domain model loading
- Schema validation
- SQL preflight checks
"""

import pathlib
from unittest.mock import patch, MagicMock

import pytest

from dbmeta_app.api.model import (
    GetPromptItemsRequestV2,
    GetPromptModel,
    PromptItem,
    PromptItemType,
    PromptsSetModel,
    TestSqlModel,
    ValidatePlanRequest,
)
from dbmeta_app.api.routes import (
    prompt_items,
    prompt_items_v2,
    preflight_query,
    validate_plan,
)
from dbmeta_app.prompt_items.domain_model import get_domain_model_item


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_settings():
    """Mock settings for tests."""
    with patch("dbmeta_app.api.routes.get_settings") as mock:
        settings = MagicMock()
        settings.database_wh_db = "wh_v2"
        settings.packs_resources_dir = str(
            pathlib.Path(__file__).parent.parent.parent.parent / "packages"
        )
        settings.client = "wifiqm"
        settings.env = "prod"
        mock.return_value = settings
        yield settings


@pytest.fixture
def mock_domain_model_settings():
    """Mock settings specifically for domain model tests."""
    with patch("dbmeta_app.prompt_items.domain_model.get_settings") as mock:
        settings = MagicMock()
        settings.packs_resources_dir = str(
            pathlib.Path(__file__).parent.parent.parent.parent / "packages"
        )
        settings.client = "wifiqm"
        settings.env = "prod"
        mock.return_value = settings
        yield settings


# ============================================================================
# prompt_items_v2 Tests
# ============================================================================


class TestPromptItemsV2:
    """Tests for prompt_items_v2 MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_prompts_set_model(self, mock_settings):
        """Test that prompt_items_v2 returns a PromptsSetModel."""
        req = GetPromptItemsRequestV2(
            user_request="show all tables",
            db="wh_v2",
            items=[PromptItemType.instruction],
        )

        with patch(
            "dbmeta_app.api.routes.get_prompt_instructions_item"
        ) as mock_instructions:
            mock_instructions.return_value = PromptItem(
                text="Test instructions",
                prompt_item_type=PromptItemType.instruction,
                score=1000,
                content_hash="abc123",
            )

            result = await prompt_items_v2(req)

            assert isinstance(result, PromptsSetModel)
            assert result.source == "db_meta"
            assert result.version == "2.0.0"
            assert len(result.prompt_items) == 1

    @pytest.mark.asyncio
    async def test_filters_by_requested_items(self, mock_settings):
        """Test that only requested item types are returned."""
        req = GetPromptItemsRequestV2(
            user_request="test query",
            db="wh_v2",
            items=[PromptItemType.instruction, PromptItemType.sql_dialect],
        )

        with patch(
            "dbmeta_app.api.routes.get_prompt_instructions_item"
        ) as mock_inst, patch(
            "dbmeta_app.api.routes.get_sql_dialect_item"
        ) as mock_dialect:
            mock_inst.return_value = PromptItem(
                text="Instructions",
                prompt_item_type=PromptItemType.instruction,
                score=1000,
            )
            mock_dialect.return_value = PromptItem(
                text="SQL Dialect",
                prompt_item_type=PromptItemType.sql_dialect,
                score=500,
            )

            result = await prompt_items_v2(req)

            assert len(result.prompt_items) == 2
            types = {item.prompt_item_type for item in result.prompt_items}
            assert types == {PromptItemType.instruction, PromptItemType.sql_dialect}

    @pytest.mark.asyncio
    async def test_includes_domain_model_when_requested(self, mock_settings):
        """Test that domain model is included when requested and exists."""
        req = GetPromptItemsRequestV2(
            user_request="test",
            db="wh_v2",
            items=[PromptItemType.domain_model],
        )

        with patch(
            "dbmeta_app.api.routes.get_domain_model_item"
        ) as mock_domain:
            mock_domain.return_value = PromptItem(
                text="# Domain Model\nEntity relationships...",
                prompt_item_type=PromptItemType.domain_model,
                score=90000,
                content_hash="domain123",
                metadata={"profile": "wh_v2"},
            )

            result = await prompt_items_v2(req)

            assert len(result.prompt_items) == 1
            assert result.prompt_items[0].prompt_item_type == PromptItemType.domain_model
            mock_domain.assert_called_once_with(profile="wh_v2")

    @pytest.mark.asyncio
    async def test_excludes_domain_model_when_none(self, mock_settings):
        """Test that domain model is excluded when it doesn't exist."""
        req = GetPromptItemsRequestV2(
            user_request="test",
            db="wh_v2",
            items=[PromptItemType.domain_model, PromptItemType.instruction],
        )

        with patch(
            "dbmeta_app.api.routes.get_domain_model_item"
        ) as mock_domain, patch(
            "dbmeta_app.api.routes.get_prompt_instructions_item"
        ) as mock_inst:
            mock_domain.return_value = None  # No domain model
            mock_inst.return_value = PromptItem(
                text="Instructions",
                prompt_item_type=PromptItemType.instruction,
                score=1000,
            )

            result = await prompt_items_v2(req)

            # Should only have instruction, not domain_model
            assert len(result.prompt_items) == 1
            assert result.prompt_items[0].prompt_item_type == PromptItemType.instruction

    @pytest.mark.asyncio
    async def test_all_item_types(self, mock_settings):
        """Test requesting all item types."""
        req = GetPromptItemsRequestV2(
            user_request="test query",
            db="wh_v2",
            items=[
                PromptItemType.db_struct,
                PromptItemType.query_example,
                PromptItemType.instruction,
                PromptItemType.sql_dialect,
                PromptItemType.domain_model,
            ],
        )

        with patch(
            "dbmeta_app.api.routes.get_schema_prompt_item"
        ) as mock_schema, patch(
            "dbmeta_app.api.routes.get_query_example_prompt_item"
        ) as mock_examples, patch(
            "dbmeta_app.api.routes.get_prompt_instructions_item"
        ) as mock_inst, patch(
            "dbmeta_app.api.routes.get_sql_dialect_item"
        ) as mock_dialect, patch(
            "dbmeta_app.api.routes.get_domain_model_item"
        ) as mock_domain:
            mock_schema.return_value = PromptItem(
                text="Schema", prompt_item_type=PromptItemType.db_struct, score=100
            )
            mock_examples.return_value = PromptItem(
                text="Examples", prompt_item_type=PromptItemType.query_example, score=90
            )
            mock_inst.return_value = PromptItem(
                text="Instructions", prompt_item_type=PromptItemType.instruction, score=80
            )
            mock_dialect.return_value = PromptItem(
                text="Dialect", prompt_item_type=PromptItemType.sql_dialect, score=70
            )
            mock_domain.return_value = PromptItem(
                text="Domain", prompt_item_type=PromptItemType.domain_model, score=90000
            )

            result = await prompt_items_v2(req)

            assert len(result.prompt_items) == 5

    @pytest.mark.asyncio
    async def test_uses_specified_db(self):
        """Test that specified db is used when provided in request."""
        req = GetPromptItemsRequestV2(
            user_request="test",
            db="wh_v2",  # Explicitly specified
            items=[PromptItemType.instruction],
        )

        with patch(
            "dbmeta_app.api.routes.get_prompt_instructions_item"
        ) as mock_inst:
            mock_inst.return_value = PromptItem(
                text="Instructions",
                prompt_item_type=PromptItemType.instruction,
                score=1000,
            )

            await prompt_items_v2(req)

            # Should use specified db
            mock_inst.assert_called_once_with(profile="wh_v2")


# ============================================================================
# Domain Model Tests
# ============================================================================


class TestDomainModel:
    """Tests for domain model loading."""

    def test_get_domain_model_item_returns_prompt_item(self, mock_domain_model_settings):
        """Test that get_domain_model_item returns a PromptItem when file exists."""
        with patch(
            "dbmeta_app.prompt_items.domain_model.assemble_effective_tree"
        ) as mock_tree:
            # Create a temp file for the domain model
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write("# Domain Model\n\nTest content")
                temp_path = f.name

            mock_tree.return_value = {
                "resources/domain_model.md": temp_path
            }

            result = get_domain_model_item(profile="wh_v2")

            assert result is not None
            assert isinstance(result, PromptItem)
            assert result.prompt_item_type == PromptItemType.domain_model
            assert "Domain Model" in result.text
            assert result.content_hash is not None
            assert result.score == 90000

            # Cleanup
            import os
            os.unlink(temp_path)

    def test_get_domain_model_item_returns_none_when_missing(
        self, mock_domain_model_settings
    ):
        """Test that get_domain_model_item returns None when file doesn't exist."""
        with patch(
            "dbmeta_app.prompt_items.domain_model.assemble_effective_tree"
        ) as mock_tree:
            mock_tree.return_value = {}  # No domain_model.md in tree

            result = get_domain_model_item(profile="wh_v2")

            assert result is None

    def test_get_domain_model_item_returns_none_for_empty_file(
        self, mock_domain_model_settings
    ):
        """Test that get_domain_model_item returns None for empty file."""
        with patch(
            "dbmeta_app.prompt_items.domain_model.assemble_effective_tree"
        ) as mock_tree:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write("   \n\n   ")  # Only whitespace
                temp_path = f.name

            mock_tree.return_value = {
                "resources/domain_model.md": temp_path
            }

            result = get_domain_model_item(profile="wh_v2")

            assert result is None

            # Cleanup
            import os
            os.unlink(temp_path)


# ============================================================================
# preflight_query Tests
# ============================================================================


class TestPreflightQuery:
    """Tests for preflight_query MCP tool."""

    @pytest.mark.asyncio
    async def test_valid_query_returns_explanation(self):
        """Test that valid SQL returns explanation."""
        req = TestSqlModel(sql="SELECT 1")

        with patch("dbmeta_app.api.routes.query_preflight") as mock_preflight:
            mock_preflight.return_value = MagicMock(
                explanation=["Query plan details..."],
                error=None,
            )

            result = await preflight_query(req)

            assert result.explanation is not None
            assert result.error is None

    @pytest.mark.asyncio
    async def test_invalid_query_returns_error(self):
        """Test that invalid SQL returns error."""
        req = TestSqlModel(sql="SELECT * FROM nonexistent_table")

        with patch("dbmeta_app.api.routes.query_preflight") as mock_preflight:
            mock_preflight.return_value = MagicMock(
                explanation=None,
                error="Table 'nonexistent_table' does not exist",
            )

            result = await preflight_query(req)

            assert result.error is not None
            assert "nonexistent_table" in result.error


# ============================================================================
# validate_plan Tests
# ============================================================================


class TestValidatePlan:
    """Tests for validate_plan MCP tool."""

    @pytest.mark.asyncio
    async def test_valid_plan_returns_valid_true(self):
        """Test that valid plan returns valid=True."""
        req = ValidatePlanRequest(
            tables=["dwh.public.subs"],
            columns_referenced=["subscriber_id", "plan_name"],
        )

        with patch(
            "dbmeta_app.api.routes.validate_plan_against_schema"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": True,
                "errors": [],
            }

            result = await validate_plan(req)

            assert result.valid is True
            assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_invalid_table_returns_error(self):
        """Test that invalid table returns validation error."""
        req = ValidatePlanRequest(
            tables=["dwh.public.nonexistent"],
            columns_referenced=["id"],
        )

        with patch(
            "dbmeta_app.api.routes.validate_plan_against_schema"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": False,
                "errors": [
                    {
                        "error_type": "missing_table",
                        "name": "dwh.public.nonexistent",
                        "suggestion": "dwh.public.subs",
                    }
                ],
                "available_tables": ["dwh.public.subs", "dwh.public.cdr_agg_day"],
            }

            result = await validate_plan(req)

            assert result.valid is False
            assert len(result.errors) == 1
            assert result.errors[0].error_type == "missing_table"
            assert result.available_tables is not None

    @pytest.mark.asyncio
    async def test_invalid_column_returns_error(self):
        """Test that invalid column returns validation error."""
        req = ValidatePlanRequest(
            tables=["dwh.public.subs"],
            columns_referenced=["nonexistent_column"],
        )

        with patch(
            "dbmeta_app.api.routes.validate_plan_against_schema"
        ) as mock_validate:
            mock_validate.return_value = {
                "valid": False,
                "errors": [
                    {
                        "error_type": "missing_column",
                        "name": "nonexistent_column",
                        "suggestion": "subscriber_id",
                    }
                ],
            }

            result = await validate_plan(req)

            assert result.valid is False
            assert len(result.errors) == 1
            assert result.errors[0].error_type == "missing_column"


# ============================================================================
# prompt_items (Legacy) Tests
# ============================================================================


class TestPromptItemsLegacy:
    """Tests for legacy prompt_items MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_combined_string(self, mock_settings):
        """Test that prompt_items returns a combined string."""
        req = GetPromptModel(user_request="show tables", db="wh_v2")

        with patch(
            "dbmeta_app.api.routes.get_schema_prompt_item"
        ) as mock_schema, patch(
            "dbmeta_app.api.routes.get_query_example_prompt_item"
        ) as mock_examples, patch(
            "dbmeta_app.api.routes.get_prompt_instructions_item"
        ) as mock_inst, patch(
            "dbmeta_app.api.routes.get_sql_dialect_item"
        ) as mock_dialect:
            mock_schema.return_value = PromptItem(
                text="Schema info", prompt_item_type=PromptItemType.db_struct, score=100
            )
            mock_examples.return_value = PromptItem(
                text="Examples", prompt_item_type=PromptItemType.query_example, score=90
            )
            mock_inst.return_value = PromptItem(
                text="Instructions", prompt_item_type=PromptItemType.instruction, score=80
            )
            mock_dialect.return_value = PromptItem(
                text="Dialect", prompt_item_type=PromptItemType.sql_dialect, score=70
            )

            result = await prompt_items(req)

            assert isinstance(result, str)
            assert "Schema info" in result
            assert "Examples" in result
            assert "Instructions" in result
            assert "Dialect" in result


# ============================================================================
# Integration Tests (require actual files)
# ============================================================================


class TestIntegration:
    """Integration tests that use actual resource files."""

    def test_domain_model_file_exists_for_wifiqm(self):
        """Test that domain_model.md exists in wifiqm client config."""
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent
        domain_model_path = (
            repo_root
            / "packages/client-configs/wifiqm/prod/dbmeta_app/overlays/resources/domain_model.md"
        )

        assert domain_model_path.exists(), f"Domain model not found at {domain_model_path}"

        content = domain_model_path.read_text()
        assert len(content) > 100, "Domain model file seems too short"
        assert "Entity" in content or "Table" in content, "Domain model should describe entities"

    def test_prompt_instructions_file_exists(self):
        """Test that prompt_instructions.yaml exists."""
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent
        instructions_path = (
            repo_root
            / "packages/client-configs/wifiqm/prod/dbmeta_app/overlays/resources/prompt_instructions.yaml"
        )

        assert instructions_path.exists(), f"Instructions not found at {instructions_path}"

    def test_schema_descriptions_file_exists(self):
        """Test that schema_descriptions.yaml exists."""
        repo_root = pathlib.Path(__file__).parent.parent.parent.parent
        schema_path = (
            repo_root
            / "packages/client-configs/wifiqm/prod/dbmeta_app/overlays/resources/schema_descriptions.yaml"
        )

        assert schema_path.exists(), f"Schema descriptions not found at {schema_path}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
