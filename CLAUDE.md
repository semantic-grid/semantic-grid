# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Semantic Grid is an open-source natural language interface for exploring complex datasets (primarily crypto/blockchain). Instead of fixed dashboards, users describe what they want to see in natural language, and the system generates live, interactive tables. The system consists of three main applications orchestrated as a monorepo.

## System Architecture

The codebase is organized as a monorepo with three main applications:

### 1. Flow Manager (`apps/fm-app`) - Python FastAPI
The core orchestration engine that:
- Coordinates user requests through prompts, templates, and MCP (Model Context Protocol) tools
- Manages agentic workflows using a structured pipeline with explicit logging and state persistence
- Uses slot-based prompt composition with Jinja templates
- Validates and repairs LLM-generated SQL through iterative critic loops
- Integrates with MCP servers for database operations

Key components:
- `fm_app/prompt_assembler/` - Prompt pack assembly and template rendering
- `fm_app/mcp_servers/` - MCP integration for database and other services
- Workflow orchestration based on Celery for async task processing

### 2. DB-Meta MCP Server (`apps/db-meta`) - Python FastAPI
A structured interface to database schema and metadata that:
- Introspects database schemas using SQLAlchemy
- Merges structural information with YAML-based descriptions
- Provides human-readable schema prompts for LLM-driven query generation
- Runs query validation (EXPLAIN, cost estimation) as a safety layer
- Serves as an MCP server exposing tools like `describe_provider`, `get_prompt_bundle`, `explain_analyze`

### 3. Web Frontend (`apps/web`) - Next.js
The user-facing application that:
- Provides conversational querying interface with real-time refinement
- Communicates with Flow Manager via REST API
- Uses Auth0 for authentication
- Built with Material-UI (MUI) components including MUI X Data Grid Pro
- Uses Drizzle ORM with PostgreSQL for application data

### 4. CMS (`apps/cms`) - Payload CMS
Content management system for managing static content and configuration.

## Development Setup & Commands

### Prerequisites
- **Node.js**: >=20
- **Package Manager**: Bun 1.2.10 (preferred for root workspace)
- **Python**: 3.13
- **Python Package Manager**: UV (for Python apps)

### Monorepo Commands (from root)

```bash
# Install all dependencies
bun install

# Run all apps in development mode (parallel)
npm run dev

# Setup specific apps
npm run setup:fm    # Flow Manager setup
npm run setup:dbm   # DB-Meta setup

# Build all apps
npm run build

# Linting and formatting
npm run lint        # Run linters across all apps
npm run format      # Format code with Prettier
npm run check-types # TypeScript type checking
npm run test        # Run tests across all apps
```

### Flow Manager (fm-app) Commands

```bash
cd apps/fm-app

# Install UV package manager (if not installed)
# Linux/MacOS: curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install dependencies
uv sync --locked

# Save/update dependencies
uv lock

# Lint and format
uv run ruff check . --fix

# Database migrations
alembic upgrade head                    # Apply migrations
alembic revision -m "Description"       # Create new migration

# Local development database
docker compose up -d                    # Start dev DB
docker compose down                     # Stop DB
docker compose down -v                  # Stop and delete DB

# Docker build
docker buildx build --platform linux/amd64 -f apps/fm-app/Dockerfile -t <org>/fm_app:latest .
```

### DB-Meta Commands

```bash
cd apps/db-meta

# Install dependencies
uv sync --locked

# Lint and format
uv run ruff check . --fix

# Run the db-meta server
./run.sh

# Docker build
docker buildx build --platform linux/amd64 -f apps/db-meta/Dockerfile -t <org>/dbmeta:latest .
```

### Web Frontend Commands

```bash
cd apps/web

# Install dependencies
bun install

# Development
bun dev

# Build
bun build

# Start production server
bun start

# Lint
bun lint

# Generate OpenAPI types from API
npm run generate        # From production API
npm run generate_local  # From local API

# Docker build
docker buildx build --file apps/web/Dockerfile -t <org>/web:latest .
```

## Key Architecture Patterns

### Prompt Packs & Template System
The system uses a sophisticated template system for LLM prompts:

- **System Packs**: Base templates in `packages/resources/<app>/system-pack/v1.0.0/`
- **Client Overlays**: Tenant-specific overrides in `packages/client-configs/<client>/<env>/<component>/overlays/`
- **Slot-based Composition**: Templates use Jinja2 with slot files (`slots/<slot>/prompt.md`)
- **Defaults & Fallbacks**: Includes prioritized candidates (e.g., slot-specific or `__default/domain.md`)
- **Merging Strategy**: Deep merge with configurable list strategies (append, unique, by_id, replace)

