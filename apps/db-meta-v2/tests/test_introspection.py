"""Tests for database introspection functions."""

from unittest.mock import MagicMock, patch

import pytest

from db_meta_v2.db.introspection import get_tables


class TestGetTables:
    """Tests for get_tables function."""

    @pytest.fixture
    def mock_trino_engine(self):
        """Create a mock Trino engine."""
        engine = MagicMock()
        engine.dialect.name = "Trino"  # Mixed case to test .lower() handling
        return engine

    @pytest.fixture
    def mock_postgres_engine(self):
        """Create a mock PostgreSQL engine."""
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        return engine

    def test_trino_with_catalog_and_schema(self, mock_trino_engine):
        """Test Trino table discovery with both catalog and schema."""
        with patch("db_meta_v2.db.introspection.get_engine", return_value=mock_trino_engine):
            # Mock the connection and execute
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [("users",), ("orders",), ("products",)]
            mock_conn.execute.return_value = mock_result
            mock_trino_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_trino_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

            tables = get_tables(schema="public", catalog="dwh")

            assert len(tables) == 3
            assert tables[0]["name"] == "users"
            assert tables[0]["schema"] == "public"
            assert tables[0]["catalog"] == "dwh"
            assert tables[0]["full_name"] == "dwh.public.users"

            # Verify execute was called (SQL is wrapped in TextClause)
            mock_conn.execute.assert_called_once()

    def test_trino_with_catalog_only(self, mock_trino_engine):
        """Test Trino table discovery with catalog only (iterates schemas)."""
        with patch("db_meta_v2.db.introspection.get_engine", return_value=mock_trino_engine):
            mock_conn = MagicMock()

            # First call: SHOW SCHEMAS FROM dwh
            schema_result = MagicMock()
            schema_result.fetchall.return_value = [
                ("public",),
                ("analytics",),
                ("information_schema",),  # Should be filtered out
            ]

            # Second call: SHOW TABLES FROM dwh.public
            public_tables_result = MagicMock()
            public_tables_result.fetchall.return_value = [("users",), ("orders",)]

            # Third call: SHOW TABLES FROM dwh.analytics
            analytics_tables_result = MagicMock()
            analytics_tables_result.fetchall.return_value = [("events",), ("metrics",)]

            mock_conn.execute.side_effect = [
                schema_result,
                public_tables_result,
                analytics_tables_result,
            ]

            mock_trino_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_trino_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

            tables = get_tables(catalog="dwh")

            # Should find 4 tables total (2 from public + 2 from analytics)
            assert len(tables) == 4

            # Check public schema tables
            public_tables = [t for t in tables if t["schema"] == "public"]
            assert len(public_tables) == 2
            assert public_tables[0]["full_name"] == "dwh.public.users"

            # Check analytics schema tables
            analytics_tables = [t for t in tables if t["schema"] == "analytics"]
            assert len(analytics_tables) == 2
            assert analytics_tables[0]["full_name"] == "dwh.analytics.events"

            # All should have correct catalog
            assert all(t["catalog"] == "dwh" for t in tables)

    def test_trino_catalog_only_handles_schema_errors(self, mock_trino_engine):
        """Test that catalog-only discovery continues when a schema errors."""
        with patch("db_meta_v2.db.introspection.get_engine", return_value=mock_trino_engine):
            mock_conn = MagicMock()

            # First call: SHOW SCHEMAS FROM dwh
            schema_result = MagicMock()
            schema_result.fetchall.return_value = [("public",), ("broken_schema",)]

            # Second call: SHOW TABLES FROM dwh.public - succeeds
            public_tables_result = MagicMock()
            public_tables_result.fetchall.return_value = [("users",)]

            # Third call: SHOW TABLES FROM dwh.broken_schema - throws exception
            mock_conn.execute.side_effect = [
                schema_result,
                public_tables_result,
                Exception("Permission denied"),
            ]

            mock_trino_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_trino_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

            # Should not raise, should return tables from public only
            tables = get_tables(catalog="dwh")

            assert len(tables) == 1
            assert tables[0]["name"] == "users"
            assert tables[0]["schema"] == "public"

    def test_trino_dialect_case_insensitive(self):
        """Test that dialect detection handles mixed case (e.g., 'Trino' vs 'trino')."""
        # Test with uppercase
        engine = MagicMock()
        engine.dialect.name = "TRINO"

        with patch("db_meta_v2.db.introspection.get_engine", return_value=engine):
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [("test_table",)]
            mock_conn.execute.return_value = mock_result
            engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            engine.connect.return_value.__exit__ = MagicMock(return_value=False)

            tables = get_tables(schema="public", catalog="dwh")

            # Should hit the Trino branch, not the generic SQLAlchemy branch
            assert len(tables) == 1
            # Verify execute was called (SQL is wrapped in TextClause)
            mock_conn.execute.assert_called_once()

    def test_postgresql_uses_inspector(self, mock_postgres_engine):
        """Test that PostgreSQL uses SQLAlchemy inspector."""
        with (
            patch("db_meta_v2.db.introspection.get_engine", return_value=mock_postgres_engine),
            patch("db_meta_v2.db.introspection.inspect") as mock_inspect,
        ):
            mock_inspector = MagicMock()
            mock_inspector.get_table_names.return_value = ["users", "orders"]
            mock_inspector.get_view_names.return_value = ["user_stats"]
            mock_inspect.return_value = mock_inspector

            tables = get_tables(schema="public")

            assert len(tables) == 3
            # Check that inspector was used
            mock_inspect.assert_called_once_with(mock_postgres_engine)
            mock_inspector.get_table_names.assert_called_once_with(schema="public")

            # Check table types
            table_types = {t["name"]: t["type"] for t in tables}
            assert table_types["users"] == "table"
            assert table_types["user_stats"] == "view"

    def test_no_catalog_no_schema_uses_inspector(self, mock_postgres_engine):
        """Test that missing catalog/schema uses SQLAlchemy inspector."""
        with (
            patch("db_meta_v2.db.introspection.get_engine", return_value=mock_postgres_engine),
            patch("db_meta_v2.db.introspection.inspect") as mock_inspect,
        ):
            mock_inspector = MagicMock()
            mock_inspector.get_table_names.return_value = ["test"]
            mock_inspector.get_view_names.return_value = []
            mock_inspect.return_value = mock_inspector

            tables = get_tables()

            assert len(tables) == 1
            assert tables[0]["full_name"] == "test"  # No prefix when no schema/catalog
