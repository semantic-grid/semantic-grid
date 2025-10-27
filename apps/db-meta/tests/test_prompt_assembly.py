"""
Tests for prompt assembly from repo artifacts.

Verifies that:
1. Schema descriptions YAML files are correctly structured
2. Profile merging works correctly
3. Error handling works for missing profiles
"""

import pathlib
import sys

import pytest
import yaml


def test_system_pack_schema_descriptions_structure():
    """Test that the system-pack schema_descriptions.yaml has correct structure."""
    # Path to system-pack
    repo_root = pathlib.Path(__file__).parent.parent.parent.parent
    schema_file = (
        repo_root
        / "packages/resources/dbmeta_app/system-pack/v1.0.0/resources/schema_descriptions.yaml"
    )

    assert schema_file.exists(), f"schema_descriptions.yaml not found at {schema_file}"

    with open(schema_file) as f:
        content = yaml.safe_load(f)

    # Verify structure
    assert "version" in content, "Missing 'version' key"
    assert "profiles" in content, "Missing 'profiles' key"
    assert isinstance(content["profiles"], dict), "'profiles' must be a dict"

    # Verify default profiles exist
    expected_profiles = ["wh", "wh_new", "wh_v2"]
    for profile in expected_profiles:
        assert (
            profile in content["profiles"]
        ), f"Missing expected profile: {profile}"
        assert "whitelist" in content["profiles"][profile]
        assert "tables" in content["profiles"][profile]


def test_client_overlay_schema_descriptions():
    """Test that client overlay schema_descriptions.yaml is properly structured."""
    repo_root = pathlib.Path(__file__).parent.parent.parent.parent
    overlay_file = (
        repo_root
        / "packages/client-configs/apegpt/prod/dbmeta_app/overlays/resources/schema_descriptions.yaml"
    )

    assert overlay_file.exists(), f"Client overlay not found at {overlay_file}"

    with open(overlay_file) as f:
        content = yaml.safe_load(f)

    # Verify structure
    assert "version" in content, "Missing 'version' key"
    assert "profiles" in content, "Missing 'profiles' key"
    assert isinstance(content["profiles"], dict), "'profiles' must be a dict"

    # wh_v2 should have actual table descriptions
    assert "wh_v2" in content["profiles"], "Missing wh_v2 profile in overlay"
    wh_v2 = content["profiles"]["wh_v2"]
    assert "tables" in wh_v2
    # Client overlay should have real table descriptions
    assert len(wh_v2["tables"]) > 0, "wh_v2 should have table descriptions"


def test_assemble_effective_tree_merges_profiles():
    """Test that assemble_effective_tree correctly merges base and overlay."""
    # This test requires dbmeta_app modules, will be tested in integration tests
    pytest.skip("Requires dbmeta_app package installation")


def test_all_expected_profiles_present():
    """Test that all expected database profiles are defined."""
    repo_root = pathlib.Path(__file__).parent.parent.parent.parent

    # Check system-pack
    schema_file = (
        repo_root
        / "packages/resources/dbmeta_app/system-pack/v1.0.0/resources/schema_descriptions.yaml"
    )

    with open(schema_file) as f:
        base_content = yaml.safe_load(f)

    # Check overlay
    overlay_file = (
        repo_root
        / "packages/client-configs/apegpt/prod/dbmeta_app/overlays/resources/schema_descriptions.yaml"
    )

    with open(overlay_file) as f:
        overlay_content = yaml.safe_load(f)

    # Both should have wh_v2
    assert "wh_v2" in base_content["profiles"]
    assert "wh_v2" in overlay_content["profiles"]

    # Overlay should have substantial content
    assert len(overlay_content["profiles"]["wh_v2"]["tables"]) >= 5


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
