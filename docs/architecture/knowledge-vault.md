# Knowledge Vault Architecture

## Overview

The Knowledge Vault is a bash-accessible storage system for db-meta-v2 that enables Claude to read, search, and append knowledge using native bash commands. It stores prompt instructions, query examples, learnings from failures, and schema notes.

## Design Principles

1. **Bash-native** - Claude already knows bash; no custom API to learn
2. **Append-only writes** - No overwrites, no conflicts, full audit trail
3. **Read flexibility** - Full bash power for searching and exploring
4. **Deployment agnostic** - Works locally or in server mode
5. **Optional sharing** - Local testers can sync to shared cloud storage

## Architecture

### Deployment Modes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DEPLOYMENT MODES                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Server MCP (K8s)              Local MCP (Solo)         Local MCP (Team)    │
│  ┌─────────────┐               ┌─────────────┐          ┌─────────────┐     │
│  │   Pod       │               │  Tester     │          │  Tester A   │     │
│  │ /data/vault │               │ ~/.db-meta/ │          │ /data/vault │     │
│  │   (PVC)     │               │   vault/    │          │     ↕ sync  │     │
│  └─────────────┘               └─────────────┘          └──────┬──────┘     │
│        │                             │                         │            │
│   shared by all               local only                  S3 bucket         │
│   pod requests                                           (shared)           │
│                                                                             │
│  VAULT_BACKEND=local          VAULT_BACKEND=local       VAULT_BACKEND=s3    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Directory Structure (Flat)

The `/data` directory uses a flat structure (no provider_id nesting). The `PROVIDER_ID` 
is metadata stored in config, not a directory layer.

```
/data/                              # PVC root
├── .oauth/                         # OAuth session storage (DiskStore) - SENSITIVE
├── schema_descriptions.yaml        # Onboarding output: table/column descriptions
├── onboarding_state.yaml           # Onboarding wizard state
├── domain_model.md                 # Generated domain model (migrates to vault)
└── vault/                          # Knowledge vault (bash-accessible)
    ├── PROTOCOL.md                 # How to use the vault (executable docs)
    ├── instructions/
    │   ├── sql_rules.md            # General SQL generation rules
    │   ├── dialect_trino.md        # Trino-specific gotchas
    │   ├── dialect_clickhouse.md   # ClickHouse-specific gotchas
    │   └── domain.md               # Domain-specific guidance
    ├── examples/
    │   └── {uuid}.yaml             # Individual query examples (flat, no domain subdirs)
    ├── learnings/
    │   ├── failures/
    │   │   └── {uuid}.yaml         # Failed query records
    │   ├── patterns.md             # Discovered optimization patterns
    │   └── schema_gotchas.md       # Schema quirks and workarounds
    └── schema/
        └── {table_name}.md         # Human-readable schema notes
```

**Note:** The bash tool is jailed to `/data/vault/` only. It cannot access `/data/.oauth/` 
(contains sensitive OAuth tokens) or other files in `/data/`.

### File Formats

**Query Example** (`examples/{domain}/{uuid}.yaml`):
```yaml
id: 550e8400-e29b-41d4-a716-446655440000
created: 2026-01-10T12:00:00Z
session_id: abc123
intent: "Count unique devices per venue in the last 7 days"
keywords:
  - device
  - venue
  - count
  - weekly
sql: |
  SELECT 
    venue_id,
    COUNT(DISTINCT device_id) as device_count
  FROM radius_sessions
  WHERE session_start >= CURRENT_DATE - INTERVAL '7' DAY
  GROUP BY venue_id
tables:
  - radius_sessions
validated: true
execution_time_ms: 1250
notes: "Uses session_start index for efficient date filtering"
```

**Failure Record** (`learnings/failures/{uuid}.yaml`):
```yaml
id: 660e8400-e29b-41d4-a716-446655440001
created: 2026-01-10T12:05:00Z
session_id: abc123
intent: "Get device connection history"
sql: |
  SELECT * FROM device_connections
  WHERE timestamp > '2026-01-01'
error: |
  Table 'device_connections' does not exist
resolution: "Use radius_sessions table instead, join with devices"
supersedes: null  # or UUID of entry this corrects
```

**Supersede Pattern** (for corrections):
```yaml
# New file that corrects an old one
id: 770e8400-e29b-41d4-a716-446655440002
created: 2026-01-10T12:10:00Z
supersedes: 550e8400-e29b-41d4-a716-446655440000
reason: "Wrong date function for Trino"
# ... corrected content
```

## Bash Tool Implementation

### Allowed Commands

