"""Shell tool for knowledge vault access.

Provides a sandboxed bash interface for Claude to read, search, and append
knowledge in the vault directory. Commands are strictly validated against
an allowlist to prevent security issues.
"""

import asyncio
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path

from db_meta_v2.config import get_settings

logger = logging.getLogger(__name__)

# Session state for protocol auto-injection
_session_state = {"protocol_injected": False}

# Commands allowed in the vault sandbox
ALLOWED_COMMANDS = {
    # Read operations
    "cat",
    "grep",
    "find",
    "ls",
    "head",
    "tail",
    "wc",
    "sort",
    "uniq",
    "diff",
    # Write operations (append-only enforced by convention)
    "mkdir",
    "touch",
    "tee",
    # Utilities
    "echo",
    "date",
    "uuidgen",
}

# Patterns that are never allowed
BLOCKED_PATTERNS = [
    "rm ",
    "rm\t",
    "rmdir",  # No deletions
    "mv ",
    "mv\t",  # No moves (would lose history)
    "curl",
    "wget",  # No network
    "$(",
    "`",  # No command substitution
    "|sh",
    "|bash",
    "| sh",
    "| bash",  # No shell injection
    "..",  # No parent directory traversal
    "/.oauth",  # No access to OAuth secrets
]


@dataclass
class CommandValidation:
    """Result of command validation."""

    ok: bool
    message: str = ""
    is_write: bool = False


def validate_command(command: str) -> CommandValidation:
    """Validate bash command against security rules.

    Args:
        command: The bash command to validate

    Returns:
        CommandValidation with ok=True if allowed, or ok=False with error message
    """
    if not command or not command.strip():
        return CommandValidation(ok=False, message="Empty command")

    # Check blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if pattern in command:
            return CommandValidation(
                ok=False, message=f"Pattern '{pattern.strip()}' not allowed for security reasons"
            )

    # Check for overwrite redirection (> without <<)
    # Allow heredoc (<<) and append (>>), block single >
    if "> " in command or ">\t" in command:
        # Check if it's actually a heredoc or append
        if "<<" not in command and ">>" not in command:
            return CommandValidation(
                ok=False,
                message="Overwrite '>' not allowed. Use '<<' heredoc or '>>' append",
            )

    # Parse base command
    try:
        parts = shlex.split(command)
        base_cmd = parts[0] if parts else ""
    except ValueError:
        # shlex can't parse heredocs, extract command manually
        base_cmd = command.split()[0] if command.split() else ""

    if not base_cmd:
        return CommandValidation(ok=False, message="Could not parse command")

    if base_cmd not in ALLOWED_COMMANDS:
        return CommandValidation(
            ok=False,
            message=f"Command '{base_cmd}' not allowed. Permitted: {sorted(ALLOWED_COMMANDS)}",
        )

    # Detect write operations
    is_write = any(op in command for op in [">>", "<<", "tee ", "tee\t", "mkdir ", "touch "])

    return CommandValidation(ok=True, is_write=is_write)


async def run_sandboxed(command: str, cwd: Path, timeout: int = 30) -> dict:
    """Run a command in the sandboxed vault directory.

    Args:
        command: The bash command to run
        cwd: Working directory (must be vault path)
        timeout: Command timeout in seconds

    Returns:
        dict with stdout, stderr, and exit_code
    """
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": str(cwd),
                "VAULT_PATH": str(cwd),
            },
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds",
                "exit_code": 124,
            }

        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": process.returncode,
        }

    except Exception as e:
        logger.exception("Error running sandboxed command")
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
        }


async def _shell(command: str) -> dict:
    """Run bash command in the knowledge vault.

    A sandboxed bash interface for reading, searching, and appending knowledge.
    The working directory is the vault root. All operations are append-only
    (no deletions or overwrites allowed).

    Available commands:
        - Read: cat, grep, find, ls, head, tail, wc, sort, uniq, diff
        - Write: mkdir, touch, tee (append-only)
        - Utils: echo, date, uuidgen

    Examples:
        # Search for examples
        grep -ri "venue" examples/

        # Read instructions
        cat instructions/sql_rules.md

        # Find recent examples
        find examples -name "*.yaml" -mtime -7

        # Create new example (heredoc)
        cat > examples/$(uuidgen).yaml << 'EOF'
        id: ...
        intent: "..."
        sql: |
          SELECT ...
        EOF

        # Append to patterns
        cat >> learnings/patterns.md << 'EOF'
        ## New Pattern
        ...
        EOF

    Args:
        command: Bash command to execute in the vault

    Returns:
        dict with:
            - stdout: Command output
            - stderr: Error output (if any)
            - exit_code: Command exit code (0 = success)
    """
    settings = get_settings()
    vault_path = Path(settings.vault_path)

    # Validate command
    validation = validate_command(command)
    if not validation.ok:
        logger.warning(f"Blocked command: {command} - {validation.message}")
        return {
            "stdout": "",
            "stderr": f"Error: {validation.message}",
            "exit_code": 1,
        }

    # Ensure vault exists
    if not vault_path.exists():
        return {
            "stdout": "",
            "stderr": f"Vault path does not exist: {vault_path}",
            "exit_code": 1,
        }

    # Run command
    logger.info(f"Running vault command: {command[:100]}...")
    result = await run_sandboxed(command, vault_path)

    # Log writes for audit
    if validation.is_write:
        logger.info(f"Vault write operation: {command[:100]}...")

    # Auto-inject protocol on first successful command
    if not _session_state["protocol_injected"] and result["exit_code"] == 0:
        _session_state["protocol_injected"] = True
        protocol_path = vault_path / "PROTOCOL.md"
        if protocol_path.exists():
            protocol_content = protocol_path.read_text()
            result["stdout"] = f"""# Knowledge Vault Protocol (auto-loaded)

{protocol_content}

---
## Command Output:

{result["stdout"]}"""
            logger.info("Auto-injected PROTOCOL.md on first shell call")

    return result


async def _protocol() -> str:
    """Re-read the knowledge vault protocol.

    Use this if you need a reminder about:
    - Database hierarchy rules
    - How to save examples and learnings
    - User transparency requirements

    Returns:
        The full PROTOCOL.md content
    """
    settings = get_settings()
    protocol_path = Path(settings.vault_path) / "PROTOCOL.md"

    if protocol_path.exists():
        return protocol_path.read_text()

    return "PROTOCOL.md not found. Vault may not be initialized."
