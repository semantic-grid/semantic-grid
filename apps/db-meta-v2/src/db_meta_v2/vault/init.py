"""Vault initialization and directory structure management."""

import logging
from pathlib import Path

from db_meta_v2.config import get_settings

logger = logging.getLogger(__name__)

# Default PROTOCOL.md content
PROTOCOL_MD = """# Knowledge Vault Protocol

This vault stores query examples, learnings, and instructions for SQL generation.
Use the `shell` tool to interact with it via bash commands.

## On Session Start

Read this protocol:
```bash
cat PROTOCOL.md
```

## Before Generating SQL

### 1. Search for existing examples
```bash
grep -ri "keyword1\\|keyword2" examples/
```

### 2. If match found, read it
```bash
cat examples/{matched_file}.yaml
```

### 3. Check for relevant learnings
```bash
grep -i "table_name" learnings/patterns.md
```

### 4. Check domain instructions
```bash
cat instructions/domain.md
```

## After Successful Query

Save as example for future use:
```bash
cat > examples/$(uuidgen).yaml << 'EOF'
created: $(date -Iseconds)
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

## After Failed Query

Record the failure for learning:
```bash
cat > learnings/failures/$(uuidgen).yaml << 'EOF'
created: $(date -Iseconds)
intent: "what user asked"
sql: |
  SELECT ...
error: |
  error message
resolution: "what should be done instead"
EOF
```

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

## Correcting a Mistake

Create new entry that supersedes the old:
```bash
cat > examples/$(uuidgen).yaml << 'EOF'
created: $(date -Iseconds)
supersedes: {old_uuid}
reason: "why the old one was wrong"
intent: "..."
sql: |
  SELECT ...
EOF
```

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

# Initial files to create (path -> content)
VAULT_FILES = {
    "PROTOCOL.md": PROTOCOL_MD,
    "instructions/sql_rules.md": "# SQL Generation Rules\n\nAdd general SQL rules here.\n",
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

    # Create initial files if missing
    for file_path, content in VAULT_FILES.items():
        full_path = vault_path / file_path
        if not full_path.exists():
            full_path.write_text(content)
            logger.info(f"Created vault file: {file_path}")
            created = True

    if created:
        logger.info("Vault structure initialized")
    else:
        logger.debug("Vault structure already exists")

    return created
