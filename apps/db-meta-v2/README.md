# db-meta-v2

MCP server for database semantics and query intelligence.

## Overview

db-meta-v2 is the core intelligence layer for Semantic Grid v2. It provides:

- **Database onboarding** - Guided flow to configure schema descriptions, domain models, and business rules
- **Query generation** - Natural language to SQL using schema context and business rules
- **Query validation** - SQL syntax checking, cost estimation, and read-only enforcement
- **UI specifications** - GridSpec generation for rich data presentation

## Installation

```bash
cd apps/db-meta-v2
uv sync
```

## Running

### As MCP Server (stdio)

```bash
./run.sh
```

Or directly:

```bash
uv run python -m db_meta_v2
```

### Claude Desktop Integration

1. Copy the example config:
   ```bash
   cp claude_desktop_config.example.json ~/.config/claude/claude_desktop_config.json
   ```

2. Edit the config to set the correct path and database URL:
   ```json
   {
     "mcpServers": {
       "db-meta-v2": {
         "command": "uv",
         "args": [
           "run",
           "--directory",
           "/path/to/semantic-grid/apps/db-meta-v2",
           "python",
           "-m",
           "db_meta_v2"
         ],
         "env": {
           "DATABASE_URL": "trino://user:pass@host:port/catalog/schema",
           "PROVIDER_ID": "my-provider"
         }
       }
     }
   }
   ```

3. Restart Claude Desktop

4. Verify connection by asking Claude: "Use the ping tool to check if db-meta-v2 is running"

**Config file locations:**
- macOS: `~/.config/claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/claude/claude_desktop_config.json`

## Configuration

Environment variables (can be set in `.env` file):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection URL | (empty) |
| `PROVIDER_ID` | Provider identifier for multi-tenant | `default` |
| `RESOURCES_DIR` | Path to resources directory | `packages/resources/dbmeta_app` |
| `PROVIDERS_DIR` | Path to providers artifact storage | `packages/resources/dbmeta_app/providers` |
| `OPENAI_API_KEY` | OpenAI API key for embeddings | (empty) |

**Supported database URL formats:**
- Trino: `trino://user:pass@host:8443/catalog/schema`
- PostgreSQL: `postgresql://user:pass@host:5432/database`
- ClickHouse: `clickhouse://user:pass@host:8123/database`

## Available Tools

### Core

- `ping` - Health check, verify server is running
- `get_config` - Get current configuration (non-sensitive)

### Database

- `test_connection` - Test database connectivity
- `detect_dialect` - Detect SQL dialect from connection URL
- `list_schemas` - List all schemas in the database
- `list_tables` - List tables in a schema
- `describe_table` - Get column information for a table
- `sample_table` - Get sample rows from a table

### Onboarding (coming soon)

- `onboarding_start` - Start onboarding flow
- `onboarding_status` - Get current onboarding state
- `onboarding_next` - Execute next onboarding step
- `onboarding_approve` - Approve pending artifact
- `onboarding_skip` - Skip current item

### Query (coming soon)

- `get_data` - Natural language to query results
- `run_sql` - Execute SQL directly
- `validate_sql` - Validate SQL syntax and cost

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

## Building Standalone Binary

The project uses PyInstaller to create standalone binaries for distribution.

### Build

```bash
# Build for current platform
uv run python scripts/build.py
```

This creates a binary at `dist/dbmeta` (and `dist/dbmeta-<platform>-<arch>`).

### Local Development Installation

To install a dev build locally without Gatekeeper issues on macOS:

```bash
# Copy binary to cache and create symlink
cp dist/dbmeta ~/.dbmeta/cache/dbmeta-dev
ln -sf ~/.dbmeta/cache/dbmeta-dev ~/.local/bin/dbmeta

# Clear extended attributes and re-sign (macOS)
xattr -cr ~/.dbmeta/cache/dbmeta-dev
codesign --force -s - ~/.dbmeta/cache/dbmeta-dev
```

### Testing the Binary

```bash
# Verify installation
dbmeta --help

# Initialize configuration
dbmeta init

# Run with console UI
dbmeta run --console
```

### Build Artifacts

- `dist/dbmeta` - Main binary
- `dist/dbmeta-<platform>-<arch>` - Platform-specific binary (e.g., `dbmeta-macos-arm64`)
- `build/` - Intermediate build files (can be deleted)

## Releases (GitHub Actions)

The project uses GitHub Actions to build and release binaries for all platforms.

### Triggering a Release

**Option 1: Tag-based release**
```bash
git tag dbmeta-v0.1.0
git push origin dbmeta-v0.1.0
```

**Option 2: Manual workflow dispatch**
1. Go to Actions > "Release dbmeta CLI"
2. Click "Run workflow"
3. Enter version (e.g., `0.1.0`)

### Release Pipeline

The workflow (`.github/workflows/release-dbmeta.yml`) builds binaries for:
- macOS (Apple Silicon): `dbmeta-macos-arm64`
- macOS (Intel): `dbmeta-macos-x64`
- Linux (x64): `dbmeta-linux-x64`
- Windows (x64): `dbmeta-windows-x64.exe`

All binaries are uploaded as GitHub Release assets.

### Installing Released Binaries

```bash
# One-liner (macOS/Linux)
curl -fsSL https://semantic-grid.io/install.sh | sh

# Or download manually from GitHub Releases
```

## Architecture

See [v2 Architecture](../../docs/future/v2-architecture.md) for the full system design.
