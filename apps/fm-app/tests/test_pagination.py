"""
Unit tests for SQL pagination with CTE support.
"""

import os
import sys
from unittest import mock

# Set minimal environment variables before importing fm_app
# This prevents Settings validation errors in CI
os.environ.setdefault('DATABASE_USER', 'test')
os.environ.setdefault('DATABASE_PASS', 'test')
os.environ.setdefault('DATABASE_PORT', '5432')
os.environ.setdefault('DATABASE_SERVER', 'localhost')
os.environ.setdefault('DATABASE_DB', 'test')
os.environ.setdefault('DATABASE_WH_USER', 'test')
os.environ.setdefault('DATABASE_WH_PASS', 'test')
os.environ.setdefault('DATABASE_WH_PORT', '8123')
os.environ.setdefault('DATABASE_WH_PORT_NEW', '8123')
os.environ.setdefault('DATABASE_WH_PORT_V2', '8123')
os.environ.setdefault('DATABASE_WH_SERVER', 'localhost')
os.environ.setdefault('DATABASE_WH_SERVER_NEW', 'localhost')
os.environ.setdefault('DATABASE_WH_SERVER_V2', 'localhost')
os.environ.setdefault('DATABASE_WH_PARAMS', '')
os.environ.setdefault('DATABASE_WH_PARAMS_NEW', '')
os.environ.setdefault('DATABASE_WH_PARAMS_V2', '')
os.environ.setdefault('DATABASE_WH_DB', 'test')
os.environ.setdefault('DATABASE_WH_DB_NEW', 'test')
os.environ.setdefault('DATABASE_WH_DB_V2', 'test')
os.environ.setdefault('AUTH0_DOMAIN', 'test.auth0.com')
os.environ.setdefault('AUTH0_API_AUDIENCE', 'test')
os.environ.setdefault('AUTH0_ISSUER', 'https://test.auth0.com/')
os.environ.setdefault('AUTH0_ALGORITHMS', 'RS256')
os.environ.setdefault('DBMETA', 'http://localhost:8000')
os.environ.setdefault('DBREF', 'http://localhost:8000')
os.environ.setdefault('IRL_SLOTS', '')
os.environ.setdefault('GOOGLE_PROJECT_ID', 'test')
os.environ.setdefault('GOOGLE_CRED_FILE', 'test.json')
os.environ.setdefault('ANTHROPIC_API_KEY', 'sk-ant-test')
os.environ.setdefault('OPENAI_API_KEY', 'sk-test')
os.environ.setdefault('DEEPSEEK_AI_API_URL', 'http://localhost')
os.environ.setdefault('DEEPSEEK_AI_API_KEY', 'test')
os.environ.setdefault('GUEST_AUTH_HOST', 'localhost')
os.environ.setdefault('GUEST_AUTH_ISSUER', 'http://localhost')

# Add the parent directory to the path so we can import fm_app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fm_app.api.routes import build_sorted_paginated_sql


def test_regular_query_without_sort():
    """Test regular SELECT query without sorting."""
    sql = "SELECT id, name FROM users"
    result = build_sorted_paginated_sql(
        sql,
        sort_by=None,
        sort_order="asc",
        include_total_count=True
    )

    # Check key components (allow for whitespace variations)
    assert "SELECT id, name FROM users" in result
    assert ") AS t" in result
    assert "COUNT(*) OVER () AS total_count" in result
    assert "LIMIT :limit" in result
    assert "OFFSET :offset" in result
    print("✅ Test 1 passed: Regular query without sort")


def test_regular_query_with_sort():
    """Test regular SELECT query with sorting."""
    sql = "SELECT id, name FROM users"
    result = build_sorted_paginated_sql(
        sql,
        sort_by="name",
        sort_order="desc",
        include_total_count=True
    )

    assert "ORDER BY t.name DESC" in result
    assert "COUNT(*) OVER () AS total_count" in result
    print("✅ Test 2 passed: Regular query with sort")


def test_cte_query_postgres():
    """Test CTE query with PostgreSQL dialect (supports nested CTEs)."""
    sql = """
    WITH temp AS (
        SELECT id, name FROM users
    )
    SELECT * FROM temp
    """

    with mock.patch('fm_app.utils.get_cached_warehouse_dialect', return_value='postgres'):
        result = build_sorted_paginated_sql(
            sql,
            sort_by=None,
            sort_order="asc",
            include_total_count=True
        )

        # PostgreSQL can wrap CTE in FROM()
        assert "SELECT *, COUNT(*) OVER () AS total_count" in result
        assert "FROM (\n            WITH temp AS" in result
        assert "__cte_wrapper" in result

    print("✅ Test 3 passed: CTE query with PostgreSQL")


def test_cte_query_clickhouse():
    """Test CTE query with ClickHouse dialect (no nested CTEs)."""
    sql = """
    WITH temp AS (
        SELECT id, name FROM users
    )
    SELECT * FROM temp
    """

    with mock.patch('fm_app.utils.get_cached_warehouse_dialect', return_value='clickhouse'):
        result = build_sorted_paginated_sql(
            sql,
            sort_by=None,
            sort_order="asc",
            include_total_count=True
        )

        # ClickHouse skips total_count for CTEs
        assert "COUNT(*) OVER ()" not in result
        assert "WITH temp AS" in result
        assert "SELECT * FROM temp" in result

    print("✅ Test 3b passed: CTE query with ClickHouse")


