"""dbmeta CLI - Standalone CLI for db-meta-v2 MCP server.

Commands:
    dbmeta init [NAME] [GIT_URL]  - Interactive setup wizard (or clone from git)
    dbmeta start                  - Start MCP server (stdio mode)
    dbmeta config                 - Open config in editor
    dbmeta status                 - Show current configuration
    dbmeta list                   - List all connections
    dbmeta use NAME               - Switch active connection
    dbmeta git-init [NAME] [URL]  - Enable git sync for existing connection
    dbmeta sync [NAME]            - Sync changes to git remote
    dbmeta pull [NAME]            - Pull updates from git remote
    dbmeta edit [NAME]            - Open connection directory in editor
    dbmeta rename OLD NEW         - Rename a connection
    dbmeta remove NAME            - Remove a connection

Global options:
    -c, --connection NAME  - Use specific connection (default: from config)
    all                    - Apply command to all connections (where supported)
"""

import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()


def _handle_sigint(signum, frame):
    """Handle Ctrl-C gracefully."""
    console.print("\n[dim]Cancelled.[/dim]")
    sys.exit(130)


# Register signal handler early to catch Ctrl-C before Click processes it
signal.signal(signal.SIGINT, _handle_sigint)

# Config paths
CONFIG_DIR = Path.home() / ".dbmeta"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
CONNECTIONS_DIR = CONFIG_DIR / "connections"

# Legacy paths (for migration)
LEGACY_VAULT_DIR = CONFIG_DIR / "vault"
LEGACY_PROVIDERS_DIR = CONFIG_DIR / "providers"


def get_connection_path(name: str) -> Path:
    """Get path to a connection directory."""
    return CONNECTIONS_DIR / name


def list_connections() -> list[str]:
    """List all connection names."""
    if not CONNECTIONS_DIR.exists():
        return []
    return sorted([d.name for d in CONNECTIONS_DIR.iterdir() if d.is_dir()])


def get_active_connection() -> str:
    """Get the active connection name from config."""
    config = load_config()
    return config.get("active_connection", "default")


def set_active_connection(name: str) -> None:
    """Set the active connection in config."""
    config = load_config()
    config["active_connection"] = name
    save_config(config)


def connection_exists(name: str) -> bool:
    """Check if a connection exists."""
    return get_connection_path(name).exists()


def get_claude_desktop_config_path() -> Path:
    """Get Claude Desktop config path for current OS."""
    system = platform.system()
    if system == "Darwin":  # macOS
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:  # Linux
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def load_config() -> dict:
    """Load config from file."""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict) -> None:
    """Save config to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_dbmeta_binary_path() -> str:
    """Get path to dbmeta binary (or script in dev mode)."""
    # If running as PyInstaller bundle
    if getattr(sys, "frozen", False):
        return sys.executable
    # Running as script - return the command that invoked us
    return "dbmeta"


def load_claude_desktop_config() -> tuple[dict, Path]:
    """Load Claude Desktop config.

    Returns (config_dict, config_path).
    """
    config_path = get_claude_desktop_config_path()

    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f), config_path
        except json.JSONDecodeError:
            console.print(f"[red]Invalid JSON in {config_path}[/red]")
            return {}, config_path

    return {}, config_path


def save_claude_desktop_config(config: dict, config_path: Path) -> None:
    """Save Claude Desktop config."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def extract_database_url_from_claude_config(claude_config: dict) -> str | None:
    """Extract DATABASE_URL from existing Claude Desktop MCP server configs."""
    mcp_servers = claude_config.get("mcpServers", {})

    # Check dbmeta entry first
    if "dbmeta" in mcp_servers:
        env = mcp_servers["dbmeta"].get("env", {})
        if "DATABASE_URL" in env:
            return env["DATABASE_URL"]

    # Check legacy db-meta-v2 entry
    if "db-meta-v2" in mcp_servers:
        env = mcp_servers["db-meta-v2"].get("env", {})
        if "DATABASE_URL" in env:
            return env["DATABASE_URL"]

    return None


def is_claude_desktop_installed() -> bool:
    """Check if Claude Desktop is installed."""
    system = platform.system()

    if system == "Darwin":  # macOS
        app_path = Path("/Applications/Claude.app")
        return app_path.exists()
    elif system == "Windows":
        # Check common install locations
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            claude_path = Path(local_app_data) / "Programs" / "Claude" / "Claude.exe"
            if claude_path.exists():
                return True
        program_files = os.environ.get("PROGRAMFILES", "")
        if program_files:
            claude_path = Path(program_files) / "Claude" / "Claude.exe"
            if claude_path.exists():
                return True
        return False
    else:  # Linux
        # Check common locations
        for path in [
            "/usr/bin/claude",
            "/usr/local/bin/claude",
            Path.home() / ".local" / "bin" / "claude",
        ]:
            if Path(path).exists():
                return True
        return False


def launch_claude_desktop() -> None:
    """Launch Claude Desktop application."""
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["open", "-a", "Claude"], check=True)
            console.print("[green]✓ Claude Desktop launched[/green]")
        elif system == "Windows":
            # Try common install locations
            subprocess.run(["start", "claude"], shell=True, check=True)
            console.print("[green]✓ Claude Desktop launched[/green]")
        else:
            console.print("[dim]Please launch Claude Desktop manually.[/dim]")
    except (subprocess.CalledProcessError, FileNotFoundError):
        console.print("[dim]Could not auto-launch. Please start Claude Desktop manually.[/dim]")


# =============================================================================
# Git utilities
# =============================================================================

GIT_INSTALL_URL = "https://git-scm.com/downloads"

# Default .gitignore content for connection directories
GITIGNORE_CONTENT = """# dbmeta gitignore
# Local state (not shared)
state.yaml

# Temp/backup files
*.tmp
*.bak
*.swp
*~

# Environment files (may contain credentials)
.env*
"""


def is_git_installed() -> bool:
    """Check if git is installed and available."""
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def is_git_repo(path: Path) -> bool:
    """Check if a directory is a git repository."""
    return (path / ".git").is_dir()


