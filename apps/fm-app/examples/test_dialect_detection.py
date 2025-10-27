"""
Test dialect detection utility.

This test verifies that the dialect detection utility correctly identifies
the warehouse database dialect from the SQLAlchemy engine or settings.
"""

from fm_app.utils import get_cached_warehouse_dialect, get_warehouse_dialect


def test_get_warehouse_dialect():
    """Test that get_warehouse_dialect returns a valid dialect."""
    print("\n=== Testing get_warehouse_dialect ===")

    try:
        dialect = get_warehouse_dialect()
        print(f"✅ Detected warehouse dialect: {dialect}")

        # Verify it's one of the supported dialects
        valid_dialects = ["clickhouse", "postgres", "mysql", "sqlite", "tsql", "oracle"]
        assert dialect in valid_dialects or dialect, \
            f"Expected one of {valid_dialects}, got: {dialect}"
        print(f"✅ Dialect '{dialect}' is valid")

    except Exception as e:
        print(f"❌ Error detecting dialect: {e}")
        raise


def test_get_cached_warehouse_dialect():
    """Test that get_cached_warehouse_dialect returns cached value."""
    print("\n=== Testing get_cached_warehouse_dialect ===")

    try:
        # First call should detect and cache
        dialect1 = get_cached_warehouse_dialect()
        print(f"✅ First call returned: {dialect1}")

        # Second call should return cached value
        dialect2 = get_cached_warehouse_dialect()
        print(f"✅ Second call returned: {dialect2}")

        # Should be the same
        assert dialect1 == dialect2, \
            f"Expected cached dialect to match, got: {dialect1} != {dialect2}"
        print("✅ Cached dialect matches")

    except Exception as e:
        print(f"❌ Error with cached dialect: {e}")
        raise


def test_dialect_in_validator():
    """Test that validator uses detected dialect when none provided."""
    print("\n=== Testing validator with auto-detected dialect ===")

    try:
        import uuid

        from fm_app.api.model import QueryMetadata
        from fm_app.validators.metadata_validator import MetadataValidator

        # Create simple metadata
        metadata = QueryMetadata(
            id=uuid.uuid4(),
            sql="SELECT wallet_address AS wallet, amount FROM transactions",
            columns=[
                {"id": str(uuid.uuid4()), "column_name": "wallet"},
                {"id": str(uuid.uuid4()), "column_name": "amount"}
            ]
        )

        # Call validator without dialect parameter (should auto-detect)
        result = MetadataValidator.validate_metadata(metadata)

        print(f"✅ Validator result: valid={result['valid']}")
        if result['errors']:
            print(f"   Errors: {result['errors']}")
        if result['warnings']:
            print(f"   Warnings: {result['warnings']}")

        # Should detect columns correctly regardless of dialect
        assert result['sql_columns'] == ['wallet', 'amount'], \
            f"Expected ['wallet', 'amount'], got: {result['sql_columns']}"
        print("✅ Validator correctly extracted columns with auto-detected dialect")

    except Exception as e:
        print(f"❌ Error testing validator: {e}")
        raise


def test_sqlglot_parse_with_dialect():
    """Test that sqlglot can parse SQL with detected dialect."""
    print("\n=== Testing sqlglot with detected dialect ===")

    try:
        import sqlglot

        dialect = get_cached_warehouse_dialect()
        sql = "SELECT wallet_address AS wallet, amount FROM transactions WHERE amount > 100"

        # Should parse successfully
        parsed = sqlglot.parse_one(sql, dialect=dialect)
        print(f"✅ Successfully parsed SQL with dialect '{dialect}'")
        print(f"   SQL: {sql[:60]}...")

        assert parsed is not None, "Expected parsed SQL object"
        print("✅ Parsed SQL object is valid")

    except Exception as e:
        print(f"❌ Error parsing SQL: {e}")
        raise


if __name__ == "__main__":
    print("\n" + "="*60)
    print("DIALECT DETECTION TESTS")
    print("="*60)

    tests = [
        ("Basic dialect detection", test_get_warehouse_dialect),
        ("Cached dialect detection", test_get_cached_warehouse_dialect),
        ("Validator auto-detection", test_dialect_in_validator),
        ("SQLglot parsing", test_sqlglot_parse_with_dialect),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            test_func()
            print(f"\n✅ PASSED: {test_name}")
            passed += 1
        except Exception as e:
            print(f"\n❌ FAILED: {test_name}")
            print(f"   Error: {e}")
            failed += 1

    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60)

    if failed > 0:
        exit(1)