def test_cte_query_with_sort_postgres():
    """Test CTE query with sorting on PostgreSQL."""
    sql = """
    WITH temp AS (
        SELECT id, name FROM users
    )
    SELECT * FROM temp
    """

    with mock.patch('fm_app.utils.get_cached_warehouse_dialect', return_value='postgres'):
        result = build_sorted_paginated_sql(
            sql,
            sort_by="name",
            sort_order="asc",
            include_total_count=True
        )

        # PostgreSQL wraps CTE, no table prefix needed
        assert "ORDER BY name ASC" in result
        assert "ORDER BY t.name" not in result

    print("✅ Test 4 passed: CTE query with sort (PostgreSQL)")


def test_cte_query_with_sort_clickhouse():
    """Test CTE query with sorting on ClickHouse."""
    sql = """
    WITH temp AS (
        SELECT id, name FROM users
    )
    SELECT * FROM temp
    """

    with mock.patch('fm_app.utils.get_cached_warehouse_dialect', return_value='clickhouse'):
        result = build_sorted_paginated_sql(
            sql,
            sort_by="name",
            sort_order="asc",
            include_total_count=False
        )

        # ClickHouse doesn't wrap, still no prefix
        assert "ORDER BY name ASC" in result
        assert "ORDER BY t.name" not in result

    print("✅ Test 4b passed: CTE query with sort (ClickHouse)")


def test_complex_cte_query():
    """Test complex multi-CTE query like user's example."""
    sql = """
    WITH
        now() AS t_now,
        t_now - INTERVAL 24 HOUR AS t_start,
        base AS (
            SELECT * FROM trades WHERE ts >= t_start
        ),
        top_traders AS (
            SELECT trader, sum(pnl) AS total_pnl
            FROM base
            GROUP BY trader
        )
    SELECT * FROM top_traders
    """

    with mock.patch('fm_app.utils.get_cached_warehouse_dialect', return_value='clickhouse'):
        result = build_sorted_paginated_sql(
            sql,
            sort_by="total_pnl",
            sort_order="desc",
            include_total_count=True
        )

        # ClickHouse doesn't wrap CTEs, so total_count is skipped
        assert "ORDER BY total_pnl DESC" in result
        assert "WITH\n        now() AS t_now" in result or "WITH now() AS t_now" in result

    print("✅ Test 5 passed: Complex multi-CTE query")


def test_query_with_trailing_semicolon():
    """Test that trailing semicolons are handled."""
    sql = "SELECT id, name FROM users;"
    result = build_sorted_paginated_sql(
        sql,
        sort_by=None,
        sort_order="asc",
        include_total_count=False
    )

    # Semicolon should be stripped from body
    assert result.count(";") == 0  # Only in the final statement
    print("✅ Test 6 passed: Trailing semicolon handling")


def test_query_with_existing_order_by():
    """Test that existing ORDER BY is stripped."""
    sql = "SELECT id, name FROM users ORDER BY created_at DESC"
    result = build_sorted_paginated_sql(
        sql,
        sort_by="name",
        sort_order="asc",
        include_total_count=True
    )

    # Should have our ORDER BY, not the original
    assert "ORDER BY t.name ASC" in result
    assert result.count("ORDER BY") == 1  # Only our ORDER BY
    print("✅ Test 7 passed: Existing ORDER BY stripped")


def test_case_insensitive_with():
    """Test that WITH detection is case-insensitive."""
    sql = "with temp as (select 1) select * from temp"

    with mock.patch('fm_app.utils.get_cached_warehouse_dialect', return_value='postgres'):
        result = build_sorted_paginated_sql(
            sql,
            sort_by=None,
            sort_order="asc",
            include_total_count=True
        )

        # Should detect lowercase "with" as CTE
        assert "__cte_wrapper" in result
        assert "SELECT *, COUNT(*) OVER () AS total_count" in result

    print("✅ Test 8 passed: Case-insensitive WITH detection")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("SQL PAGINATION TESTS")
    print("="*60)

    tests = [
        ("Regular query without sort", test_regular_query_without_sort),
        ("Regular query with sort", test_regular_query_with_sort),
        ("CTE query with PostgreSQL", test_cte_query_postgres),
        ("CTE query with ClickHouse", test_cte_query_clickhouse),
        ("CTE query with sort (PostgreSQL)", test_cte_query_with_sort_postgres),
        ("CTE query with sort (ClickHouse)", test_cte_query_with_sort_clickhouse),
        ("Complex multi-CTE query", test_complex_cte_query),
        ("Trailing semicolon handling", test_query_with_trailing_semicolon),
        ("Existing ORDER BY stripped", test_query_with_existing_order_by),
        ("Case-insensitive WITH", test_case_insensitive_with),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"❌ FAILED: {test_name}")
            print(f"   Error: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR in {test_name}: {e}")
            failed += 1

    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60)

    if failed > 0:
        exit(1)