Example slot structure:
```
system-pack/v1.0.0/slots/
├── planner/
│   ├── prompt.md
│   └── domain.md
├── interactive_query/
├── data_analysis/
└── __default/
    └── domain.md
```

### Request Flow (Typical)
1. User submits natural language request via Web UI
2. Flow Manager assembles effective prompt tree (system pack + client overlays)
3. Planner proposes next tool and arguments (JSON)
4. Tool Selector enforces policy (validate before execute)
5. Codegen generates SQL (deterministic or LLM-assisted)
6. Validation via db-meta MCP server (`explain_analyze`)
7. Repair Loop (if needed): critic rewrites SQL, loop until valid
8. Execute query when validated
9. Return results with lineage (prompt hashes, MCP call hashes)

### MCP (Model Context Protocol) Integration
MCP servers provide structured tool interfaces:
- `describe_provider(client?, env?)` - Discover profiles/resources
- `get_prompt_bundle(profile, ...)` - Get schema descriptions, examples, instructions
- `explain_analyze(sql, profile?, ...)` - Validate SQL with execution plan

### Environment Configuration
Both Python apps use Pydantic Settings with `.env` files:

**Flow Manager** requires:
- Database credentials (operational DB)
- Warehouse database credentials (multiple profiles: wh, wh_new, wh_v2)
- Auth0 configuration
- LLM API keys (Anthropic, OpenAI)

**DB-Meta** requires:
- Warehouse database credentials (matching fm-app profiles)
- Vector DB configuration (Milvus)
- OpenAI API key for embeddings
- Pack resources directory path

**Web Frontend** requires (see turbo.json for complete list):
- Auth0 configuration
- API endpoint URLs
- LLM API keys
- AWS credentials (for S3)
- MUI X license key

### Database Strategy
- **Operational DB**: PostgreSQL (stores flow state, user data, sessions)
- **Warehouse DBs**: Multiple ClickHouse instances (different profiles/versions)
- **Vector DB**: Milvus (for semantic search over prompts/examples)
- **Migrations**: Alembic for schema versioning (fm-app only)

## Code Style & Standards

### Python Apps
- **Formatter**: Black (line-length: 88)
- **Linter**: Ruff with flake8-compatible rules
- **Import Sorting**: isort with black profile
- **Type Hints**: Encouraged but not strictly enforced
- Use `uv run ruff check . --fix` before committing

### TypeScript/JavaScript
- **Linter**: ESLint with Airbnb config + TypeScript
- **Formatter**: Prettier
- **Import Sorting**: eslint-plugin-simple-import-sort
- Follows Next.js conventions for the web app

## Deployment

### Infrastructure
- Kubernetes deployments configured in `infra/` and `apps/*/k8s/`
- Helm charts available for cloud deployments
- Docker Compose for local development

### Build Requirements
- Multi-platform builds use `docker buildx` for linux/amd64
- Each app has its own Dockerfile optimized for production
- Turbo handles build caching and dependency ordering

### Environment-Specific Configs
- Local: `apps/*/k8s/overlays/local/`
- Cloud: `apps/*/k8s/overlays/cloud/`
- Client configs support multi-tenancy via `packages/client-configs/`

## Working with This Codebase

### Adding a New Prompt Slot
1. Create `packages/resources/fm_app/system-pack/v1.0.0/slots/<slot-name>/prompt.md`
2. Add optional fragments like `domain.md`, `system.md`
3. Reference in flow orchestration code
4. Add client-specific overlays if needed

### Adding a New MCP Tool
1. Register provider in fm-app settings
2. Create client in `fm_app/mcp_servers/`
3. Reference in slot metadata (`requires.mcp`)
4. Update validation policies if needed

### Database Schema Changes
1. Create migration: `alembic revision -m "description"`
2. Edit generated migration file in `apps/fm-app/alembic/versions/`
3. Apply: `alembic upgrade head`
4. Never modify applied migrations

### Working with Multiple Database Profiles
The system supports multiple warehouse database instances (profiles):
- `wh` - Legacy/original database
- `wh_new` - Newer database instance
- `wh_v2` - Current production database

Configure all three in both fm-app and db-meta `.env` files with corresponding `_port`, `_server`, `_params`, and `_db` suffixes.

## Important Notes

- This is a monorepo managed by Turbo; always run setup tasks through Turbo to respect dependencies
- Python apps require Python 3.13 (specified in pyproject.toml)
- The prompt pack system is versioned; always increment version when making breaking changes
- MCP calls are traced and hashed for lineage/reproducibility
- Never commit `.env` files or embed secrets in code
- The system validates all LLM-generated SQL before execution as a safety measure
