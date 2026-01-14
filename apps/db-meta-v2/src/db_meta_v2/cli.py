"""dbmeta CLI - Standalone CLI for db-meta-v2 MCP server.

Commands:
    dbmeta init          - Interactive setup wizard
    dbmeta start         - Start MCP server (stdio mode)
    dbmeta config        - Open config in editor
    dbmeta claude-desktop - Configure Claude Desktop
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()

# Config paths
CONFIG_DIR = Path.home() / ".dbmeta"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
VAULT_DIR = CONFIG_DIR / "vault"


def get_claude_desktop_config_path() -> Path:
    """Get Claude Desktop config path for current OS."""
    system = platform.system()
    if system == "Darwin":  # macOS
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:  # Linux
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"


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


@click.group()
@click.version_option(version="0.1.2")
def main():
    """dbmeta - Database metadata MCP server for Claude Desktop."""
    pass


@main.command()
def init():
    """Interactive setup wizard."""
    console.print(
        Panel.fit(
            "[bold blue]dbmeta Setup Wizard[/bold blue]\n\n"
            "This will configure dbmeta to connect to your database\n"
            "and optionally set up Claude Desktop integration.",
            border_style="blue",
        )
    )

    # Check for existing config
    if CONFIG_FILE.exists():
        existing = load_config()
        console.print(f"\n[yellow]Existing config found at {CONFIG_FILE}[/yellow]")
        if not Confirm.ask("Overwrite existing configuration?", default=False):
            console.print("[dim]Setup cancelled.[/dim]")
            return

    console.print("\n[bold]Database Connection[/bold]")
    console.print("[dim]Examples:[/dim]")
    console.print("  Trino:      trino://user:pass@host:8443/catalog/schema?http_scheme=https")
    console.print("  ClickHouse: clickhouse+native://user:pass@host:9000/database")
    console.print("  PostgreSQL: postgresql://user:pass@host:5432/database")
    console.print()

    database_url = Prompt.ask(
        "Database URL",
        default=existing.get("database_url", "") if CONFIG_FILE.exists() else "",
    )

    if not database_url:
        console.print("[red]Database URL is required.[/red]")
        return

    provider_id = Prompt.ask(
        "Provider ID",
        default="default",
    )

    console.print("\n[bold]Tool Mode[/bold]")
    console.print("  [cyan]shell[/cyan]    - Shell-first mode (recommended for autonomous agents)")
    console.print("  [cyan]detailed[/cyan] - Full toolset with schema discovery tools")
    console.print()

    tool_mode = Prompt.ask(
        "Tool mode",
        choices=["shell", "detailed"],
        default="shell",
    )

    # Build config
    config = {
        "database_url": database_url,
        "provider_id": provider_id,
        "tool_mode": tool_mode,
        "vault_path": str(VAULT_DIR),
        "log_level": "INFO",
    }

    # Save config
    save_config(config)
    console.print(f"\n[green]✓ Config saved to {CONFIG_FILE}[/green]")

    # Create vault directory
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓ Vault directory created at {VAULT_DIR}[/green]")

    # Offer Claude Desktop setup
    console.print()
    if Confirm.ask("Configure Claude Desktop integration?", default=True):
        _configure_claude_desktop(silent=False)

    console.print(
        Panel.fit(
            "[bold green]Setup Complete![/bold green]\n\n"
            "To start the server manually:\n"
            "  [cyan]dbmeta start[/cyan]\n\n"
            "If you configured Claude Desktop, restart it to connect.",
            border_style="green",
        )
    )


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

    # Import and run the server
    from db_meta_v2.server import main as server_main

    server_main()


@main.command()
def config():
    """Open config file in editor."""
    if not CONFIG_FILE.exists():
        console.print("[yellow]No config found. Run 'dbmeta init' first.[/yellow]")
        if Confirm.ask("Create config now?", default=True):
            ctx = click.get_current_context()
            ctx.invoke(init)
            return
        return

    editor = os.environ.get("EDITOR", "nano")
    console.print(f"[dim]Opening {CONFIG_FILE} in {editor}...[/dim]")

    try:
        subprocess.run([editor, str(CONFIG_FILE)], check=True)
        console.print("[green]✓ Config saved.[/green]")
    except FileNotFoundError:
        console.print(f"[red]Editor '{editor}' not found.[/red]")
        console.print("[dim]Set EDITOR environment variable or edit manually:[/dim]")
        console.print(f"  {CONFIG_FILE}")
    except subprocess.CalledProcessError:
        console.print("[yellow]Editor exited with error.[/yellow]")


def _configure_claude_desktop(silent: bool = False) -> bool:
    """Configure Claude Desktop to use dbmeta.

    Returns True if successful.
    """
    config_path = get_claude_desktop_config_path()

    # Load existing config or create new
    if config_path.exists():
        try:
            with open(config_path) as f:
                claude_config = json.load(f)
        except json.JSONDecodeError:
            if not silent:
                console.print(f"[red]Invalid JSON in {config_path}[/red]")
            return False
    else:
        claude_config = {}

    # Ensure mcpServers key exists
    if "mcpServers" not in claude_config:
        claude_config["mcpServers"] = {}

    # Check if dbmeta already configured
    if "dbmeta" in claude_config["mcpServers"]:
        if not silent:
            console.print("[yellow]dbmeta is already configured in Claude Desktop.[/yellow]")
            if not Confirm.ask("Update existing configuration?", default=True):
                return False

    # Get binary path
    binary_path = get_dbmeta_binary_path()

    # Add dbmeta server config
    claude_config["mcpServers"]["dbmeta"] = {
        "command": binary_path,
        "args": ["start"],
    }

    # Ensure parent directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Save config
    with open(config_path, "w") as f:
        json.dump(claude_config, f, indent=2)

    if not silent:
        console.print(f"[green]✓ Claude Desktop configured at {config_path}[/green]")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print("  1. Restart Claude Desktop")
        console.print("  2. Look for 'dbmeta' in the MCP servers list")
        console.print("  3. Start a conversation and ask about your database!")

    return True


@main.command("claude-desktop")
def claude_desktop():
    """Configure Claude Desktop integration."""
    console.print(
        Panel.fit(
            "[bold blue]Claude Desktop Configuration[/bold blue]\n\n"
            "This will add dbmeta to your Claude Desktop MCP servers.",
            border_style="blue",
        )
    )

    if not CONFIG_FILE.exists():
        console.print("[yellow]No dbmeta config found.[/yellow]")
        if Confirm.ask("Run setup wizard first?", default=True):
            ctx = click.get_current_context()
            ctx.invoke(init)
            return
        console.print("[dim]Run 'dbmeta init' to configure.[/dim]")
        return

    _configure_claude_desktop(silent=False)


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
        console.print(f"  Config file: [green]{CONFIG_FILE}[/green]")
        console.print(f"  Database:    [cyan]{config.get('database_url', 'N/A')[:50]}...[/cyan]")
        console.print(f"  Provider:    {config.get('provider_id', 'N/A')}")
        console.print(f"  Tool mode:   {config.get('tool_mode', 'N/A')}")
        console.print(f"  Vault:       {config.get('vault_path', 'N/A')}")
    else:
        console.print(f"  [yellow]No config found at {CONFIG_FILE}[/yellow]")
        console.print("  [dim]Run 'dbmeta init' to configure.[/dim]")

    # Claude Desktop status
    console.print("\n[bold]Claude Desktop[/bold]")
    claude_config_path = get_claude_desktop_config_path()
    if claude_config_path.exists():
        try:
            with open(claude_config_path) as f:
                claude_config = json.load(f)
            if "dbmeta" in claude_config.get("mcpServers", {}):
                console.print("  [green]✓ dbmeta configured in Claude Desktop[/green]")
                cmd = claude_config["mcpServers"]["dbmeta"].get("command", "N/A")
                console.print(f"  Command: {cmd}")
            else:
                console.print("  [yellow]dbmeta not configured in Claude Desktop[/yellow]")
                console.print("  [dim]Run 'dbmeta claude-desktop' to configure.[/dim]")
        except json.JSONDecodeError:
            console.print("  [red]Invalid Claude Desktop config[/red]")
    else:
        console.print(f"  [dim]Claude Desktop config not found at {claude_config_path}[/dim]")

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