def git_init(path: Path, remote_url: str | None = None) -> bool:
    """Initialize a git repository in the given path.

    Args:
        path: Directory to initialize
        remote_url: Optional remote URL to add as origin

    Returns:
        True if successful
    """
    try:
        # Initialize repo
        subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)

        # Create .gitignore
        gitignore_path = path / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(GITIGNORE_CONTENT)

        # Initial commit
        subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial dbmeta connection setup"],
            cwd=path,
            capture_output=True,
            check=True,
        )

        # Add remote if provided
        if remote_url:
            subprocess.run(
                ["git", "remote", "add", "origin", remote_url],
                cwd=path,
                capture_output=True,
                check=True,
            )

        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Git error: {e.stderr.decode() if e.stderr else str(e)}[/red]")
        return False


def git_clone(url: str, dest: Path) -> bool:
    """Clone a git repository.

    Args:
        url: Git URL to clone
        dest: Destination path

    Returns:
        True if successful
    """
    try:
        subprocess.run(
            ["git", "clone", url, str(dest)],
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        console.print(f"[red]Git clone failed: {error_msg}[/red]")
        return False


def git_sync(path: Path) -> bool:
    """Sync local changes to remote (add, commit, pull --rebase, push).

    Args:
        path: Git repository path

    Returns:
        True if successful
    """
    from datetime import datetime

    try:
        # Check for changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            check=True,
        )

        has_changes = bool(result.stdout.strip())

        if has_changes:
            # Add all changes
            subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)

            # Commit with timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            subprocess.run(
                ["git", "commit", "-m", f"dbmeta sync {timestamp}"],
                cwd=path,
                capture_output=True,
                check=True,
            )
            console.print("[green]✓ Changes committed[/green]")
        else:
            console.print("[dim]No local changes to commit.[/dim]")

        # Check if remote exists
        result = subprocess.run(
            ["git", "remote"],
            cwd=path,
            capture_output=True,
            check=True,
        )

        if not result.stdout.strip():
            console.print(
                "[yellow]No remote configured. Use 'git remote add origin <url>'[/yellow]"
            )
            return True

        # Pull with rebase to get remote changes
        console.print("[dim]Pulling remote changes...[/dim]")
        result = subprocess.run(
            ["git", "pull", "--rebase", "origin", "HEAD"],
            cwd=path,
            capture_output=True,
        )

        if result.returncode != 0:
            error_msg = result.stderr.decode() if result.stderr else ""
            if "conflict" in error_msg.lower():
                console.print("[yellow]Merge conflict detected.[/yellow]")
                console.print("[dim]Resolve conflicts manually, then run:[/dim]")
                console.print(f"  cd {path}")
                console.print("  git add .")
                console.print("  git rebase --continue")
                console.print("  dbmeta sync")
                return False
            elif "couldn't find remote ref" in error_msg.lower():
                # Remote branch doesn't exist yet, that's ok
                pass
            else:
                console.print(f"[yellow]Pull warning: {error_msg}[/yellow]")

        # Push changes
        console.print("[dim]Pushing to remote...[/dim]")
        result = subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            cwd=path,
            capture_output=True,
        )

        if result.returncode != 0:
            error_msg = result.stderr.decode() if result.stderr else ""
            if "rejected" in error_msg.lower():
                console.print("[yellow]Push rejected. Try 'dbmeta pull' first.[/yellow]")
                return False
            else:
                console.print(f"[red]Push failed: {error_msg}[/red]")
                return False

        console.print("[green]✓ Synced with remote[/green]")
        return True

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        console.print(f"[red]Git error: {error_msg}[/red]")
        return False


def git_pull(path: Path) -> bool:
    """Pull changes from remote.

    Args:
        path: Git repository path

    Returns:
        True if successful
    """
    try:
        # Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            check=True,
        )

        if result.stdout.strip():
            console.print("[yellow]You have uncommitted changes.[/yellow]")
            console.print("[dim]Stashing changes before pull...[/dim]")
            subprocess.run(["git", "stash"], cwd=path, capture_output=True, check=True)
            stashed = True
        else:
            stashed = False

        # Pull
        result = subprocess.run(
            ["git", "pull", "--rebase", "origin", "HEAD"],
            cwd=path,
            capture_output=True,
        )

        if result.returncode != 0:
            error_msg = result.stderr.decode() if result.stderr else ""
            if "conflict" in error_msg.lower():
                console.print("[yellow]Merge conflict detected.[/yellow]")
                console.print(f"[dim]Resolve conflicts in {path}[/dim]")
                return False
            elif "couldn't find remote ref" in error_msg.lower():
                console.print("[dim]Remote branch not found (may not exist yet).[/dim]")
            else:
                console.print(f"[yellow]Pull warning: {error_msg}[/yellow]")

        # Pop stash if we stashed
        if stashed:
            result = subprocess.run(
                ["git", "stash", "pop"],
                cwd=path,
                capture_output=True,
            )
            if result.returncode != 0:
                console.print("[yellow]Conflict applying stashed changes.[/yellow]")
                console.print("[dim]Resolve conflicts manually.[/dim]")
                return False
            console.print("[dim]Restored local changes.[/dim]")

        console.print("[green]✓ Pulled from remote[/green]")
        return True

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        console.print(f"[red]Git error: {error_msg}[/red]")
        return False


def is_git_url(s: str) -> bool:
    """Check if a string looks like a git URL."""
    if not s:
        return False
    # Common git URL patterns
    return (
        s.startswith("git@")
        or s.startswith("https://github.com/")
        or s.startswith("https://gitlab.com/")
        or s.startswith("https://bitbucket.org/")
        or s.endswith(".git")
        or "github.com" in s
        or "gitlab.com" in s
    )


@click.group()
@click.version_option(version="0.2.7")
def main():
    """dbmeta - Database metadata MCP server for Claude Desktop."""
    pass


@main.command()
@click.argument("name", default="default", required=False)
@click.argument("source", default=None, required=False)
def init(name: str, source: str | None):
    """Interactive setup wizard - configure database and Claude Desktop.

    NAME is the connection name (default: "default").

    SOURCE is an optional git URL to clone an existing connection config.
    This enables "brownfield" setup where you join an existing team's
    semantic layer instead of starting from scratch.

    Examples:
        dbmeta init                           # New connection "default"
        dbmeta init mydb                      # New connection "mydb"
        dbmeta init mydb git@github.com:org/dbmeta-mydb.git  # Clone from git
    """
    # Check if Claude Desktop is installed
    if not is_claude_desktop_installed():
        console.print(
            Panel.fit(
                "[bold red]Claude Desktop Not Found[/bold red]\n\n"
                "dbmeta requires Claude Desktop to be installed.\n\n"
                "Download from: [cyan]https://claude.ai/download[/cyan]",
                border_style="red",
            )
        )
        return

    # Determine if this is brownfield (git clone) or greenfield (new setup)
    is_brownfield = source and is_git_url(source)

    if is_brownfield:
        _init_brownfield(name, source)
    else:
        _init_greenfield(name)