```python
ALLOWED_COMMANDS = {
    # Read operations
    "cat", "grep", "find", "ls", "head", "tail", "wc",
    "sort", "uniq", "diff", "less",
    
    # Write operations (append-only enforced by convention)
    "mkdir", "touch", "tee",
    
    # Utilities
    "echo", "date", "uuidgen",
}

BLOCKED_PATTERNS = [
    "rm ", "rm\t", "rmdir",     # No deletions
    "mv ", "mv\t",              # No moves (would lose history)  
    "> ",  # No overwrites (only >> append or heredoc to new file)
    "curl", "wget",             # No network
    "$(", "`",                  # No command substitution
    "|sh", "|bash",             # No shell injection
]
```

### Tool Definition

```python
@mcp.tool(name="shell")
async def shell(command: str) -> dict:
    """
    Run bash command in the knowledge vault.
    
    Available commands: cat, grep, find, ls, head, tail, wc, sort, uniq, diff, mkdir, tee, echo
    
    Working directory: /data/vault
    
    Examples:
        grep -ri "venue" examples/
        cat instructions/sql_rules.md
        find examples -name "*.yaml" -mtime -7
        cat > examples/wifi/$(uuidgen).yaml << 'EOF'
        ...
        EOF
    
    Args:
        command: Bash command to execute
        
    Returns:
        stdout: Command output
        stderr: Error output (if any)
        exit_code: Command exit code
    """
    settings = get_settings()
    vault_path = settings.vault_path
    
    # Validate command
    validation = validate_command(command)
    if not validation.ok:
        return {"error": validation.message, "exit_code": 1}
    
    # Execute in sandbox
    result = await run_sandboxed(
        command,
        cwd=vault_path,
        timeout=30,
        env={"VAULT_PATH": vault_path}
    )
    
    # If write operation and S3 backend, sync
    if validation.is_write and settings.vault_backend == "s3":
        await vault_sync.push_new_files()
    
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode
    }
```

### Command Validation

```python
@dataclass
class CommandValidation:
    ok: bool
    message: str = ""
    is_write: bool = False

def validate_command(command: str) -> CommandValidation:
    """Validate bash command against security rules."""
    
    # Check blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if pattern in command:
            return CommandValidation(
                ok=False, 
                message=f"Pattern '{pattern.strip()}' not allowed"
            )
    
    # Parse base command
    try:
        parts = shlex.split(command)
        base_cmd = parts[0] if parts else ""
    except ValueError:
        # Allow heredocs which shlex can't parse
        base_cmd = command.split()[0] if command.split() else ""
    
    if base_cmd not in ALLOWED_COMMANDS:
        return CommandValidation(
            ok=False,
            message=f"Command '{base_cmd}' not allowed. Permitted: {sorted(ALLOWED_COMMANDS)}"
        )
    
    # Detect write operations
    is_write = any(op in command for op in [">>", "<<", "tee", "mkdir", "touch"])
    # Heredoc to new file is allowed
    if "> " not in command and "cat >" in command and "<<" in command:
        is_write = True
    
    return CommandValidation(ok=True, is_write=is_write)
```

## S3 Sync Layer

For team deployments with shared knowledge:

```python
class VaultSync:
    """Bidirectional sync between local vault and S3."""
    
    def __init__(self, bucket: str, prefix: str, local_path: Path):
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/"
        self.local_path = local_path
        self.s3 = boto3.client("s3")
    
    async def pull(self) -> int:
        """
        Pull new files from S3 to local.
        Called on startup and periodically.
        Returns number of new files.
        """
        # List remote files
        remote_files = await self._list_remote()
        local_files = await self._list_local()
        
        # Download files we don't have
        new_files = remote_files - local_files
        for key in new_files:
            local_dest = self.local_path / key
            local_dest.parent.mkdir(parents=True, exist_ok=True)
            self.s3.download_file(self.bucket, self.prefix + key, str(local_dest))
        
        return len(new_files)
    
    async def push_new_files(self) -> int:
        """
        Push new local files to S3.
        Called after write operations.
        Returns number of pushed files.
        """
        remote_files = await self._list_remote()
        local_files = await self._list_local()
        
        # Upload files that don't exist remotely
        new_files = local_files - remote_files
        for key in new_files:
            local_src = self.local_path / key
            self.s3.upload_file(str(local_src), self.bucket, self.prefix + key)
        
        return len(new_files)
    
    async def _list_remote(self) -> set[str]:
        """List all keys in S3 under prefix."""
        keys = set()
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"].removeprefix(self.prefix)
                keys.add(key)
        return keys
    
    async def _list_local(self) -> set[str]:
        """List all files in local vault."""
        files = set()
        for path in self.local_path.rglob("*"):
            if path.is_file():
                files.add(str(path.relative_to(self.local_path)))
        return files
