"""
Detailed test showing query transformations for key examples.
"""

import os
import sys
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fm_app.api.routes import _strip_leading_comments, build_sorted_paginated_sql


def load_query_examples():
    """Load query examples from the apegpt prod config."""
    repo_root = Path(__file__).parent.parent.parent.parent
    yaml_path = repo_root / "packages/client-configs/apegpt/prod/dbmeta_app/overlays/resources/query_examples.yaml"

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    examples = []
    for profile, profile_data in data.get('profiles', {}).items():
        for idx, example in enumerate(profile_data.get('examples', []), 1):
            examples.append({
                'profile': profile,
                'index': idx,
                'request': example.get('request', '').strip(),
                'query': example.get('response', '').strip(),
                'db': example.get('db', '')
            })

    return examples


def main():
    examples = load_query_examples()

    # Test a few key examples in detail
    test_cases = [
        (1, "Simple CTE with LIMIT (should preserve LIMIT inside CTE)"),
        (2, "Multi-CTE with LIMIT inside (complex case)"),
        (10, "Very complex multi-step CTE (profitability analysis)"),
    ]

    with mock.patch('fm_app.utils.get_cached_warehouse_dialect', return_value='clickhouse'):
        for idx, description in test_cases:
            example = examples[idx - 1]  # 0-indexed
            print("=" * 80)
            print(f"Example {idx}: {description}")
            print("=" * 80)
            print()
            print("REQUEST:")
            print(example['request'])
            print()
            print("ORIGINAL QUERY (first 500 chars):")
            print(example['query'][:500])
            if len(example['query']) > 500:
                print("... [truncated]")
            print()

            # Transform with pagination
            result = build_sorted_paginated_sql(
                example['query'],
                sort_by=None,
                sort_order="asc",
                include_total_count=True
            )

            print("TRANSFORMED QUERY (last 500 chars):")
            print(result[-500:])
            print()

            # Validate (use same detection logic as the actual function)
            query_no_comments = _strip_leading_comments(example['query'])
            is_cte = query_no_comments.strip().upper().startswith('WITH')
            original_len = len(example['query'])
            result_len = len(result)

            print("VALIDATION:")
            print(f"  Is CTE: {is_cte}")
            print(f"  Original length: {original_len} chars")
            print(f"  Result length: {result_len} chars")
            print(f"  Has LIMIT :limit: {'✓' if 'LIMIT :limit' in result else '✗'}")
            print(f"  Has OFFSET :offset: {'✓' if 'OFFSET :offset' in result else '✗'}")

            if is_cte:
                original_with_count = example['query'].upper().count('WITH')
                result_with_count = result.upper().count('WITH')
                print(f"  WITH count (original): {original_with_count}")
                print(f"  WITH count (result): {result_with_count}")
                print(f"  CTEs preserved: {'✓' if result_with_count >= original_with_count else '✗'}")

            # Check for common issues
            if result_len < original_len * 0.8:
                print(f"  ⚠ Warning: Result is {int((1 - result_len/original_len)*100)}% smaller than original")

            print()


if __name__ == "__main__":
    main()
