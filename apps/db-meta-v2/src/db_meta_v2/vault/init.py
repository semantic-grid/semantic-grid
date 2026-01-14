"""Vault initialization and directory structure management."""

import logging
from pathlib import Path

from db_meta_v2.config import get_settings

logger = logging.getLogger(__name__)

# Default PROTOCOL.md content
PROTOCOL_MD = """# Knowledge Vault Protocol

This vault stores query examples, learnings, and instructions for SQL generation.
Use the `shell` tool to interact with it via bash commands.

## CRITICAL: Use Cached Schema First

**NEVER introspect the database directly if cached schema exists.**

On first run, dbmeta discovers and caches the full database schema. This cache contains:
- `schema_descriptions.yaml` - Complete table/column descriptions with semantic annotations
- `instructions/domain.md` - Domain model explaining relationships and business logic

**Before ANY database introspection:**
1. Check if `schema_descriptions.yaml` exists
2. If it exists, use it as your primary schema reference
3. Only call `list_catalogs()`, `list_schemas()`, `list_tables()` if cache is missing

```bash
# Check for cached schema
cat schema_descriptions.yaml 2>/dev/null | head -50
```

If the file exists and has content, USE IT instead of calling discovery tools.

## CRITICAL: Read Domain Model

**ALWAYS read the domain model before writing queries.**

The domain model (`instructions/domain.md`) contains:
- Business entity relationships
- Key concepts and terminology
- Important joins and aggregations
- Common query patterns

```bash
cat instructions/domain.md
```

This is NOT optional - it contains critical context for correct SQL generation.

## Database Hierarchy

**ALWAYS start discovery at the CATALOG level, not schema level.**

Many databases use 3-level hierarchy: `catalog.schema.table`
- WRONG: `list_tables(schema="radius")` - misses the catalog
- RIGHT: `list_catalogs()` first, then drill down

Before ANY query work:
1. Check cached schema first (`schema_descriptions.yaml`)
2. Check `instructions/sql_rules.md` for hierarchy rules
3. Check domain model (`instructions/domain.md`)
4. Only if cache missing: use `list_catalogs()` to discover

Failing to do this will cause "table not found" errors.

## IMPORTANT: User Transparency

**ALWAYS inform the user when you save or discover knowledge.**

After saving anything to the vault, add a footnote to your response:

> **Knowledge saved**: Saved this query as example `{uuid}` for future reference.

When you find and use existing knowledge, mention it:

> **Using prior knowledge**: Found similar query in `examples/{file}`.

This helps users understand what the system is learning and builds trust.

## On Session Start

1. Read this protocol:
```bash
cat PROTOCOL.md
```

2. Check for cached schema (USE THIS FIRST):
```bash
cat schema_descriptions.yaml 2>/dev/null | head -100
```

3. Read domain model (REQUIRED):
```bash
cat instructions/domain.md
```

4. Check database structure rules:
```bash
cat instructions/sql_rules.md
```

## Before Generating SQL

### 1. Use cached schema (PRIMARY SOURCE)
```bash
# Search for relevant tables/columns in cache
grep -i "keyword" schema_descriptions.yaml
```

### 2. Search for existing examples
```bash
grep -ri "keyword1\\|keyword2" examples/
```

### 3. If match found, read it
```bash
cat examples/{matched_file}.yaml
```

### 4. Check for relevant learnings
```bash
grep -i "table_name" learnings/patterns.md
```

### 5. Reference domain model for context
The domain model should already be loaded from session start.
If not, read it now:
```bash
cat instructions/domain.md
```

## After Successful Query

Save as example for future use. First generate a UUID:
```bash
uuidgen
```

Then use that UUID in the filename (replace YOUR_UUID with the output):
```bash
cat >> examples/YOUR_UUID.yaml << 'EOF'
intent: "description of what user asked"
keywords:
  - keyword1
  - keyword2
sql: |
  SELECT ...
tables:
  - table1
validated: true
EOF
```

**Then tell the user**: "Saved this query as example `{uuid}` for future reference."

## After Failed Query

Record the failure for learning. First generate a UUID:
```bash
uuidgen
```

Then save the failure:
```bash
cat >> learnings/failures/YOUR_UUID.yaml << 'EOF'
intent: "what user asked"
sql: |
  SELECT ...
error: |
  error message
resolution: "what should be done instead"
EOF
```

**Then tell the user**: "Recorded this issue in `failures/{uuid}` to avoid repeating it."

## When Discovering a Pattern

Append to patterns file:
```bash
cat >> learnings/patterns.md << 'EOF'

## Pattern Name
- **Issue**: what goes wrong
- **Fix**: what to do instead
- **Example**: `code snippet`
EOF
```

**Then tell the user**: "Added pattern '{name}' to learnings for future queries."

## Correcting a Mistake

Create new entry that supersedes the old. First generate a UUID:
```bash
uuidgen
```

Then create the corrected entry:
```bash
cat >> examples/YOUR_UUID.yaml << 'EOF'
supersedes: {old_uuid}
reason: "why the old one was wrong"
intent: "..."
sql: |
  SELECT ...
EOF
```

**Then tell the user**: "Corrected example `{old_uuid}` with new version `{new_uuid}`."

## Useful Commands

```bash
# List all examples
find examples -name "*.yaml" | wc -l

# Recent examples (last 7 days)
find examples -name "*.yaml" -mtime -7

# Search across everything
grep -ri "search term" .

# Recent failures
ls -lt learnings/failures/*.yaml | head -10
```
"""

