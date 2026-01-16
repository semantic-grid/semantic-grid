# dbmeta Connections Refactor

## Overview

Refactor dbmeta's file system layout to support multiple database connections with self-contained configurations, unifying local CLI and server-based deployments.

## Current Issues

1. **Naming**: `providers` is generic - `connections` is clearer for database connections
2. **Split config**: Global `config.yaml` in root, but connection-specific data in `providers/default/`
3. **Global vault**: `vault/` is shared but should be per-connection (different DBs need different examples, learnings, schema)
4. **Container mounting**: When mounting only `vault/` in container, agent loses access to `schema_descriptions.yaml` and `domain_model.md`
5. **Multi-connection**: No way to manage multiple database connections with meaningful names
6. **Shell mode broken**: PROTOCOL.md tells agent to `cat schema_descriptions.yaml` but it's in `providers/`, not `vault/`!

## Mode Analysis

### Detailed Mode (multi-tool)
- Tools access files via Python: `load_schema_descriptions()`, domain tools, etc.
- Files accessed: `providers/{id}/schema_descriptions.yaml`, `providers/{id}/domain_model.md`
- Works because Python code knows both paths

### Shell Mode
- Agent uses `shell` tool with bash commands from `vault/` as working directory
- PROTOCOL.md instructs: `cat schema_descriptions.yaml`, `cat instructions/domain.md`
- **BUG**: `schema_descriptions.yaml` is in `providers/{id}/`, NOT in `vault/`!
- Agent can't access schema cache in shell mode without full path knowledge

### The Fix
Unify everything under one connection directory. Both modes access the same paths:
- Detailed mode: Python reads `connections/{name}/schema/descriptions.yaml`
- Shell mode: Agent runs `cat schema/descriptions.yaml` from connection root

## Current Structure

```
~/.dbmeta/                              # LOCAL (CLI)
├── cache/
├── config.yaml                         # Global config with database_url
├── providers/default/
│   ├── domain_model.md
│   ├── onboarding_state.yaml
│   └── schema_descriptions.yaml
├── resources/
└── vault/
    ├── PROTOCOL.md
    ├── examples/
    ├── instructions/
    ├── learnings/
    └── schema/

/data/vault/                            # SERVER (container)
├── PROTOCOL.md                         # Mounted as vault_path
├── examples/
├── instructions/
├── learnings/
└── schema/
# Note: schema_descriptions.yaml and domain_model.md are elsewhere!
```

## Proposed Structure

```
~/.dbmeta/                              # LOCAL (CLI)
├── .version                            # Storage format version (e.g., "2")
├── cache/                              # Binary cache (unchanged)
│   └── dbmeta-*
├── config.yaml                         # Global settings only
└── connections/
    ├── default/                        # Self-contained connection
    │   ├── config.yaml                 # Connection-specific (DATABASE_URL, etc.)
    │   ├── state.yaml                  # Onboarding state
    │   ├── PROTOCOL.md
    │   ├── schema/
    │   │   ├── descriptions.yaml
    │   │   └── tables.yaml
    │   ├── domain/
    │   │   └── model.md
    │   ├── instructions/
    │   │   ├── sql_rules.md
    │   │   └── domain.md
    │   ├── examples/
    │   │   └── *.yaml
    │   └── learnings/
    │       ├── patterns.md
    │       ├── schema_gotchas.md
    │       └── failures/
    │
    └── trino-prod/                     # Another connection
        └── ... (same structure)

/data/connections/mydb/                 # SERVER (container) - mount entire connection
├── config.yaml                         # Or use env vars
├── state.yaml
├── PROTOCOL.md
├── schema/
├── domain/
├── instructions/
├── examples/
└── learnings/
```

## Configuration Files

### Global config (`~/.dbmeta/config.yaml`)

```yaml
# Global settings only - no database URL here
default_connection: default
log_level: INFO
```

### Connection config (`~/.dbmeta/connections/{name}/config.yaml`)

```yaml
# Connection-specific settings
database_url: trino://user:pass@host:8443/catalog/schema
tool_mode: shell
# Optional overrides
log_level: DEBUG
```

## Server Mode Configuration

Server mode uses environment variables, which map to the new structure:

| Env Variable | Description | Example |
|--------------|-------------|---------|
| `DATABASE_URL` | Database connection | `trino://...` |
| `CONNECTION_NAME` | Connection identifier | `mydb` |
| `CONNECTION_PATH` | Path to connection dir | `/data/connections/mydb` |
| `TOOL_MODE` | Tool exposure mode | `shell` |

When `CONNECTION_PATH` is set:
- All files are read/written relative to that path
- `config.yaml` in that path is optional (env vars take precedence)
- Single mount point gives agent access to everything

