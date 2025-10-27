"""
Example usage of MetadataValidator to check QueryMetadata consistency.
"""

from uuid import uuid4

from fm_app.api.model import Column, QueryMetadata
from fm_app.validators import MetadataValidationError, MetadataValidator


def example_valid_metadata():
    """Example of valid metadata."""
    print("=" * 80)
    print("Example 1: Valid metadata")
    print("=" * 80)

    sql = """
    SELECT
        wallet_address AS wallet,
        DATE(block_time) AS trade_date,
        SUM(amount) AS total_amount
    FROM trades
    GROUP BY wallet_address, DATE(block_time)
    ORDER BY total_amount DESC
    """

    metadata = QueryMetadata(
        id=uuid4(),
        sql=sql,
        columns=[
            Column(
                id="col_1",
                column_name="wallet",  # ✓ Using alias
                summary="Wallet address",
            ),
            Column(
                id="col_2",
                column_name="trade_date",  # ✓ Using alias
                summary="Trading date",
            ),
            Column(
                id="col_3",
                column_name="total_amount",  # ✓ Using alias
                summary="Total amount",
            ),
        ],
    )

    result = MetadataValidator.validate_metadata(metadata, dialect="clickhouse")

    print(f"Valid: {result['valid']}")
    print(f"SQL columns: {result['sql_columns']}")
    print(f"Metadata columns: {result['metadata_columns']}")
    print(f"Errors: {result['errors']}")
    print(f"Warnings: {result['warnings']}")
    print()


def example_invalid_metadata_with_expressions():
    """Example of invalid metadata (using expressions instead of aliases)."""
    print("=" * 80)
    print("Example 2: Invalid metadata - expressions in column_name")
    print("=" * 80)

    sql = """
    SELECT
        wallet_address AS wallet,
        DATE(block_time) AS trade_date,
        SUM(amount) AS total_amount
    FROM trades
    GROUP BY wallet_address, DATE(block_time)
    """

    metadata = QueryMetadata(
        id=uuid4(),
        sql=sql,
        columns=[
            Column(
                id="col_1",
                column_name="wallet_address",  # ❌ Should use alias "wallet"
                summary="Wallet address",
            ),
            Column(
                id="col_2",
                column_name="DATE(block_time)",  # ❌ Should use alias "trade_date"
                summary="Trading date",
            ),
            Column(
                id="col_3",
                column_name="SUM(amount)",  # ❌ Should use alias "total_amount"
                summary="Total amount",
            ),
        ],
    )

    result = MetadataValidator.validate_metadata(metadata, dialect="clickhouse")

    print(f"Valid: {result['valid']}")
    print(f"SQL columns: {result['sql_columns']}")
    print(f"Metadata columns: {result['metadata_columns']}")
    print("Errors:")
    for error in result["errors"]:
        print(f"  - {error}")
    print()


def example_invalid_metadata_with_table_prefix():
    """Example of invalid metadata (using table prefixes)."""
    print("=" * 80)
    print("Example 3: Invalid metadata - table prefixes in column_name")
    print("=" * 80)

    sql = """
    SELECT
        t.wallet_address,
        t.amount
    FROM trades t
    """

    metadata = QueryMetadata(
        id=uuid4(),
        sql=sql,
        columns=[
            Column(
                id="col_1",
                column_name="t.wallet_address",  # ❌ Should be "wallet_address"
                summary="Wallet address",
            ),
            Column(
                id="col_2",
                column_name="t.amount",  # ❌ Should be "amount"
                summary="Amount",
            ),
        ],
    )

    result = MetadataValidator.validate_metadata(metadata, dialect="clickhouse")

    print(f"Valid: {result['valid']}")
    print("Errors:")
    for error in result["errors"]:
        print(f"  - {error}")
    print()


def example_validate_and_raise():
    """Example using validate_and_raise."""
    print("=" * 80)
    print("Example 4: Using validate_and_raise (will throw exception)")
    print("=" * 80)

    sql = """
    SELECT
        DATE(block_time) AS trade_date,
        SUM(amount) AS total_amount
    FROM trades
    """

    metadata = QueryMetadata(
        id=uuid4(),
        sql=sql,
        columns=[
            Column(
                id="col_1",
                column_name="DATE(block_time)",  # ❌ Wrong
                summary="Trading date",
            ),
        ],
    )

    try:
        MetadataValidator.validate_and_raise(metadata, dialect="clickhouse")
        print("Validation passed!")
    except MetadataValidationError as e:
        print(f"Validation failed (as expected):\n{e}")
    print()


if __name__ == "__main__":
    example_valid_metadata()
    example_invalid_metadata_with_expressions()
    example_invalid_metadata_with_table_prefix()
    example_validate_and_raise()

    print("=" * 80)
    print("Summary:")
    print("=" * 80)
    print(
        """
The MetadataValidator can be used to:
1. Validate QueryMetadata before saving it
2. Debug issues with column_name inconsistencies
3. Add as a validation step in the repair/critic loop

Integration points:
- Add to the interactive query flow after LLM generates metadata
- Add as a post-processing step before returning to frontend
- Add as a pre-check before executing sort/filter operations
- Use in tests to ensure metadata quality
"""
    )
