"""dbmeta CLI - Standalone CLI for db-meta-v2 MCP server.

Commands:
    dbmeta init    - Interactive setup wizard (configures database + Claude Desktop)
    dbmeta start   - Start MCP server (stdio mode)
    dbmeta config  - Open config in editor
    dbmeta status  - Show current configuration
"""

import json
import os
import platform
import signal
import subprocess
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

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
VAULT_DIR = CONFIG_DIR / "vault"


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


@click.group()
@click.version_option(version="0.1.14")
def main():
    """dbmeta - Database metadata MCP server for Claude Desktop."""
    pass


@main.command()
def init():
    """Interactive setup wizard - configure database and Claude Desktop."""
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

    console.print(
        Panel.fit(
            "[bold blue]dbmeta Setup[/bold blue]\n\n"
            "Configure database connection for Claude Desktop.",
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

    if has_dbmeta or has_legacy:
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

        if not Confirm.ask("Update configuration?", default=True):
            console.print("[dim]Setup cancelled.[/dim]")
            return
    else:
        console.print(f"\n[dim]Claude Desktop config: {claude_config_path}[/dim]")
        if not claude_config_path.exists():
            console.print("[dim]Will create new config file.[/dim]")

    # Prompt for DATABASE_URL
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
        return

    # Build dbmeta config (saved to ~/.dbmeta/config.yaml)
    config = {
        "database_url": database_url,
        "provider_id": "default",
        "tool_mode": "shell",
        "vault_path": str(VAULT_DIR),
        "log_level": "INFO",
    }

    # Save dbmeta config
    save_config(config)
    console.print(f"\n[green]✓ Config saved to {CONFIG_FILE}[/green]")

    # Create vault directory
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

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


@main.command()
def start():
    """Start the MCP server (stdio mode for Claude Desktop)."""
    if not CONFIG_FILE.exists():
        console.print("[red]No config found. Run 'dbmeta init' first.[/red]")
        sys.exit(1)

    config = load_config()

    # Set environment variables from config
    os.environ["DATABASE_URL"] = config.get("database_url", "")
    os.environ["PROVIDER_ID"] = config.get("provider_id", "default")
    os.environ["TOOL_MODE"] = config.get("tool_mode", "shell")
    os.environ["VAULT_PATH"] = config.get("vault_path", str(VAULT_DIR))
    os.environ["LOG_LEVEL"] = config.get("log_level", "INFO")
    os.environ["MCP_TRANSPORT"] = "stdio"  # Always stdio for CLI

    # Set writable paths for local CLI (not the bundled read-only resources)
    os.environ["RESOURCES_DIR"] = str(CONFIG_DIR / "resources")
    os.environ["PROVIDERS_DIR"] = str(CONFIG_DIR / "providers")

    # Ensure directories exist
    (CONFIG_DIR / "resources").mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "providers").mkdir(parents=True, exist_ok=True)

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

    editor = os.environ.get("EDITOR", "nano")
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
def status():
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
        db_url = config.get("database_url", "N/A")
        # Mask password
        if "@" in db_url and ":" in db_url.split("@")[0]:
            parts = db_url.split("@")
            prefix = parts[0]
            scheme_user = prefix.rsplit(":", 1)[0]
            db_url = f"{scheme_user}:****@{parts[1]}"
        console.print(f"  Config file: [green]{CONFIG_FILE}[/green]")
        console.print(
            f"  Database:    [cyan]{db_url[:60]}{'...' if len(db_url) > 60 else ''}[/cyan]"
        )
        console.print(f"  Provider:    {config.get('provider_id', 'N/A')}")
        console.print(f"  Tool mode:   {config.get('tool_mode', 'N/A')}")
    else:
        console.print(f"  [yellow]No config found at {CONFIG_FILE}[/yellow]")
        console.print("  [dim]Run 'dbmeta init' to configure.[/dim]")

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

    # Vault status
    console.print("\n[bold]Knowledge Vault[/bold]")
    if VAULT_DIR.exists():
        protocol = VAULT_DIR / "PROTOCOL.md"
        examples = VAULT_DIR / "examples"
        console.print(f"  Vault path:  [green]{VAULT_DIR}[/green]")
        proto_status = "[green]✓[/green]" if protocol.exists() else "[yellow]missing[/yellow]"
        console.print(f"  PROTOCOL.md: {proto_status}")
        if examples.exists():
            example_count = len(list(examples.glob("*.yaml")))
            console.print(f"  Examples:    {example_count} files")
        else:
            console.print("  Examples:    [dim]none yet[/dim]")
    else:
        console.print(f"  [dim]Vault not initialized at {VAULT_DIR}[/dim]")


if __name__ == "__main__":
    main()