def _init_brownfield(name: str, git_url: str):
    """Initialize connection by cloning from git (brownfield setup)."""
    # Check git is installed
    if not is_git_installed():
        console.print(
            Panel.fit(
                "[bold red]Git Not Found[/bold red]\n\n"
                "Git is required for cloning connection configs.\n\n"
                f"Install from: [cyan]{GIT_INSTALL_URL}[/cyan]",
                border_style="red",
            )
        )
        return

    console.print(
        Panel.fit(
            f"[bold blue]dbmeta Setup (Brownfield)[/bold blue]\n\n"
            f"Clone connection: [cyan]{name}[/cyan]\n"
            f"From: [dim]{git_url}[/dim]",
            border_style="blue",
        )
    )

    connection_path = get_connection_path(name)

    # Check if connection already exists
    if connection_path.exists():
        console.print(f"\n[red]Connection '{name}' already exists.[/red]")
        console.print("[dim]Use 'dbmeta remove {name}' first, or choose a different name.[/dim]")
        return

    # Clone the repository
    console.print("\n[dim]Cloning repository...[/dim]")
    if not git_clone(git_url, connection_path):
        return

    console.print(f"[green]✓ Cloned to {connection_path}[/green]")

    # Show what was cloned
    console.print("\n[bold]Cloned files:[/bold]")
    for item in sorted(connection_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            console.print(f"  [cyan]{item.name}/[/cyan]")
        else:
            console.print(f"  {item.name}")

    # Now prompt for DATABASE_URL (credentials are not in git)
    _prompt_and_save_database_url(name)

    # Recover onboarding state from cloned files
    _recover_onboarding_state(name, connection_path)

    # Configure Claude Desktop
    _configure_claude_desktop(name)

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Setup Complete![/bold green]\n\n"
            "Connection cloned from git.\n"
            "Claude Desktop needs to restart to load the new config.\n\n"
            "[dim]Use 'dbmeta pull' to get updates from the team.[/dim]\n"
            "[dim]Use 'dbmeta sync' to share your changes.[/dim]",
            border_style="green",
        )
    )

    # Offer to launch Claude Desktop
    console.print()
    if Confirm.ask("Launch Claude Desktop now?", default=True):
        launch_claude_desktop()
    else:
        console.print("[dim]Please restart Claude Desktop manually.[/dim]")


def _init_greenfield(name: str):
    """Initialize a new connection from scratch (greenfield setup)."""
    console.print(
        Panel.fit(
            f"[bold blue]dbmeta Setup[/bold blue]\n\nConfigure connection: [cyan]{name}[/cyan]",
            border_style="blue",
        )
    )

    # Load existing Claude Desktop config
    claude_config, claude_config_path = load_claude_desktop_config()
    mcp_servers = claude_config.get("mcpServers", {})

    # Check for existing dbmeta or db-meta-v2 entry
    existing_url = extract_database_url_from_claude_config(claude_config)
    has_dbmeta = "dbmeta" in mcp_servers
    has_legacy = "db-meta-v2" in mcp_servers

    # Also check ~/.dbmeta/config.yaml for existing URL
    if not existing_url:
        dbmeta_config = load_config()
        existing_url = dbmeta_config.get("database_url")

    # Check if connection already exists
    connection_path = get_connection_path(name)
    if connection_path.exists():
        console.print(f"\n[yellow]Connection '{name}' already exists.[/yellow]")
        if not Confirm.ask("Update configuration?", default=True):
            console.print("[dim]Setup cancelled.[/dim]")
            return
    elif has_dbmeta or has_legacy:
        console.print("\n[yellow]Existing configuration found:[/yellow]")
        if has_dbmeta:
            console.print("  Entry: [cyan]dbmeta[/cyan]")
        if has_legacy:
            console.print("  Entry: [cyan]db-meta-v2[/cyan] (legacy)")
        if existing_url:
            # Mask password in URL for display
            display_url = existing_url
            if "@" in display_url:
                # Simple password masking
                parts = display_url.split("@")
                prefix = parts[0]
                if ":" in prefix:
                    scheme_user = prefix.rsplit(":", 1)[0]
                    display_url = f"{scheme_user}:****@{parts[1]}"
            console.print(f"  Database: [cyan]{display_url}[/cyan]")
        console.print()
    else:
        console.print(f"\n[dim]Claude Desktop config: {claude_config_path}[/dim]")
        if not claude_config_path.exists():
            console.print("[dim]Will create new config file.[/dim]")

    # Prompt for DATABASE_URL
    database_url = _prompt_and_save_database_url(name, existing_url)
    if not database_url:
        return

    # Create connection directory
    connection_path.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓ Connection directory created: {connection_path}[/green]")

    # Configure Claude Desktop
    _configure_claude_desktop(name)

    # Run migration if legacy data exists
    if LEGACY_VAULT_DIR.exists() or LEGACY_PROVIDERS_DIR.exists():
        console.print("\n[yellow]Legacy data detected. Running migration...[/yellow]")
        try:
            from db_meta_v2.vault.migrate import migrate_to_connection_structure

            stats = migrate_to_connection_structure(name)
            if not stats.get("skipped"):
                console.print("[green]✓ Legacy data migrated[/green]")
        except Exception as e:
            console.print(f"[yellow]Migration warning: {e}[/yellow]")

    # Offer git sync setup (only for greenfield, if git is available)
    _offer_git_setup(name, connection_path)

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Setup Complete![/bold green]\n\n"
            "Claude Desktop needs to restart to load the new config.",
            border_style="green",
        )
    )

    # Offer to launch Claude Desktop
    console.print()
    if Confirm.ask("Launch Claude Desktop now?", default=True):
        launch_claude_desktop()
    else:
        console.print("[dim]Please restart Claude Desktop manually.[/dim]")


def _get_connection_env_path(name: str) -> Path:
    """Get path to connection's .env file."""
    return get_connection_path(name) / ".env"


