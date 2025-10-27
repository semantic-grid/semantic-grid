"""
Test database driver normalization.

This test verifies that the driver normalization correctly handles
'postgres' -> 'postgresql' conversion for SQLAlchemy compatibility.
"""

from dbmeta_app.wh_db.db import normalize_database_driver


def test_postgres_to_postgresql():
    """Test that 'postgres' is normalized to 'postgresql'."""
    assert normalize_database_driver('postgres') == 'postgresql'
    print("✅ Test 1 passed: 'postgres' -> 'postgresql'")


def test_postgres_with_driver():
    """Test that 'postgres+psycopg2' is normalized to 'postgresql+psycopg2'."""
    assert normalize_database_driver('postgres+psycopg2') == 'postgresql+psycopg2'
    print("✅ Test 2 passed: 'postgres+psycopg2' -> 'postgresql+psycopg2'")


def test_clickhouse_unchanged():
    """Test that 'clickhouse+native' remains unchanged."""
    assert normalize_database_driver('clickhouse+native') == 'clickhouse+native'
    print("✅ Test 3 passed: 'clickhouse+native' remains unchanged")


def test_clickhouse_simple():
    """Test that 'clickhouse' remains unchanged."""
    assert normalize_database_driver('clickhouse') == 'clickhouse'
    print("✅ Test 4 passed: 'clickhouse' remains unchanged")


def test_postgresql_unchanged():
    """Test that 'postgresql' (correct form) remains unchanged."""
    assert normalize_database_driver('postgresql') == 'postgresql'
    print("✅ Test 5 passed: 'postgresql' remains unchanged")


def test_postgresql_with_driver():
    """Test that 'postgresql+psycopg2' remains unchanged."""
    assert normalize_database_driver('postgresql+psycopg2') == 'postgresql+psycopg2'
    print("✅ Test 6 passed: 'postgresql+psycopg2' remains unchanged")


def test_mysql():
    """Test that 'mysql+pymysql' remains unchanged."""
    assert normalize_database_driver('mysql+pymysql') == 'mysql+pymysql'
    print("✅ Test 7 passed: 'mysql+pymysql' remains unchanged")


def test_empty_driver():
    """Test that empty/None driver is handled."""
    assert normalize_database_driver('') == ''
    assert normalize_database_driver(None) is None
    print("✅ Test 8 passed: Empty/None driver handled correctly")


def test_case_insensitive():
    """Test that dialect is case-insensitive."""
    assert normalize_database_driver('POSTGRES+psycopg2') == 'postgresql+psycopg2'
    assert normalize_database_driver('ClickHouse+native') == 'clickhouse+native'
    print("✅ Test 9 passed: Case-insensitive normalization")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("DATABASE DRIVER NORMALIZATION TESTS")
    print("="*60)

    tests = [
        ("postgres -> postgresql", test_postgres_to_postgresql),
        ("postgres+driver normalization", test_postgres_with_driver),
        ("clickhouse unchanged", test_clickhouse_unchanged),
        ("clickhouse simple unchanged", test_clickhouse_simple),
        ("postgresql unchanged", test_postgresql_unchanged),
        ("postgresql+driver unchanged", test_postgresql_with_driver),
        ("mysql unchanged", test_mysql),
        ("empty/None handling", test_empty_driver),
        ("case insensitive", test_case_insensitive),
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
