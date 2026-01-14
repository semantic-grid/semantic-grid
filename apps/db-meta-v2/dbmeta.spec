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
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

# Get the app directory
app_dir = Path(SPECPATH)
src_dir = app_dir / "src"
resources_dir = app_dir.parent.parent / "packages" / "resources"

block_cipher = None

# Collect ALL package metadata to avoid version check failures at runtime
import importlib.metadata
from PyInstaller.utils.hooks import collect_dynamic_libs

datas = []
binaries = []

# Get all installed packages and copy their metadata
for dist in importlib.metadata.distributions():
    try:
        datas += copy_metadata(dist.metadata["Name"])
    except Exception:
        pass

# Collect lupa native libraries (Lua bindings for fakeredis)
try:
    binaries += collect_dynamic_libs("lupa")
except Exception:
    pass

# Collect fakeredis data files (commands.json, etc.)
try:
    datas += collect_data_files("fakeredis", include_py_files=False)
    # Also explicitly add commands.json to the right location
    import fakeredis
    fakeredis_dir = Path(fakeredis.__file__).parent
    datas.append((str(fakeredis_dir / "commands.json"), "fakeredis"))
except Exception:
    pass

# Include vault templates if they exist
if resources_dir.exists():
    datas.append((str(resources_dir / "dbmeta_app"), "resources/dbmeta_app"))

a = Analysis(
    [str(src_dir / "db_meta_v2" / "cli.py")],
    pathex=[str(src_dir)],
    binaries=binaries,
    datas=datas,
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
        # Fakeredis/Lua support (used by docket)
        "lupa",
        "lupa.lua51",
        "lupa.lua52",
        "lupa.lua53",
        "lupa.lua54",
        "lupa.luajit20",
        "lupa.luajit21",
        "fakeredis",
        # OpenTelemetry (for console tracing)
        "opentelemetry",
        "opentelemetry.sdk",
        "opentelemetry.sdk.trace",
        "opentelemetry.sdk.trace.export",
        "opentelemetry.trace",
        # Console module
        "db_meta_v2.console",
        "db_meta_v2.console.collector",
        "db_meta_v2.console.server",
        "db_meta_v2.console.ui",
        "db_meta_v2.console.exporter",
        "db_meta_v2.console.http_exporter",
        "db_meta_v2.console.instrument",
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
        # Exclude logfire - its Pydantic plugin breaks in PyInstaller
        # (tries to inspect source code which doesn't exist in bundle)
        "logfire",
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