def _load_connection_env(name: str) -> dict:
    """Load environment variables from connection's .env file."""
    env_file = _get_connection_env_path(name)
    if not env_file.exists():
        return {}

    env_vars = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                # Remove quotes if present
                value = value.strip().strip("\"'")
                env_vars[key] = value
    return env_vars


def _save_connection_env(name: str, env_vars: dict):
    """Save environment variables to connection's .env file."""
    conn_path = get_connection_path(name)
    conn_path.mkdir(parents=True, exist_ok=True)

    env_file = _get_connection_env_path(name)
    with open(env_file, "w") as f:
        f.write("# dbmeta connection credentials\n")
        f.write("# This file is gitignored - do not commit\n\n")
        for key, value in env_vars.items():
            f.write(f'{key}="{value}"\n')


def _prompt_and_save_database_url(name: str, existing_url: str | None = None) -> str | None:
    """Prompt for database URL and save to connection's .env file."""
    # Try to load existing URL from connection's .env
    if not existing_url:
        conn_env = _load_connection_env(name)
        existing_url = conn_env.get("DATABASE_URL")

    console.print("\n[bold]Database Connection[/bold]")
    console.print("[dim]Examples:[/dim]")
    console.print("  trino://user:pass@host:8443/catalog/schema?http_scheme=https")
    console.print("  clickhouse+native://user:pass@host:9000/database")
    console.print("  postgresql://user:pass@host:5432/database")
    console.print()

    database_url = Prompt.ask(
        "Database URL",
        default=existing_url or "",
    )

    if not database_url:
        console.print("[red]Database URL is required.[/red]")
        return None

    # Save DATABASE_URL to connection's .env file (gitignored)
    _save_connection_env(name, {"DATABASE_URL": database_url})
    console.print(f"\n[green]✓ Credentials saved to {_get_connection_env_path(name)}[/green]")

    # Save non-sensitive config to global config.yaml
    config = load_config()
    config.update(
        {
            "active_connection": name,
            "tool_mode": "shell",
            "log_level": "INFO",
        }
    )
    # Remove database_url from global config if present (migrate to per-connection)
    config.pop("database_url", None)

    save_config(config)
    console.print(f"[green]✓ Config saved to {CONFIG_FILE}[/green]")

    return database_url


def _configure_claude_desktop(name: str):
    """Configure Claude Desktop for dbmeta."""
    claude_config, claude_config_path = load_claude_desktop_config()
    mcp_servers = claude_config.get("mcpServers", {})
    has_legacy = "db-meta-v2" in mcp_servers

    # Update Claude Desktop config
    if "mcpServers" not in claude_config:
        claude_config["mcpServers"] = {}

    # Get binary path
    binary_path = get_dbmeta_binary_path()

    # Add/update dbmeta entry
    claude_config["mcpServers"]["dbmeta"] = {
        "command": binary_path,
        "args": ["start"],
    }

    # Remove legacy entry if exists
    if has_legacy:
        del claude_config["mcpServers"]["db-meta-v2"]
        console.print("[dim]Removed legacy 'db-meta-v2' entry.[/dim]")

    # Save Claude Desktop config
    save_claude_desktop_config(claude_config, claude_config_path)
    console.print(f"[green]✓ Claude Desktop configured at {claude_config_path}[/green]")

    # Show other MCP servers (kept intact)
    other_servers = [k for k in claude_config["mcpServers"].keys() if k != "dbmeta"]
    if other_servers:
        console.print(f"[dim]Other MCP servers (unchanged): {', '.join(other_servers)}[/dim]")


def _recover_onboarding_state(name: str, connection_path: Path):
    """Recover onboarding state from cloned files.

    When cloning from git, state.yaml is not included (gitignored).
    This reconstructs the state based on existing schema/domain files.
    """
    # Set environment so state module uses correct path
    os.environ["CONNECTION_NAME"] = name
    os.environ["CONNECTIONS_DIR"] = str(CONNECTIONS_DIR)

    # Check what files exist
    schema_file = connection_path / "schema" / "descriptions.yaml"
    domain_file = connection_path / "domain" / "model.md"

    has_schema = schema_file.exists()
    has_domain = domain_file.exists()

    if not has_schema and not has_domain:
        console.print("[dim]No existing schema/domain files found.[/dim]")
        return

    # Import here to avoid circular imports and ensure env is set
    from db_meta_v2.onboarding.state import load_state

    # load_state will auto-recover and save if files exist but state doesn't
    state = load_state()

    if state:
        console.print(f"[green]✓ Onboarding state recovered: {state.phase.value}[/green]")
        if has_schema:
            console.print(f"  [dim]Schema: {state.tables_total} tables[/dim]")
        if has_domain:
            console.print("  [dim]Domain model: ready[/dim]")


def _offer_git_setup(name: str, connection_path: Path):
    """Offer to set up git sync for the connection."""
    # Skip if already a git repo (e.g., from brownfield)
    if is_git_repo(connection_path):
        return

    # Check if git is installed
    if not is_git_installed():
        console.print("\n[dim]Tip: Install git to enable team sync features.[/dim]")
        console.print(f"[dim]     {GIT_INSTALL_URL}[/dim]")
        return

    console.print("\n[bold]Git Sync (Optional)[/bold]")
    console.print("[dim]Enable git to share your semantic layer with your team.[/dim]")

    if not Confirm.ask("Enable git sync for this connection?", default=False):
        return

    # Ask for remote URL (optional)
    console.print(
        "\n[dim]Enter a git remote URL to sync with (or leave empty to add later).[/dim]"
    )
    console.print("[dim]Example: git@github.com:yourorg/dbmeta-mydb.git[/dim]")
    remote_url = Prompt.ask("Git remote URL", default="")

    # Initialize git
    if git_init(connection_path, remote_url if remote_url else None):
        console.print("[green]✓ Git repository initialized[/green]")
        if remote_url:
            console.print(f"[dim]Remote 'origin' set to {remote_url}[/dim]")
            console.print("[dim]Use 'dbmeta sync' to push changes to the team.[/dim]")
        else:
            console.print("[dim]Add a remote later with: git remote add origin <url>[/dim]")
            console.print("[dim]Then use 'dbmeta sync' to push changes.[/dim]")


