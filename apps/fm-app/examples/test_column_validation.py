"""
Test script for column validation in data handler.
"""

from fm_app.api.model import Column
from fm_app.api.routes import validate_sort_column


def test_valid_column():
    """Test validation with valid column name."""
    print("=" * 80)
    print("Test 1: Valid column name")
    print("=" * 80)

    columns = [
        Column(id="col_1", column_name="wallet", summary="Wallet address"),
        Column(id="col_2", column_name="amount", summary="Amount"),
        Column(id="col_3", column_name="trade_date", summary="Trade date"),
    ]

    is_valid, result = validate_sort_column("wallet", columns)

    print("Input: sort_by='wallet'")
    print(f"Valid: {is_valid}")
    print(f"Result: {result}")
    assert is_valid is True
    assert result == "wallet"
    print("✅ PASSED\n")


def test_case_insensitive():
    """Test case-insensitive matching."""
    print("=" * 80)
    print("Test 2: Case insensitive matching")
    print("=" * 80)

    columns = [
        Column(id="col_1", column_name="wallet", summary="Wallet address"),
        Column(id="col_2", column_name="amount", summary="Amount"),
    ]

    is_valid, result = validate_sort_column("WALLET", columns)

    print("Input: sort_by='WALLET'")
    print(f"Valid: {is_valid}")
    print(f"Result: {result}")
    assert is_valid is True
    assert result == "wallet"  # Should return canonical lowercase name
    print("✅ PASSED\n")


def test_invalid_column():
    """Test validation with invalid column name."""
    print("=" * 80)
    print("Test 3: Invalid column name")
    print("=" * 80)

    columns = [
        Column(id="col_1", column_name="wallet", summary="Wallet address"),
        Column(id="col_2", column_name="amount", summary="Amount"),
    ]

    is_valid, result = validate_sort_column("nonexistent", columns)

    print("Input: sort_by='nonexistent'")
    print(f"Valid: {is_valid}")
    print(f"Error message: {result}")
    assert is_valid is False
    assert "Invalid sort column" in result
    assert "nonexistent" in result
    assert "wallet" in result  # Should list available columns
    print("✅ PASSED\n")


def test_no_columns():
    """Test validation when no columns available."""
    print("=" * 80)
    print("Test 4: No columns available")
    print("=" * 80)

    columns = []

    is_valid, result = validate_sort_column("wallet", columns)

    print("Input: sort_by='wallet', columns=[]")
    print(f"Valid: {is_valid}")
    print(f"Error message: {result}")
    assert is_valid is False
    # Empty list is treated as "not available"
    assert "not available" in result or "No columns found" in result
    print("✅ PASSED\n")


def test_none_columns():
    """Test validation when columns is None."""
    print("=" * 80)
    print("Test 5: Columns is None")
    print("=" * 80)

    is_valid, result = validate_sort_column("wallet", None)

    print("Input: sort_by='wallet', columns=None")
    print(f"Valid: {is_valid}")
    print(f"Error message: {result}")
    assert is_valid is False
    assert "not available" in result
    print("✅ PASSED\n")


def test_columns_without_column_name():
    """Test validation when some columns don't have column_name."""
    print("=" * 80)
    print("Test 6: Columns without column_name")
    print("=" * 80)

    columns = [
        Column(id="col_1", column_name="wallet", summary="Wallet"),
        Column(id="col_2", column_name=None, summary="Missing name"),  # No column_name
        Column(id="col_3", column_name="amount", summary="Amount"),
    ]

    # Should still work with valid columns
    is_valid, result = validate_sort_column("wallet", columns)
    print("Input: sort_by='wallet'")
    print(f"Valid: {is_valid}")
    print(f"Result: {result}")
    assert is_valid is True
    assert result == "wallet"

    # Invalid column should show only valid ones
    is_valid, result = validate_sort_column("invalid", columns)
    print("\nInput: sort_by='invalid'")
    print(f"Valid: {is_valid}")
    print(f"Error: {result}")
    assert is_valid is False
    assert "wallet" in result
    assert "amount" in result
    print("✅ PASSED\n")


def test_dict_columns():
    """Test validation when columns are dicts (from session metadata)."""
    print("=" * 80)
    print("Test 7: Columns as dicts (session metadata)")
    print("=" * 80)

    # Session metadata stores columns as dicts
    columns = [
        {"id": "col_1", "column_name": "wallet", "summary": "Wallet"},
        {"id": "col_2", "column_name": "amount", "summary": "Amount"},
    ]

    is_valid, result = validate_sort_column("wallet", columns)

    print("Input: sort_by='wallet', columns (as dicts)")
    print(f"Valid: {is_valid}")
    print(f"Result: {result}")
    assert is_valid is True
    assert result == "wallet"
    print("✅ PASSED\n")


if __name__ == "__main__":
    print("\n🧪 Running Column Validation Tests\n")

    test_valid_column()
    test_case_insensitive()
    test_invalid_column()
    test_no_columns()
    test_none_columns()
    test_columns_without_column_name()
    test_dict_columns()

    print("=" * 80)
    print("✅ All tests passed!")
    print("=" * 80)
    print(
        """
Summary:
- validate_sort_column correctly validates column names
- Case-insensitive matching works
- Clear error messages for invalid columns
- Handles edge cases (no columns, None, dicts)
- Returns canonical column name from metadata
"""
    )