### Backward Compatibility

For existing deployments using `VAULT_PATH`:
- If `VAULT_PATH` is set but `CONNECTION_PATH` is not, use legacy behavior
- Log deprecation warning
- `PROVIDERS_DIR` continues to work for legacy `providers/{id}/` structure

## CLI Changes

### New Commands

```bash
# Connection management
dbmeta init [NAME]              # Create/update connection (default: "default")
dbmeta list                     # List all connections
dbmeta use NAME                 # Set default connection
dbmeta remove NAME              # Remove a connection

# Commands with connection targeting
dbmeta status [NAME]            # Status of specific or default connection
dbmeta status all               # Status of all connections
dbmeta config [NAME]            # Edit specific connection config
dbmeta config all               # Edit global config

# Start with specific connection
dbmeta start [NAME]             # Start MCP server for connection
```

### Examples

```bash
# Initial setup
dbmeta init                     # Creates "default" connection
dbmeta init prod-trino          # Creates "prod-trino" connection

# Managing multiple connections
dbmeta list
# Output:
#   * default (postgresql://localhost/mydb)
#     prod-trino (trino://trino.prod:8443/hive/default)
#     staging (trino://trino.staging:8443/hive/default)

dbmeta use prod-trino           # Switch default
dbmeta status all               # Show all connection statuses

# Claude Desktop integration
# Each connection gets its own MCP server entry
```

### Claude Desktop Config

```json
{
  "mcpServers": {
    "dbmeta": {
      "command": "dbmeta",
      "args": ["start"]
    },
    "dbmeta-prod": {
      "command": "dbmeta",
      "args": ["start", "prod-trino"]
    }
  }
}
```

## Code Changes

### 1. Config Module (`config.py`)

```python
class Settings(BaseSettings):
    # Global settings
    default_connection: str = "default"
    log_level: str = "INFO"
    
    # Connection settings (from env or connection config.yaml)
    connection_name: str = Field(default="default", env="CONNECTION_NAME")
    connection_path: str = Field(default="", env="CONNECTION_PATH")
    database_url: str = Field(default="", env="DATABASE_URL")
    tool_mode: str = Field(default="shell", env="TOOL_MODE")
    
    # Legacy (deprecated)
    vault_path: str = Field(default="", env="VAULT_PATH")
    providers_dir: str = Field(default="", env="PROVIDERS_DIR")
    
    @property
    def effective_connection_path(self) -> Path:
        """Get the effective connection path."""
        if self.connection_path:
            return Path(self.connection_path)
        # Local CLI mode
        return Path.home() / ".dbmeta" / "connections" / self.connection_name
```

### 2. Vault Module

Update to use connection-relative paths:

```python
def get_vault_path(subpath: str = "") -> Path:
    """Get path within current connection's vault."""
    settings = get_settings()
    base = settings.effective_connection_path
    return base / subpath if subpath else base

# Examples:
# get_vault_path("schema/descriptions.yaml")
# get_vault_path("examples")
# get_vault_path("PROTOCOL.md")
```

### 3. CLI Module

- Add connection argument to commands
- Implement `list`, `use`, `remove` commands
- Handle `all` keyword for bulk operations

### 4. Migration

```python
def migrate_to_connections():
    """Migrate from old structure to new connections structure."""
    old_vault = Path.home() / ".dbmeta" / "vault"
    old_providers = Path.home() / ".dbmeta" / "providers"
    old_config = Path.home() / ".dbmeta" / "config.yaml"
    
    new_connection = Path.home() / ".dbmeta" / "connections" / "default"
    
    if old_vault.exists() and not new_connection.exists():
        # Migrate vault contents
        # Migrate provider data
        # Update config.yaml
        # Leave old dirs for safety, log migration
```

## Version File

A `.version` file in `~/.dbmeta/` tracks the storage format version:

```
~/.dbmeta/.version
```

Contents: single line with version number (e.g., `2`)

| Version | Description |
|---------|-------------|
| (none)  | Legacy structure (vault/ + providers/) |
| 2       | Connections structure |

This eliminates guesswork for future migrations - just read the version file.

## Migration Path

### Version Detection

```python
def get_storage_version(base_path: Path) -> int:
    """Detect storage format version."""
    version_file = base_path / ".version"
    if version_file.exists():
        return int(version_file.read_text().strip())
    
    # Heuristics for legacy detection
    if (base_path / "vault").exists() or (base_path / "providers").exists():
        return 1  # Legacy
    if (base_path / "connections").exists():
        return 2  # New format (version file missing, but structure exists)
    
    return 0  # Fresh install
```

### Local CLI Migration

