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

from db_meta_v2.onboarding.state import get_connection_path

logger = logging.getLogger(__name__)

# Critical reminder injected into every tool response
CRITICAL_REMINDER = """
## CRITICAL REMINDER

**0. FIRST: Read and follow the knowledge vault protocol:**
   shell(command='cat PROTOCOL.md')

**Database uses 3-level hierarchy: catalog.schema.table**

Before writing SQL:
1. Use list_catalogs() to see available catalogs
2. Use list_schemas(catalog='...') to see schemas
3. Use list_tables(catalog='...', schema='...') with BOTH parameters

---
"""


def inject_protocol(result: dict, session_id: str | None = None):
    """Inject critical reminder into tool response.

    For small results: includes reminder + JSON in text content
    For large results: includes reminder + summary only (data in structuredContent)

    Args:
        result: Tool result dict
        session_id: Unused, kept for API compatibility

    Returns:
        CallToolResult with text content and structured data
    """
    import json

    from mcp.types import CallToolResult, TextContent

    if not isinstance(result, dict):
        return result

    reminder = CRITICAL_REMINDER.strip()

    # Check if result has large data (e.g., query results)
    data = result.get("data", [])
    is_large = isinstance(data, list) and len(data) > 20

    if is_large:
        # For large results, only show summary in text (full data in structuredContent)
        rows = len(data)
        status = result.get("status", "unknown")
        summary = f"Status: {status}, Rows: {rows}"
        if "columns" in result:
            summary += f", Columns: {result['columns']}"
        text_output = (
            f"{reminder}\n\n--- RESULT SUMMARY ---\n{summary}\n\n"
            "(Full data in structured response)"
        )
    else:
        # For small results, include full JSON
        json_data = json.dumps(result, indent=2, default=str)
        text_output = f"{reminder}\n\n--- DATA ---\n\n{json_data}"

    return CallToolResult(
        content=[TextContent(type="text", text=text_output)],
        structuredContent=result,
        isError=False,
    )


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


# Shell tool descriptions for different modes
SHELL_DESCRIPTION_DETAILED = """Run bash command in the knowledge vault.

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

Args:
    command: Bash command to execute in the vault

Returns:
    dict with stdout, stderr, exit_code
"""

SHELL_DESCRIPTION_SHELL_MODE = """YOUR PRIMARY TOOL - Use this for ALL query preparation.

START IMMEDIATELY with: cat PROTOCOL.md

This shell is your Swiss Army knife. The connection directory contains everything you need:

    connection/
    ├── PROTOCOL.md            # READ THIS FIRST - critical instructions
    ├── state.yaml             # Onboarding state
    ├── schema/
    │   └── descriptions.yaml  # Cached schema with descriptions
    ├── domain/
    │   └── model.md           # Domain model (business entities)
    ├── instructions/
    │   └── sql_rules.md       # SQL dialect rules
    ├── examples/              # Query examples (YAML)
    └── learnings/             # Patterns, common mistakes

WORKFLOW:
    1. cat PROTOCOL.md                              # Understand the rules
    2. cat schema/descriptions.yaml | head -100     # Check cached schema
    3. cat domain/model.md                          # Understand the domain
    4. grep -ri "keyword" examples/                 # Find similar queries
    5. cat instructions/sql_rules.md                # Check SQL rules
    6. Write SQL based on what you found
    7. Use validate_sql() then run_sql() to execute
    8. Save successful queries to examples/

Available commands:
    - Read: cat, grep, find, ls, head, tail, wc, sort, uniq, diff
    - Write: mkdir, touch, tee (append-only)
    - Utils: echo, date, uuidgen

Args:
    command: Bash command to execute in the connection directory

Returns:
    dict with stdout, stderr, exit_code
"""


async def _shell(command: str) -> dict:
    """Run bash command in the connection directory - see SHELL_DESCRIPTION_* for docs."""
    connection_path = get_connection_path()

    # Validate command
    validation = validate_command(command)
    if not validation.ok:
        logger.warning(f"Blocked command: {command} - {validation.message}")
        return {
            "stdout": "",
            "stderr": f"Error: {validation.message}",
            "exit_code": 1,
        }

    # Ensure connection directory exists
    if not connection_path.exists():
        return {
            "stdout": "",
            "stderr": f"Connection path does not exist: {connection_path}",
            "exit_code": 1,
        }

    # Run command
    logger.info(f"Running shell command: {command[:100]}...")
    result = await run_sandboxed(command, connection_path)

    # Log writes for audit
    if validation.is_write:
        logger.info(f"Connection write operation: {command[:100]}...")

    # Auto-inject protocol on first successful command
    if result["exit_code"] == 0:
        result = inject_protocol(result)

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
    protocol_path = get_connection_path() / "PROTOCOL.md"

    if protocol_path.exists():
        return protocol_path.read_text()

    return "PROTOCOL.md not found. Connection may not be initialized."