@main.command()
@click.option("-c", "--connection", default=None, help="Connection name (default: active)")
def start(connection: str | None):
    """Start the MCP server (stdio mode for Claude Desktop)."""
    if not CONFIG_FILE.exists():
        console.print("[red]No config found. Run 'dbmeta init' first.[/red]")
        sys.exit(1)

    config = load_config()

    # Determine connection name
    conn_name = connection or config.get("active_connection", "default")
    connection_path = get_connection_path(conn_name)

    # Load DATABASE_URL from connection's .env file
    conn_env = _load_connection_env(conn_name)
    database_url = conn_env.get("DATABASE_URL", "")

    # Fallback to global config for backward compatibility
    if not database_url:
        database_url = config.get("database_url", "")

    # Set environment variables
    os.environ["DATABASE_URL"] = database_url
    os.environ["CONNECTION_NAME"] = conn_name
    os.environ["CONNECTION_PATH"] = str(connection_path)
    os.environ["TOOL_MODE"] = config.get("tool_mode", "shell")
    os.environ["LOG_LEVEL"] = config.get("log_level", "INFO")
    os.environ["MCP_TRANSPORT"] = "stdio"  # Always stdio for CLI

    # Legacy env vars for backward compatibility
    os.environ["PROVIDER_ID"] = conn_name
    os.environ["CONNECTIONS_DIR"] = str(CONNECTIONS_DIR)

    # Ensure connection directory exists
    connection_path.mkdir(parents=True, exist_ok=True)

    # Patch fakeredis path for PyInstaller bundles
    if getattr(sys, "frozen", False):
        import fakeredis.model._command_info as cmd_info

        bundle_dir = getattr(sys, "_MEIPASS", "")

        def patched_load():
            import json

            if cmd_info._COMMAND_INFO is None:
                json_path = os.path.join(bundle_dir, "fakeredis", "commands.json")
                with open(json_path, encoding="utf8") as f:
                    cmd_info._COMMAND_INFO = cmd_info._encode_obj(json.load(f))

        cmd_info._load_command_info = patched_load

    # Import and run the server
    from db_meta_v2.server import main as server_main

    server_main()


@main.command()
def config():
    """Open config file in editor."""
    if not CONFIG_FILE.exists():
        console.print("[yellow]No config found. Run 'dbmeta init' first.[/yellow]")
        if Confirm.ask("Run setup now?", default=True):
            ctx = click.get_current_context()
            ctx.invoke(init)
            return
        return

    editor = os.environ.get("EDITOR", "vim")
    console.print(f"[dim]Opening {CONFIG_FILE} in {editor}...[/dim]")

    try:
        subprocess.run([editor, str(CONFIG_FILE)], check=True)
        console.print("[green]✓ Config saved.[/green]")
        console.print("[dim]Restart Claude Desktop to apply changes.[/dim]")
    except FileNotFoundError:
        console.print(f"[red]Editor '{editor}' not found.[/red]")
        console.print("[dim]Set EDITOR environment variable or edit manually:[/dim]")
        console.print(f"  {CONFIG_FILE}")
    except subprocess.CalledProcessError:
        console.print("[yellow]Editor exited with error.[/yellow]")


@main.command("console")
@click.option("--port", "-p", default=8384, help="Port for console UI")
@click.option("--no-browser", is_flag=True, help="Don't open browser automatically")
def console_cmd(port: int, no_browser: bool):
    """Start local trace console (view MCP server activity).

    Run this in a separate terminal, then use Claude Desktop normally.
    The MCP server will send traces here for visualization.

    Example:
        Terminal 1: dbmeta console
        Terminal 2: Use Claude Desktop (which runs dbmeta start)
    """
    from db_meta_v2.console import start_console

    console.print(
        Panel.fit(
            f"[bold blue]dbmeta console[/bold blue]\n\n"
            f"Trace viewer at [cyan]http://localhost:{port}[/cyan]\n\n"
            f"[dim]Waiting for traces from MCP server...[/dim]\n"
            f"Press Ctrl+C to stop.",
            border_style="blue",
        )
    )

    start_console(port=port, open_browser=not no_browser, blocking=True)


@main.command()
@click.option("-c", "--connection", default=None, help="Show status for specific connection")
def status(connection: str | None):
    """Show current configuration status."""
    console.print(
        Panel.fit(
            "[bold blue]dbmeta Status[/bold blue]",
            border_style="blue",
        )
    )

    # Config status
    console.print("\n[bold]Configuration[/bold]")
    if CONFIG_FILE.exists():
        config = load_config()
        console.print(f"  Config file: [green]{CONFIG_FILE}[/green]")
        console.print(f"  Tool mode:   {config.get('tool_mode', 'N/A')}")
    else:
        console.print(f"  [yellow]No config found at {CONFIG_FILE}[/yellow]")
        console.print("  [dim]Run 'dbmeta init' to configure.[/dim]")

    # Connections status
    console.print("\n[bold]Connections[/bold]")
    connections = list_connections()
    active = get_active_connection()

    if connections:
        for conn in connections:
            conn_path = get_connection_path(conn)
            is_active = conn == active
            marker = "[green]●[/green]" if is_active else "[dim]○[/dim]"
            active_label = " [green](active)[/green]" if is_active else ""

            # Check for key files
            has_schema = (conn_path / "schema" / "descriptions.yaml").exists()
            has_domain = (conn_path / "domain" / "model.md").exists()
            has_env = (conn_path / ".env").exists()

            status_parts = []
            if has_schema:
                status_parts.append("schema")
            if has_domain:
                status_parts.append("domain")
            if has_env:
                status_parts.append("credentials")

            status_str = f"[dim]({', '.join(status_parts)})[/dim]" if status_parts else ""
            console.print(f"  {marker} [cyan]{conn}[/cyan]{active_label} {status_str}")

            # Show masked database URL for active connection
            if is_active:
                conn_env = _load_connection_env(conn)
                db_url = conn_env.get("DATABASE_URL", "")
                if db_url:
                    # Mask password
                    if "@" in db_url and ":" in db_url.split("@")[0]:
                        parts = db_url.split("@")
                        prefix = parts[0]
                        scheme_user = prefix.rsplit(":", 1)[0]
                        db_url = f"{scheme_user}:****@{parts[1]}"
                    truncated = f"{db_url[:50]}..." if len(db_url) > 50 else db_url
                    console.print(f"      [dim]Database: {truncated}[/dim]")
                elif not has_env:
                    console.print(
                        "      [yellow]No .env file - run 'dbmeta init' to configure[/yellow]"
                    )
    else:
        console.print("  [dim]No connections configured.[/dim]")
        console.print("  [dim]Run 'dbmeta init' to create one.[/dim]")

    # Claude Desktop status
    console.print("\n[bold]Claude Desktop[/bold]")
    claude_config, claude_config_path = load_claude_desktop_config()
    if claude_config:
        mcp_servers = claude_config.get("mcpServers", {})
        if "dbmeta" in mcp_servers:
            console.print("  [green]✓ dbmeta configured[/green]")
            cmd = mcp_servers["dbmeta"].get("command", "N/A")
            console.print(f"  Command: {cmd}")
        elif "db-meta-v2" in mcp_servers:
            console.print("  [yellow]⚠ Legacy 'db-meta-v2' entry found[/yellow]")
            console.print("  [dim]Run 'dbmeta init' to upgrade.[/dim]")
        else:
            console.print("  [yellow]dbmeta not configured[/yellow]")
            console.print("  [dim]Run 'dbmeta init' to configure.[/dim]")

        # Show other servers
        other_servers = [k for k in mcp_servers.keys() if k not in ("dbmeta", "db-meta-v2")]
        if other_servers:
            console.print(f"  Other servers: {', '.join(other_servers)}")
    else:
        console.print(f"  [dim]No config at {claude_config_path}[/dim]")

    # Legacy structure warning
    if LEGACY_VAULT_DIR.exists() or LEGACY_PROVIDERS_DIR.exists():
        console.print("\n[yellow]⚠ Legacy data structure detected[/yellow]")
        console.print("  [dim]Run 'dbmeta init' to migrate to new connection structure.[/dim]")


