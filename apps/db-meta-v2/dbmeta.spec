# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for dbmeta CLI.

Build with:
    cd apps/db-meta-v2
    uv run pyinstaller dbmeta.spec

Or use the build script:
    uv run python scripts/build.py
"""

import sys
from pathlib import Path

# Get the app directory
app_dir = Path(SPECPATH)
src_dir = app_dir / "src"
resources_dir = app_dir.parent.parent / "packages" / "resources"

block_cipher = None

a = Analysis(
    [str(src_dir / "db_meta_v2" / "cli.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[
        # Include vault templates if they exist
        (str(resources_dir / "dbmeta_app"), "resources/dbmeta_app"),
    ] if resources_dir.exists() else [],
    hiddenimports=[
        # SQLAlchemy dialects
        "sqlalchemy.dialects.postgresql",
        "sqlalchemy.dialects.mysql",
        "trino.sqlalchemy",
        "clickhouse_sqlalchemy",
        # Pydantic
        "pydantic",
        "pydantic_settings",
        "pydantic_core",
        # FastMCP and dependencies
        "fastmcp",
        "mcp",
        "httpx",
        "anyio",
        "starlette",
        "uvicorn",
        # Rich console
        "rich",
        "rich.console",
        "rich.panel",
        "rich.prompt",
        # Click
        "click",
        # YAML
        "yaml",
        # Other
        "email.mime.text",
        "email.mime.multipart",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PIL",
        "cv2",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="dbmeta",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