# Directory structure to create
VAULT_DIRS = [
    "instructions",
    "examples",
    "learnings",
    "learnings/failures",
    "schema",
]

# Files to always overwrite (system-controlled, shipped with each deploy)
VAULT_SYSTEM_FILES = {
    "PROTOCOL.md": PROTOCOL_MD,
}

# Initial files to create only if missing (user-editable templates)
VAULT_TEMPLATE_FILES = {
    "instructions/sql_rules.md": """# SQL Generation Rules

## Database Hierarchy

Check the database dialect to understand the naming hierarchy:

- **Trino/Presto**: 3-level → `catalog.schema.table` (e.g., `iceberg.radius.wifi_qm_v2`)
- **PostgreSQL**: 2-level → `schema.table` (e.g., `public.users`)
- **MySQL**: 2-level → `database.table`
- **ClickHouse**: 2-level → `database.table`

**ALWAYS verify the hierarchy before writing queries.**

Use `list_catalogs()` first if available. If it returns catalogs, you MUST include
the catalog in all table references.

## Common Mistakes

1. Using 2-level path when 3-level is required
   - WRONG: `SELECT * FROM radius.wifi_qm_v2`
   - RIGHT: `SELECT * FROM iceberg.radius.wifi_qm_v2`

2. Assuming schema names without checking
   - Always use `list_schemas(catalog="...")` to discover actual schema names

Add domain-specific SQL rules below this line.
---

""",
    "instructions/domain.md": "# Domain Knowledge\n\nAdd domain-specific guidance here.\n",
    "learnings/patterns.md": "# Query Patterns\n\nDocument successful patterns here.\n",
    "learnings/schema_gotchas.md": "# Schema Gotchas\n\nDocument schema quirks here.\n",
}


def ensure_vault_structure() -> bool:
    """Ensure vault directory structure exists.

    Creates the vault directory and subdirectories if they don't exist.
    Also creates initial template files if missing.

    Returns:
        True if vault was created/updated, False if it already existed unchanged
    """
    settings = get_settings()
    vault_path = Path(settings.vault_path)
    created = False

    # Create vault root
    if not vault_path.exists():
        vault_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created vault directory: {vault_path}")
        created = True

    # Create subdirectories
    for subdir in VAULT_DIRS:
        dir_path = vault_path / subdir
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created vault subdirectory: {subdir}")
            created = True

    # Always overwrite system-controlled files (e.g., PROTOCOL.md)
    for file_path, content in VAULT_SYSTEM_FILES.items():
        full_path = vault_path / file_path
        full_path.write_text(content)
        logger.info(f"Updated system file: {file_path}")
        created = True

    # Create template files only if missing (user-editable)
    for file_path, content in VAULT_TEMPLATE_FILES.items():
        full_path = vault_path / file_path
        if not full_path.exists():
            full_path.write_text(content)
            logger.info(f"Created template file: {file_path}")
            created = True

    if created:
        logger.info("Vault structure initialized")
    else:
        logger.debug("Vault structure already exists")

    return created
