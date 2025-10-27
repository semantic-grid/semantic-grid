import pathlib
from typing import Dict

from dbmeta_app.prompt_assembler.prompt_packs import (
    assemble_effective_tree,
    load_yaml,
    sha256_bytes,
)


def compute_lineage(tree: Dict[str, bytes], relpaths: list[str]) -> Dict[str, str]:
    return {rel: sha256_bytes(tree[rel]) for rel in relpaths if rel in tree}


if __name__ == "__main__":
    # check yaml file loading

    # system_pack = find_system_pack(
    #    repo_root=repo_root / "resources",  # <-- just the prompts root
    #    component=component,
    #    version=None,  # None means latest
    # )
    # overlay_dirs: List[pathlib.Path] = []
    # if client and env:
    #    ov = find_client_overlay(repo_root, client, env, component)
    #    if ov:
    #        overlay_dirs.append(ov)
    # print("system_pack", system_pack)
    # print("overlay_dirs", overlay_dirs)

    repo_root = pathlib.Path('/app/packages').resolve()
    component = "dbmeta_app"
    client = "apegpt"
    env = "prod"
    profile = "wh_v2"
    tree = assemble_effective_tree(repo_root, profile, client, env)

    merged = load_yaml(tree, "resources/prompt_instructions.yaml")["profiles"][profile]

    print("instructions", merged)

    lineage = compute_lineage(
        tree,
        [
            "resources/prompt_instructions.yaml",
            "resources/query_examples.yaml",
            "resources/schema_descriptions.yaml",
            "resources/dialect_capabilities.yaml",
        ],
    )

    print("lineage", lineage)

    # asyncio.run(check_mcp(mcp))

    # Start the FastAPI server
    # mcp.run(transport="sse", host="0.0.0.0", port=settings.port)
