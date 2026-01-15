#!/usr/bin/env python3
"""Build script for dbmeta CLI binary.

Usage:
    cd apps/db-meta-v2
    uv run python scripts/build.py

Output:
    dist/dbmeta (or dist/dbmeta.exe on Windows)
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path


def get_platform_suffix() -> str:
    """Get platform suffix for binary name."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalize architecture names
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine

    # Normalize OS names
    if system == "darwin":
        os_name = "macos"
    elif system == "windows":
        os_name = "windows"
    else:
        os_name = "linux"

    return f"{os_name}-{arch}"


def main():
    """Build the dbmeta binary."""
    app_dir = Path(__file__).parent.parent
    spec_file = app_dir / "dbmeta.spec"
    dist_dir = app_dir / "dist"

    print(f"Building dbmeta for {get_platform_suffix()}...")
    print(f"  App dir: {app_dir}")
    print(f"  Spec file: {spec_file}")
    print()

    # Check spec file exists
    if not spec_file.exists():
        print(f"ERROR: Spec file not found: {spec_file}")
        sys.exit(1)

    # Clean previous build
    build_dir = app_dir / "build"
    if build_dir.exists():
        print("Cleaning previous build...")
        shutil.rmtree(build_dir)

    # Run PyInstaller
    print("Running PyInstaller...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(spec_file),
        ],
        cwd=str(app_dir),
    )

    if result.returncode != 0:
        print("ERROR: PyInstaller failed")
        sys.exit(1)

    # Check output
    binary_name = "dbmeta.exe" if platform.system() == "Windows" else "dbmeta"
    binary_path = dist_dir / binary_name

    if not binary_path.exists():
        print(f"ERROR: Binary not found at {binary_path}")
        sys.exit(1)

    # Get file size
    size_mb = binary_path.stat().st_size / (1024 * 1024)

    print()
    print("Build successful!")
    print(f"  Binary: {binary_path}")
    print(f"  Size: {size_mb:.1f} MB")
    print()
    print("To test:")
    print(f"  {binary_path} --help")
    print(f"  {binary_path} init")

    # Optionally rename with platform suffix
    platform_suffix = get_platform_suffix()
    if platform.system() == "Windows":
        platform_binary = dist_dir / f"dbmeta-{platform_suffix}.exe"
    else:
        platform_binary = dist_dir / f"dbmeta-{platform_suffix}"

    shutil.copy(binary_path, platform_binary)
    print()
    print(f"Platform binary: {platform_binary}")


if __name__ == "__main__":
    main()