**Before (v1):**
```
~/.dbmeta/
├── config.yaml                         # database_url, provider_id, etc.
├── providers/default/
│   ├── schema_descriptions.yaml
│   ├── domain_model.md
│   └── onboarding_state.yaml
└── vault/
    ├── PROTOCOL.md
    ├── examples/
    ├── instructions/
    └── learnings/
```

**After (v2):**
```
~/.dbmeta/
├── .version                            # "2"
├── config.yaml                         # default_connection: default
└── connections/default/
    ├── config.yaml                     # database_url (moved from root)
    ├── state.yaml                      # renamed from onboarding_state.yaml
    ├── PROTOCOL.md                     # moved from vault/
    ├── schema/
    │   └── descriptions.yaml           # moved from providers/
    ├── domain/
    │   └── model.md                    # moved from providers/
    ├── instructions/                   # moved from vault/
    ├── examples/                       # moved from vault/
    └── learnings/                      # moved from vault/
```

**Migration steps:**
```python
def migrate_local_v1_to_v2():
    base = Path.home() / ".dbmeta"
    
    # 1. Create connections/default/
    conn_path = base / "connections" / "default"
    conn_path.mkdir(parents=True, exist_ok=True)
    
    # 2. Move vault/* -> connections/default/
    vault = base / "vault"
    if vault.exists():
        for item in ["PROTOCOL.md", "examples", "instructions", "learnings"]:
            src = vault / item
            if src.exists():
                shutil.move(src, conn_path / item)
    
    # 3. Move providers/default/* -> connections/default/
    provider = base / "providers" / "default"
    if provider.exists():
        # schema_descriptions.yaml -> schema/descriptions.yaml
        if (provider / "schema_descriptions.yaml").exists():
            (conn_path / "schema").mkdir(exist_ok=True)
            shutil.move(provider / "schema_descriptions.yaml", 
                       conn_path / "schema" / "descriptions.yaml")
        
        # domain_model.md -> domain/model.md
        if (provider / "domain_model.md").exists():
            (conn_path / "domain").mkdir(exist_ok=True)
            shutil.move(provider / "domain_model.md",
                       conn_path / "domain" / "model.md")
        
        # onboarding_state.yaml -> state.yaml
        if (provider / "onboarding_state.yaml").exists():
            shutil.move(provider / "onboarding_state.yaml",
                       conn_path / "state.yaml")
    
    # 4. Split config.yaml
    old_config = yaml.safe_load((base / "config.yaml").read_text())
    
    # Connection-specific config
    conn_config = {
        "database_url": old_config.pop("database_url", ""),
        "tool_mode": old_config.pop("tool_mode", "shell"),
    }
    (conn_path / "config.yaml").write_text(yaml.dump(conn_config))
    
    # Global config
    global_config = {
        "default_connection": "default",
        "log_level": old_config.get("log_level", "INFO"),
    }
    (base / "config.yaml").write_text(yaml.dump(global_config))
    
    # 5. Write version file
    (base / ".version").write_text("2")
    
    # 6. Clean up empty dirs (keep originals for safety during transition)
    logger.info("Migration complete. Old directories preserved for safety.")
```

### Server-Side Migration

**Before (v1):**
```
# Env vars
VAULT_PATH=/data/vault
PROVIDERS_DIR=/data/providers
PROVIDER_ID=default

# File structure
/data/
├── vault/
│   ├── PROTOCOL.md
│   ├── examples/
│   ├── instructions/
│   └── learnings/
└── providers/default/
    ├── schema_descriptions.yaml
    ├── domain_model.md
    └── onboarding_state.yaml
```

**After (v2):**
```
# Env vars (new)
CONNECTION_PATH=/data/connection

# Or (legacy compat)
VAULT_PATH=/data/vault              # Triggers migration
PROVIDERS_DIR=/data/providers       # Triggers migration

# File structure
/data/connection/                   # Single connection root
├── .version                        # "2"
├── config.yaml                     # Optional (env vars take precedence)
├── state.yaml
├── PROTOCOL.md
├── schema/
│   └── descriptions.yaml
├── domain/
│   └── model.md
├── instructions/
├── examples/
└── learnings/
```

**Server migration logic:**
```python
def migrate_server_v1_to_v2():
    settings = get_settings()
    
    # Detect legacy env vars
    if settings.vault_path and not settings.connection_path:
        logger.warning("VAULT_PATH is deprecated. Use CONNECTION_PATH instead.")
        
        vault = Path(settings.vault_path)
        providers = Path(settings.providers_dir) / settings.provider_id
        
        # Determine connection path
        # Option A: vault parent (e.g., /data/vault -> /data/connection)
        conn_path = vault.parent / "connection"
        
        # Option B: If PROVIDERS_DIR == VAULT_PATH parent, use that
        # This handles case where everything is under /data/
        
        conn_path.mkdir(parents=True, exist_ok=True)
        
        # Same migration logic as local, but different source paths
        # ... (move files)
        
        # Update settings to use new path
        os.environ["CONNECTION_PATH"] = str(conn_path)
        
        (conn_path / ".version").write_text("2")
```

