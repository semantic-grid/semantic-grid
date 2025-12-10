"""SQL dialect prompt item generator."""

import pathlib

from dbmeta_app.api.model import PromptItem, PromptItemType
from dbmeta_app.config import get_settings
from dbmeta_app.prompt_assembler.prompt_packs import assemble_effective_tree, load_yaml
from dbmeta_app.prompt_items.utils import compute_content_hash


def get_sql_dialect_item(profile: str) -> PromptItem:
    """Get SQL dialect instructions as a PromptItem.

    Args:
        profile: The database profile to get dialect instructions for

    Returns:
        PromptItem containing SQL dialect instructions
    """
    settings = get_settings()
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    client = settings.client
    env = settings.env
    tree = assemble_effective_tree(repo_root, profile, client, env)

    dialect_config = load_yaml(tree, "resources/sql_dialect.yaml")

    # Handle missing profiles key or profile
    if "profiles" not in dialect_config:
        instructions = []
    elif profile not in dialect_config["profiles"]:
        instructions = []
    else:
        instructions = dialect_config["profiles"][profile]

    # Format into a human-readable LLM prompt
    if instructions:
        llm_prompt = "\n\n### SQL Dialect Instructions:\n" + "\n".join(
            f"- {instruction}" for instruction in instructions
        )
    else:
        llm_prompt = ""

    # Compute hash and metadata for lineage tracking
    content_hash = compute_content_hash(llm_prompt)
    metadata = {
        "profile": profile,
        "client": client,
        "env": env,
        "instructions_count": len(instructions),
    }

    return PromptItem(
        text=llm_prompt,
        prompt_item_type=PromptItemType.sql_dialect,
        score=100_000,
        content_hash=content_hash,
        metadata=metadata,
    )


def get_sql_dialect_instructions(profile: str) -> list[str]:
    """Get raw SQL dialect instructions list.

    Args:
        profile: The database profile to get dialect instructions for

    Returns:
        List of SQL dialect instruction strings
    """
    settings = get_settings()
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    client = settings.client
    env = settings.env
    tree = assemble_effective_tree(repo_root, profile, client, env)

    dialect_config = load_yaml(tree, "resources/sql_dialect.yaml")

    if "profiles" not in dialect_config:
        return []
    if profile not in dialect_config["profiles"]:
        return []

    return dialect_config["profiles"][profile]