def _get_git_remote_url(path: Path) -> str | None:
    """Get the git remote origin URL for a repository."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path,
            capture_output=True,
            check=True,
        )
        return result.stdout.decode().strip()
    except subprocess.CalledProcessError:
        return None


def _get_git_status_indicator(path: Path) -> str:
    """Get a short git status indicator for a connection."""
    if not is_git_repo(path):
        return "[dim]-[/dim]"

    remote_url = _get_git_remote_url(path)

    # Check for uncommitted changes
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            check=True,
        )
        has_changes = bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        has_changes = False

    if remote_url:
        if has_changes:
            return "[yellow]●[/yellow]"  # Has remote, uncommitted changes
        return "[green]✓[/green]"  # Has remote, clean
    else:
        if has_changes:
            return "[yellow]○[/yellow]"  # Local only, uncommitted changes
        return "[dim]○[/dim]"  # Local only, clean


@main.command("list")
def list_cmd():
    """List all configured connections."""
    connections = list_connections()
    active = get_active_connection()

    if not connections:
        console.print("[dim]No connections configured.[/dim]")
        console.print("[dim]Run 'dbmeta init <name>' to create one.[/dim]")
        return

    table = Table(title="Connections", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Active", justify="center")
    table.add_column("Schema", justify="center")
    table.add_column("Domain", justify="center")
    table.add_column("Git", justify="center")
    table.add_column("Remote")

    for conn in connections:
        conn_path = get_connection_path(conn)
        is_active = conn == active

        has_schema = (conn_path / "schema" / "descriptions.yaml").exists()
        has_domain = (conn_path / "domain" / "model.md").exists()

        git_status = _get_git_status_indicator(conn_path)
        git_remote = ""
        if is_git_repo(conn_path):
            remote_url = _get_git_remote_url(conn_path)
            if remote_url:
                # Shorten the URL for display
                if remote_url.startswith("git@github.com:"):
                    git_remote = remote_url.replace("git@github.com:", "gh:")
                elif remote_url.startswith("https://github.com/"):
                    git_remote = remote_url.replace("https://github.com/", "gh:")
                else:
                    git_remote = remote_url
                # Trim .git suffix
                if git_remote.endswith(".git"):
                    git_remote = git_remote[:-4]

        table.add_row(
            conn,
            "[green]●[/green]" if is_active else "",
            "[green]✓[/green]" if has_schema else "[dim]-[/dim]",
            "[green]✓[/green]" if has_domain else "[dim]-[/dim]",
            git_status,
            f"[dim]{git_remote}[/dim]" if git_remote else "",
        )

    console.print(table)

    # Legend
    console.print("\n[dim]Git: ✓ synced, ● uncommitted changes, ○ local only, - not enabled[/dim]")


@main.command()
@click.argument("name")
def use(name: str):
    """Switch to a different connection.

    NAME is the connection name to switch to.
    """
    if not connection_exists(name):
        console.print(f"[red]Connection '{name}' not found.[/red]")
        console.print("[dim]Run 'dbmeta list' to see available connections.[/dim]")
        sys.exit(1)

    set_active_connection(name)
    console.print(f"[green]✓ Switched to connection '{name}'[/green]")
    console.print("[dim]Restart Claude Desktop to apply changes.[/dim]")


@main.command()
@click.argument("name", default=None, required=False)
def sync(name: str | None):
    """Sync connection changes with git remote.

    NAME is the connection name (default: active connection).

    This command:
    1. Commits any local changes (auto-generated commit message)
    2. Pulls remote changes (with rebase)
    3. Pushes to remote

    Use this to share your semantic layer updates with your team.
    """
    # Default to active connection
    if not name:
        name = get_active_connection()

    if not connection_exists(name):
        console.print(f"[red]Connection '{name}' not found.[/red]")
        sys.exit(1)

    conn_path = get_connection_path(name)

    # Check if it's a git repo
    if not is_git_repo(conn_path):
        console.print(f"[yellow]Connection '{name}' is not a git repository.[/yellow]")
        console.print("[dim]Run 'dbmeta init' and enable git sync, or initialize manually:[/dim]")
        console.print(f"  cd {conn_path}")
        console.print("  git init")
        console.print("  git remote add origin <your-repo-url>")
        return

    console.print(f"[bold]Syncing connection: {name}[/bold]")
    git_sync(conn_path)


@main.command()
@click.argument("name", default=None, required=False)
def pull(name: str | None):
    """Pull connection updates from git remote.

    NAME is the connection name (default: active connection).

    This pulls the latest changes from the remote repository,
    allowing you to get updates from your team.
    """
    # Default to active connection
    if not name:
        name = get_active_connection()

    if not connection_exists(name):
        console.print(f"[red]Connection '{name}' not found.[/red]")
        sys.exit(1)

    conn_path = get_connection_path(name)

    # Check if it's a git repo
    if not is_git_repo(conn_path):
        console.print(f"[yellow]Connection '{name}' is not a git repository.[/yellow]")
        console.print("[dim]This connection was not set up with git sync.[/dim]")
        return

    console.print(f"[bold]Pulling updates for: {name}[/bold]")
    git_pull(conn_path)


@main.command("git-init")
@click.argument("name", default=None, required=False)
@click.argument("remote_url", default=None, required=False)
def git_init_cmd(name: str | None, remote_url: str | None):
    """Enable git sync for an existing connection.

    NAME is the connection name (default: active connection).
    REMOTE_URL is the optional git remote URL.

    This initializes a git repository in the connection directory
    and optionally sets up a remote for syncing.

    Examples:
        dbmeta git-init
        dbmeta git-init mydb
        dbmeta git-init mydb git@github.com:org/dbmeta-mydb.git
    """
    # Check git is installed
    if not is_git_installed():
        console.print(
            Panel.fit(
                "[bold red]Git Not Found[/bold red]\n\n"
                f"Install from: [cyan]{GIT_INSTALL_URL}[/cyan]",
                border_style="red",
            )
        )
        return

    # Default to active connection
    if not name:
        name = get_active_connection()

    if not connection_exists(name):
        console.print(f"[red]Connection '{name}' not found.[/red]")
        sys.exit(1)

    conn_path = get_connection_path(name)

    # Check if already a git repo
    if is_git_repo(conn_path):
        console.print(f"[yellow]Connection '{name}' is already a git repository.[/yellow]")
        # Show remote info if any
        try:
            result = subprocess.run(
                ["git", "remote", "-v"],
                cwd=conn_path,
                capture_output=True,
                check=True,
            )
            if result.stdout.strip():
                console.print("[dim]Remotes:[/dim]")
                console.print(result.stdout.decode())
        except subprocess.CalledProcessError:
            pass
        return

    # Prompt for remote if not provided
    if not remote_url:
        console.print(f"\n[bold]Enable git sync for: {name}[/bold]")
        console.print(
            "[dim]Enter a git remote URL to sync with (or leave empty to add later).[/dim]"
        )
        console.print("[dim]Example: git@github.com:yourorg/dbmeta-mydb.git[/dim]")
        remote_url = Prompt.ask("Git remote URL", default="")

    # Initialize git
    if git_init(conn_path, remote_url if remote_url else None):
        console.print(f"[green]✓ Git initialized for '{name}'[/green]")
        if remote_url:
            console.print(f"[dim]Remote 'origin' set to {remote_url}[/dim]")
        console.print("[dim]Use 'dbmeta sync' to push changes to the team.[/dim]")


@main.command()
@click.argument("name", default=None, required=False)
def edit(name: str | None):
    """Open connection directory in editor.

    NAME is the connection name to edit (default: active connection).

    Opens the connection directory in your editor (vim by default).
    Set EDITOR environment variable to change the editor.

    The connection directory contains:
    - schema/descriptions.yaml - Column descriptions
    - domain/model.md - Domain model documentation
    - examples/ - Query examples
    - instructions/ - Custom instructions
    - learnings/ - Failure patterns
    """
    # Default to active connection
    if not name:
        name = get_active_connection()

    if not connection_exists(name):
        console.print(f"[red]Connection '{name}' not found.[/red]")
        console.print("[dim]Run 'dbmeta list' to see available connections.[/dim]")
        sys.exit(1)

    conn_path = get_connection_path(name)
    editor = os.environ.get("EDITOR", "vim")

    console.print(f"[dim]Opening {conn_path} in {editor}...[/dim]")

    try:
        subprocess.run([editor, str(conn_path)], check=True)
        console.print("[green]✓ Done.[/green]")
    except FileNotFoundError:
        console.print(f"[red]Editor '{editor}' not found.[/red]")
        console.print("[dim]Set EDITOR environment variable or edit manually:[/dim]")
        console.print(f"  {conn_path}")
    except subprocess.CalledProcessError:
        console.print("[yellow]Editor exited with error.[/yellow]")


@main.command()
@click.argument("old_name")
@click.argument("new_name")
def rename(old_name: str, new_name: str):
    """Rename a connection.

    OLD_NAME is the current connection name.
    NEW_NAME is the new name for the connection.

    This renames the connection directory and updates the active
    connection if needed.
    """
    if not connection_exists(old_name):
        console.print(f"[red]Connection '{old_name}' not found.[/red]")
        console.print("[dim]Run 'dbmeta list' to see available connections.[/dim]")
        sys.exit(1)

    if connection_exists(new_name):
        console.print(f"[red]Connection '{new_name}' already exists.[/red]")
        sys.exit(1)

    # Validate new name (simple alphanumeric + dash/underscore)
    if not re.match(r"^[a-zA-Z0-9_-]+$", new_name):
        console.print("[red]Invalid name. Use only letters, numbers, dashes, underscores.[/red]")
        sys.exit(1)

    old_path = get_connection_path(old_name)
    new_path = get_connection_path(new_name)

    # Rename directory
    old_path.rename(new_path)
    console.print(f"[green]✓ Renamed '{old_name}' to '{new_name}'[/green]")

    # Update active connection if needed
    if get_active_connection() == old_name:
        set_active_connection(new_name)
        console.print(f"[dim]Active connection updated to '{new_name}'.[/dim]")

    console.print("[dim]Restart Claude Desktop to apply changes.[/dim]")


@main.command()
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def remove(name: str, force: bool):
    """Remove a connection.

    NAME is the connection name to remove.
    This deletes all data associated with the connection.
    """
    if not connection_exists(name):
        console.print(f"[red]Connection '{name}' not found.[/red]")
        sys.exit(1)

    conn_path = get_connection_path(name)

    if not force:
        console.print(f"[yellow]Warning: This will delete all data in {conn_path}[/yellow]")
        if not Confirm.ask(f"Remove connection '{name}'?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            return

    shutil.rmtree(conn_path)
    console.print(f"[green]✓ Connection '{name}' removed[/green]")

    # If this was the active connection, suggest switching
    if get_active_connection() == name:
        remaining = list_connections()
        if remaining:
            console.print(f"[yellow]'{name}' was the active connection.[/yellow]")
            console.print(f"[dim]Run 'dbmeta use {remaining[0]}' to switch.[/dim]")


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would be migrated without making changes")
@click.option("--server", is_flag=True, help="Run in server mode (use CONNECTION_PATH env var)")
def migrate(dry_run: bool, server: bool):
    """Migrate from legacy storage format to new connection structure.

    This migrates data from the old structure:
        ~/.dbmeta/vault/
        ~/.dbmeta/providers/{id}/

    To the new self-contained connection structure:
        ~/.dbmeta/connections/{name}/

    For server/container deployments, use --server flag which reads
    CONNECTION_PATH from environment variables.

    Migration is non-destructive - original files are preserved.
    Run 'dbmeta status' to check if migration is needed.

    Examples:
        # Local CLI migration
        dbmeta migrate

        # Server/container migration (uses env vars)
        CONNECTION_PATH=/data/connection dbmeta migrate --server

        # Dry run to see what would happen
        dbmeta migrate --dry-run
    """
    from db_meta_v2.vault import ensure_connection_structure
    from db_meta_v2.vault.migrate import (
        detect_legacy_structure,
        get_storage_version,
        migrate_to_connection_structure,
        write_storage_version,
    )

    # Server mode: use CONNECTION_PATH env var directly
    if server:
        from db_meta_v2.config import get_settings

        settings = get_settings()
        connection_path = settings.get_effective_connection_path()
        conn_name = settings.connection_name

        console.print("[bold]Server mode migration[/bold]")
        console.print(f"  Connection: {conn_name}")
        console.print(f"  Path:       {connection_path}")

        version = get_storage_version(connection_path)
        if version >= 2:
            console.print("\n[green]✓ Already at v2 format.[/green]")
            return

        if dry_run:
            console.print("\n[yellow]Dry run - no changes made.[/yellow]")
            return

        # For server mode, we mainly ensure structure and write version
        console.print("\n[bold]Initializing connection structure...[/bold]")
        ensure_connection_structure()
        write_storage_version(connection_path)
        console.print("[green]✓ Connection structure initialized (v2)[/green]")
        return

    # Local CLI mode: detect and migrate legacy structure
    legacy = detect_legacy_structure()

    if not legacy:
        console.print("[green]✓ No legacy data to migrate.[/green]")
        console.print("[dim]Already using new connection structure.[/dim]")
        return

    console.print("[bold]Legacy data detected:[/bold]")
    if legacy.get("vault_path"):
        console.print(f"  Vault:    {legacy['vault_path']}")
    if legacy.get("provider_path"):
        console.print(f"  Provider: {legacy['provider_path']}")
    console.print(f"  ID:       {legacy.get('provider_id', 'default')}")

    # Check target
    conn_name = legacy.get("provider_id") or "default"
    target_path = CONNECTIONS_DIR / conn_name
    version = get_storage_version(target_path)

    if version >= 2:
        console.print(f"\n[green]✓ Already migrated to: {target_path}[/green]")
        return

    console.print("\n[bold]Migration target:[/bold]")
    console.print(f"  {target_path}")

    if dry_run:
        console.print("\n[yellow]Dry run - no changes made.[/yellow]")
        console.print("[dim]Run without --dry-run to perform migration.[/dim]")
        return

    # Perform migration
    console.print("\n[bold]Migrating...[/bold]")
    try:
        stats = migrate_to_connection_structure(conn_name)

        if stats.get("skipped"):
            console.print(f"[yellow]Skipped: {stats.get('reason')}[/yellow]")
        else:
            console.print("[green]✓ Migration complete![/green]")
            console.print("\n[bold]Migrated:[/bold]")
            if stats.get("schema_descriptions"):
                console.print("  ✓ Schema descriptions")
            if stats.get("domain_model"):
                console.print("  ✓ Domain model")
            if stats.get("onboarding_state"):
                console.print("  ✓ Onboarding state")
            if stats.get("query_examples", 0) > 0:
                console.print(f"  ✓ {stats['query_examples']} query examples")
            if stats.get("failures", 0) > 0:
                console.print(f"  ✓ {stats['failures']} failure records")
            vault_files = stats.get("vault_files", {})
            if vault_files:
                for key, count in vault_files.items():
                    if count > 0:
                        console.print(f"  ✓ {count} {key} files")

            console.print("\n[dim]Original files preserved in legacy locations.[/dim]")
            console.print("[dim]You may delete them after verifying the migration.[/dim]")

    except Exception as e:
        console.print(f"[red]Migration failed: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("command", type=click.Choice(["status", "migrate"]))
def all(command: str):
    """Run a command for all connections.

    Supported commands:
    - status: Show status for all connections
    - migrate: Run migration for all connections (legacy)
    """
    connections = list_connections()

    if not connections:
        console.print("[dim]No connections found.[/dim]")
        return

    if command == "status":
        for conn in connections:
            console.print(f"\n[bold cyan]Connection: {conn}[/bold cyan]")
            conn_path = get_connection_path(conn)

            # Quick status
            has_schema = (conn_path / "schema" / "descriptions.yaml").exists()
            has_domain = (conn_path / "domain" / "model.md").exists()
            has_state = (conn_path / "state.yaml").exists()
            has_version = (conn_path / ".version").exists()

            console.print(f"  Path:    {conn_path}")
            console.print(f"  Schema:  {'[green]✓[/green]' if has_schema else '[dim]-[/dim]'}")
            console.print(f"  Domain:  {'[green]✓[/green]' if has_domain else '[dim]-[/dim]'}")
            console.print(f"  State:   {'[green]✓[/green]' if has_state else '[dim]-[/dim]'}")
            console.print(
                f"  Version: {'[green]v2[/green]' if has_version else '[yellow]v1[/yellow]'}"
            )

    elif command == "migrate":
        from db_meta_v2.vault.migrate import migrate_to_connection_structure

        for conn in connections:
            console.print(f"\n[bold]Migrating: {conn}[/bold]")
            try:
                stats = migrate_to_connection_structure(conn)
                if stats.get("skipped"):
                    console.print(f"  [dim]Skipped: {stats.get('reason')}[/dim]")
                else:
                    console.print("  [green]✓ Migrated[/green]")
            except Exception as e:
                console.print(f"  [red]Error: {e}[/red]")


if __name__ == "__main__":
    main()