### Kubernetes Deployment Update

**Before:**
```yaml
env:
  - name: VAULT_PATH
    value: /data/vault
  - name: PROVIDERS_DIR
    value: /data/providers
  - name: PROVIDER_ID
    value: default
volumes:
  - name: vault
    mountPath: /data/vault
  - name: providers  
    mountPath: /data/providers
```

**After:**
```yaml
env:
  - name: CONNECTION_PATH
    value: /data/connection
  # Legacy vars still work but log deprecation warning
volumes:
  - name: connection
    mountPath: /data/connection
```

### Migration Safety

1. **Non-destructive**: Original files are moved, not deleted
2. **Idempotent**: Running migration twice is safe (checks .version)
3. **Rollback**: Keep old dirs for one version cycle
4. **Logging**: Log all migration actions for debugging
5. **Validation**: After migration, verify key files exist

### Deprecation Timeline

| Version | Behavior |
|---------|----------|
| 0.2.0   | Introduce v2, auto-migrate, support both |
| 0.3.0   | Log warnings for v1 env vars |
| 0.4.0   | Remove v1 support, require migration |

## Kubernetes/Container Deployment

### Single Connection

```yaml
volumes:
  - name: dbmeta-connection
    persistentVolumeClaim:
      claimName: dbmeta-mydb

containers:
  - name: dbmeta
    env:
      - name: CONNECTION_PATH
        value: /data/connection
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: db-credentials
            key: url
    volumeMounts:
      - name: dbmeta-connection
        mountPath: /data/connection
```

### Multiple Connections (separate deployments)

Each connection gets its own deployment with its own PVC and secrets.

## Open Questions

1. **S3 backend**: How does this interact with `vault_backend: s3`?
   - Proposal: S3 syncs entire connection directory, not just vault subdirectory
   
2. **Shared resources**: Should some things be shared across connections (e.g., SQL dialect rules)?
   - Proposal: Keep dialect rules in bundled resources, connection-specific rules in `instructions/`

3. **Connection isolation**: Should connections share any state?
   - Proposal: No, each connection is fully isolated

## Mode-Specific Changes

### Detailed Mode (multi-tool)

**Before:**
```python
# schema_store.py
def get_schema_file_path(provider_id):
    return Path(settings.providers_dir) / provider_id / "schema_descriptions.yaml"
```

**After:**
```python
def get_schema_file_path(provider_id):
    return get_connection_path() / "schema" / "descriptions.yaml"
```

Tools affected:
- `load_schema_descriptions()` / `save_schema_descriptions()`
- `_domain_status()` / `_domain_generate()` / `_domain_approve()`
- `_onboarding_*()` functions
- `_get_data()` / query generation

No functional change for users - just internal path reorganization.

### Shell Mode

**Before:**
- Working directory: `vault/`
- Schema file: `../providers/{id}/schema_descriptions.yaml` (not accessible!)
- Domain file: `instructions/domain.md` (template only, not actual domain model!)

**After:**
- Working directory: `connections/{name}/`
- Schema file: `schema/descriptions.yaml` (accessible via `cat schema/descriptions.yaml`)
- Domain file: `domain/model.md` (accessible via `cat domain/model.md`)

PROTOCOL.md commands work as documented:
```bash
cat schema/descriptions.yaml    # Works!
cat domain/model.md             # Works!
cat instructions/sql_rules.md   # Works!
cat examples/*.yaml             # Works!
```

## Implementation Order

1. [ ] Update `config.py` with new settings and paths
2. [ ] Update `onboarding/state.py` - `get_provider_dir()` → `get_connection_path()`
3. [ ] Update `onboarding/schema_store.py` - new path: `schema/descriptions.yaml`
4. [ ] Update `tools/domain.py` - new path: `domain/model.md`
5. [ ] Update `vault/init.py` - initialize inside connection, not separate vault
6. [ ] Update `tools/shell.py` - working directory = connection path
7. [ ] Update PROTOCOL.md with correct paths
8. [ ] Add migration logic (detect `.version` + migrate old structure)
9. [ ] Update CLI commands with connection argument
10. [ ] Add `list`, `use`, `remove` commands
11. [ ] Add `all` keyword support
12. [ ] Update server mode to use `CONNECTION_PATH`
13. [ ] Update documentation
14. [ ] Test both modes after migration