```

## PROTOCOL.md (Executable Documentation)

This file lives in the vault and teaches Claude how to use it:

```markdown
# Knowledge Vault Protocol

## On Session Start
```bash
cat /data/vault/PROTOCOL.md
```

## Before Generating SQL

### 1. Check for existing examples
```bash
grep -ri "keyword1\|keyword2" examples/
```

### 2. If match found, read it
```bash
cat examples/{domain}/{file}.yaml
```

### 3. Check for relevant learnings
```bash
grep -i "table_name" learnings/patterns.md
grep -l "table_name" learnings/failures/*.yaml | head -3 | xargs cat
```

### 4. Check domain-specific instructions
```bash
cat instructions/domain_{domain}.md
```

## After Successful Query

Save as example for future:
```bash
cat > examples/{domain}/$(uuidgen).yaml << 'EOF'
id: {will be filename}
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

Record the failure:
```bash
cat > learnings/failures/$(uuidgen).yaml << 'EOF'
id: {will be filename}
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

## {Pattern Name}
- **Issue**: {what goes wrong}
- **Fix**: {what to do instead}
- **Example**: `{code snippet}`
EOF
```

## Correcting a Mistake

Create new entry that supersedes the old:
```bash
cat > examples/{domain}/$(uuidgen).yaml << 'EOF'
id: {new uuid}
created: $(date -Iseconds)
supersedes: {old uuid}
reason: "why the old one was wrong"
# ... corrected content
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

# View superseded chain
grep -l "supersedes:" examples/**/*.yaml
```
```

## Configuration

```python
class VaultSettings(BaseSettings):
    """Knowledge vault configuration."""
    
    # Backend: "local" or "s3"
    vault_backend: Literal["local", "s3"] = "local"
    
    # Local path (always used, even with S3 as cache)
    vault_path: str = "/data/vault"
    
    # S3 settings (only used if vault_backend == "s3")
    vault_s3_bucket: str | None = None
    vault_s3_prefix: str = "knowledge/"
    vault_s3_region: str = "us-east-1"
    
    # Sync settings
    vault_sync_on_startup: bool = True
    vault_sync_interval_seconds: int = 300  # 5 minutes
    
    model_config = SettingsConfigDict(env_prefix="")
```

### Environment Variables

```bash
# Server deployment (K8s) - local PVC
VAULT_BACKEND=local
VAULT_PATH=/data/vault

# Local solo tester
VAULT_BACKEND=local
VAULT_PATH=~/.db-meta/vault

# Local team with shared S3
VAULT_BACKEND=s3
VAULT_PATH=/tmp/vault-cache
VAULT_S3_BUCKET=myorg-db-meta-vault
VAULT_S3_PREFIX=knowledge/
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

## Migration Plan

### Phase 1: Core Implementation
1. Add `VaultSettings` to config
2. Implement `shell` tool with command validation
3. Create vault directory structure
4. Write PROTOCOL.md

### Phase 2: Migrate Existing Content
1. Convert `instructions.yaml` → `instructions/*.md`
2. Convert `examples.yaml` → `examples/{domain}/*.yaml`
3. Update existing tools to reference vault

### Phase 3: S3 Backend (Optional)
1. Implement `VaultSync` class
2. Add sync-on-startup logic
3. Add background sync task
4. Test multi-tester scenarios

### Phase 4: Integration
1. Update `get_data` tool to check vault before generating SQL
2. Add auto-save of successful queries
3. Add auto-record of failures
4. Add `vault_refresh` tool for manual sync

## Security Considerations

1. **Command sandboxing** - Strict allowlist, no shell expansion
2. **Path containment** - Bash jailed to `/data/vault/` only, cannot access `/data/.oauth/` or parent
3. **No deletions** - Append-only preserves audit trail
4. **No network** - curl/wget blocked
5. **S3 IAM** - Minimal permissions (GetObject, PutObject, ListBucket)
6. **No secrets in vault** - Connection strings stay in env vars
7. **OAuth isolation** - `.oauth/` directory contains encrypted tokens, completely inaccessible to bash tool

## Future Enhancements

1. **Compaction job** - Periodic consolidation of superseded entries
2. **Search index** - SQLite FTS or similar for faster keyword search
3. **Embeddings** - Vector search over examples for semantic matching
4. **Metrics** - Track which examples get reused, which patterns help
5. **Multi-tenant** - Namespace vault by organization/project
