import pathlib

from dbmeta_app.api.model import PromptItem, PromptItemType
from dbmeta_app.config import get_settings
from dbmeta_app.prompt_assembler.prompt_packs import assemble_effective_tree
from dbmeta_app.prompt_items.utils import compute_content_hash


def get_domain_model_item(profile: str) -> PromptItem | None:
    """
    Load the domain model (entity relationships, business context) from client overlay.

    The domain model is a markdown file that describes:
    - Entity definitions (what each table represents)
    - Relationships (explicit and inferred FKs, join paths)
    - Business context (subscriber lifecycle, network assets, etc.)
    - Data quality notes (missing tables, gaps)

    Returns None if no domain_model.md file exists for this profile.
    """
    settings = get_settings()
    repo_root = pathlib.Path(settings.packs_resources_dir).resolve()
    client = settings.client
    env = settings.env
    tree = assemble_effective_tree(repo_root, profile, client, env)

    # Try to load domain_model.md from the effective tree
    domain_model_path = "resources/domain_model.md"

    # Check if file exists in the tree
    if domain_model_path not in tree:
        return None

    file_path = tree[domain_model_path]
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, IOError):
        return None

    if not content.strip():
        return None

    # Format as LLM prompt
    llm_prompt = f"\n\n### Domain Model (Entity Relationships)\n\n{content}"

    # Compute hash and metadata for lineage tracking
    content_hash = compute_content_hash(llm_prompt)
    metadata = {
        "profile": profile,
        "client": client,
        "env": env,
        "source_file": str(file_path),
    }

    return PromptItem(
        text=llm_prompt,
        prompt_item_type=PromptItemType.domain_model,
        score=90_000,  # High priority - provides context for query planning
        content_hash=content_hash,
        metadata=metadata,
    )
