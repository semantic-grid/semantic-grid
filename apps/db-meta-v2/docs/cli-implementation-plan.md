# dbmeta CLI - Standalone Binary Implementation Plan

## Goal
Create a one-liner installer for db-meta-v2 that works without Python/Docker:
```bash
curl -fsSL https://semantic-grid.io/install.sh | sh
```

## User Experience

```bash
# Install
curl -fsSL https://semantic-grid.io/install.sh | sh

# First run - interactive setup
dbmeta init
# → Prompts for DATABASE_URL, PROVIDER_ID
# → Creates ~/.dbmeta/config.yaml
# → Offers to configure Claude Desktop

# Start server
dbmeta start

# Later: edit config
dbmeta config
```

## Files to Create

### 1. CLI Entry Point
**`apps/db-meta-v2/src/db_meta_v2/cli.py`**

Commands:
- `dbmeta init` - Interactive setup wizard
  - Prompt for DATABASE_URL (with examples for Trino/ClickHouse/Postgres)
  - Prompt for PROVIDER_ID (default: "default")
  - Prompt for TOOL_MODE (detailed/shell, default: shell)
  - Save to `~/.dbmeta/config.yaml`
  - Offer to configure Claude Desktop automatically
  
- `dbmeta start` - Run MCP server (stdio mode for Claude Desktop)
  - Load config from `~/.dbmeta/config.yaml`
  - Start server with loaded settings
  
- `dbmeta config` - Open config in $EDITOR
  
- `dbmeta claude-desktop` - Configure Claude Desktop
  - Detect OS, find config path
  - Read existing config or create new
  - Add/update dbmeta server entry
  - Print instructions to restart Claude Desktop

### 2. PyInstaller Spec
**`apps/db-meta-v2/dbmeta.spec`**

- Bundle db_meta_v2 package + all dependencies
- Single-file executable (--onefile)
- Include vault templates from packages/resources
- Hidden imports for SQLAlchemy dialects, pydantic, etc.

### 3. Build Script  
**`apps/db-meta-v2/scripts/build.py`**

- Run PyInstaller with correct options
- Output to `dist/dbmeta` (or `dist/dbmeta.exe` on Windows)
- For local testing

### 4. Install Script
**`apps/db-meta-v2/scripts/install.sh`**

```bash
#!/bin/bash
# Detect OS/arch
# Download from GitHub Releases
# Install to ~/.local/bin or /usr/local/bin
# Make executable
# Print next steps
```

### 5. GitHub Actions Workflow
**`.github/workflows/release-dbmeta.yml`**

Matrix build:
- `macos-latest` (arm64) → `dbmeta-macos-arm64`
- `macos-13` (x64) → `dbmeta-macos-x64`  
- `ubuntu-latest` → `dbmeta-linux-x64`
- `windows-latest` → `dbmeta-windows-x64.exe`

Trigger: On tag `dbmeta-v*`

Steps:
1. Checkout
2. Setup Python 3.13
3. Install uv + dependencies
4. Run PyInstaller
5. Upload artifacts to GitHub Release

## Config File Format

**`~/.dbmeta/config.yaml`**
```yaml
database_url: "trino://user:pass@host:8443/catalog/schema"
provider_id: "default"
tool_mode: "shell"
vault_path: "~/.dbmeta/vault"
log_level: "INFO"
```

## Claude Desktop Config

**Auto-generated entry:**
```json
{
  "mcpServers": {
    "dbmeta": {
      "command": "/Users/xxx/.local/bin/dbmeta",
      "args": ["start"]
    }
  }
}
```

## Dependencies to Add

```toml
# pyproject.toml [project.optional-dependencies]
cli = [
  "click>=8.0",      # CLI framework
  "rich>=13.0",      # Pretty prompts/output
  "pyyaml>=6.0",     # Config file
]

[project.scripts]
dbmeta = "db_meta_v2.cli:main"

# dev dependencies
[tool.uv.dev-dependencies]
pyinstaller = ">=6.0"
```

## Implementation Order

1. Add CLI dependencies to pyproject.toml
2. Create cli.py with Click commands
3. Create dbmeta.spec for PyInstaller
4. Create scripts/build.py for local builds
5. Test locally on macOS
6. Create scripts/install.sh
7. Create GitHub Actions workflow
8. Test end-to-end on fresh machine

## Platform-Specific Notes

### macOS
- Binary works on both arm64 and x64 with separate builds
- Claude Desktop config: `~/.config/claude/claude_desktop_config.json`
- Install to: `~/.local/bin/dbmeta`

### Linux
- x64 only for now
- Same config path as macOS
- Install to: `~/.local/bin/dbmeta`

### Windows
- Produces `.exe`
- Claude Desktop config: `%APPDATA%\Claude\claude_desktop_config.json`
- Install to: `%LOCALAPPDATA%\Programs\dbmeta\dbmeta.exe`
- Add to PATH or create shortcut

## Open Questions

None - ready to implement.
