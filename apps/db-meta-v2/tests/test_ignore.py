"""Tests for .dbmetaignore pattern matching."""


from db_meta_v2.onboarding.ignore import IgnorePatterns, get_default_ignore_content


class TestIgnorePatterns:
    """Tests for IgnorePatterns class."""

    def test_default_patterns_loaded(self):
        """Default patterns should include common system schemas."""
        ignore = IgnorePatterns()
        assert ignore.should_ignore("information_schema")
        assert ignore.should_ignore("pg_catalog")
        assert ignore.should_ignore("django_migrations")
        assert ignore.should_ignore("auth_user")

    def test_custom_patterns(self):
        """Custom patterns should work."""
        ignore = IgnorePatterns(["test_*", "staging_*"])
        assert ignore.should_ignore("test_table")
        assert ignore.should_ignore("staging_data")
        assert not ignore.should_ignore("production_data")

    def test_wildcard_patterns(self):
        """Wildcard patterns should match correctly."""
        ignore = IgnorePatterns(["django_*", "_*", "tmp_*"])
        assert ignore.should_ignore("django_migrations")
        assert ignore.should_ignore("django_session")
        assert ignore.should_ignore("_internal")
        assert ignore.should_ignore("tmp_cache")
        assert not ignore.should_ignore("users")
        assert not ignore.should_ignore("orders")

    def test_exact_match(self):
        """Exact patterns should only match exact names."""
        ignore = IgnorePatterns(["system", "mysql"])
        assert ignore.should_ignore("system")
        assert ignore.should_ignore("mysql")
        assert not ignore.should_ignore("system_logs")
        assert not ignore.should_ignore("mysql_data")

    def test_case_insensitive(self):
        """Matching should be case-insensitive."""
        ignore = IgnorePatterns(["information_schema"])
        assert ignore.should_ignore("information_schema")
        assert ignore.should_ignore("INFORMATION_SCHEMA")
        assert ignore.should_ignore("Information_Schema")

    def test_filter_schemas(self):
        """filter_schemas should remove ignored schemas."""
        ignore = IgnorePatterns(["pg_*", "information_schema"])
        schemas = ["public", "pg_catalog", "pg_toast", "information_schema", "myschema"]
        filtered = ignore.filter_schemas(schemas)
        assert filtered == ["public", "myschema"]

    def test_filter_tables(self):
        """filter_tables should remove ignored tables."""
        ignore = IgnorePatterns(["django_*", "_*"])
        tables = [
            {"name": "users", "full_name": "public.users"},
            {"name": "django_migrations", "full_name": "public.django_migrations"},
            {"name": "_temp", "full_name": "public._temp"},
            {"name": "orders", "full_name": "public.orders"},
        ]
        filtered = ignore.filter_tables(tables)
        assert len(filtered) == 2
        assert filtered[0]["name"] == "users"
        assert filtered[1]["name"] == "orders"

    def test_parse_patterns_ignores_comments(self):
        """Parser should ignore comments and blank lines."""
        content = """
# This is a comment
pattern1

# Another comment
pattern2
  # Indented comment
pattern3
"""
        patterns = IgnorePatterns._parse_patterns(content)
        assert patterns == ["pattern1", "pattern2", "pattern3"]


class TestDefaultContent:
    """Tests for default ignore content."""

    def test_default_content_not_empty(self):
        """Default content should exist."""
        content = get_default_ignore_content()
        assert len(content) > 0

    def test_default_content_has_common_patterns(self):
        """Default content should include common patterns."""
        content = get_default_ignore_content()
        assert "information_schema" in content
        assert "django_*" in content
        assert "pg_catalog" in content
