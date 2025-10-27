# from __future__ import annotations

import copy
import hashlib
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml
from jsonschema import Draft202012Validator, validate
from jsonschema import exceptions as jsonschema_ex

# ---------- Utilities


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def read_yaml(path: pathlib.Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_yaml(tree: Dict[str, bytes], rel: str) -> Dict[str, Any]:
    return yaml.safe_load(tree.get(rel, b"{}")) or {}


def write_text(path: pathlib.Path, s: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-8")


# ---------- helpers


def _make_hashable(x: Any) -> Any:
    if isinstance(x, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in x.items()))
    if isinstance(x, (list, tuple)):
        return tuple(_make_hashable(v) for v in x)
    return x


def _merge_lists(
    base: list, patch: list, strategy: str = "append", id_key: str | None = None
):
    if strategy == "override" or strategy == "replace":
        # full replacement
        return copy.deepcopy(patch)

    if strategy == "append":
        return base + patch

    if strategy == "unique":
        out = list(base)
        for v in patch:
            if v not in out:
                out.append(v)
        return out

    if strategy == "by_id":
        if not id_key:
            raise ValueError("id_key required for by_id strategy")
        out = {
            item[id_key]: dict(item)
            for item in base
            if isinstance(item, dict) and id_key in item
        }
        for item in patch:
            if isinstance(item, dict) and id_key in item:
                out[item[id_key]] = dict(item)
            else:
                out[str(item)] = item
        return list(out.values())

    raise ValueError(f"Unknown list merge strategy: {strategy}")


# ---------- core merge

_META_KEYS = {"strategy", "id_key", "strategies", "id_keys", "__list__"}


def json_merge_patch(
    base: Any,
    patch: Any,
    *,
    list_strategy: str = "append",  # default mode: 'append' | 'unique' | 'by_id'
    list_id_key: Optional[str] = None,
) -> Any:
    """
    Extended JSON Merge Patch:
      - dict vs dict: RFC 7386 (null deletes), plus:
          * read local defaults: 'strategy', 'id_key'
          * read per-child overrides: 'strategies', 'id_keys' (dicts of child->value)
          * meta-keys are not emitted in output
      - list vs list: merge using strategy/id_key
      - list vs dict (overlay carries meta): if patch has '__list__' use it
        with strategy/id_key
      - anything else: replace
    """

    # dict vs dict → merge keys, honoring meta
    if isinstance(base, dict) and isinstance(patch, dict):
        # node-level defaults from patch
        local_strategy = patch.get("strategy", list_strategy)
        local_id_key = patch.get("id_key", list_id_key)
        per_child_strat = patch.get("strategies", {}) or {}
        per_child_idkey = patch.get("id_keys", {}) or {}

        out = copy.deepcopy(base)

        for k, v in patch.items():
            if k in _META_KEYS:
                continue  # never materialize meta keys

            if v is None:
                out.pop(k, None)
                continue

            # child-specific overrides if provided
            child_strategy = per_child_strat.get(k, local_strategy)
            child_id_key = per_child_idkey.get(k, local_id_key)

            if k in out:
                out[k] = json_merge_patch(
                    out[k],
                    v,
                    list_strategy=child_strategy,
                    list_id_key=child_id_key,
                )

            elif isinstance(v, list) and isinstance(out.get(k), list):
                list_strategy = patch.get("strategies", {}).get(k) or patch.get(
                    "strategy", "append"
                )
                id_key = patch.get("id_key")
                out[k] = _merge_lists(out[k], v, strategy=list_strategy, id_key=id_key)

            else:
                # new key entirely
                if isinstance(v, dict):
                    # if it's a wrapped list node, unwrap immediately
                    if "__list__" in v and isinstance(base.get(k, None), list):
                        out[k] = _merge_wrapped_list(
                            base_list=[],  # no base for new key
                            patch_wrapper=v,
                            strategy=child_strategy,
                            id_key=child_id_key,
                        )
                    else:
                        out[k] = json_merge_patch(
                            {},
                            v,
                            list_strategy=child_strategy,
                            list_id_key=child_id_key,
                        )
                else:
                    out[k] = copy.deepcopy(v)
        return out

    # list vs list → merge
    if isinstance(base, list) and isinstance(patch, list):
        return _merge_lists(base, patch, strategy=list_strategy, id_key=list_id_key)

    # list vs dict → allow wrapped list with meta keys
    if (
        isinstance(base, list)
        and isinstance(patch, dict)
        and ("__list__" in patch or any(k in patch for k in ("strategy", "id_key")))
    ):
        return _merge_wrapped_list(
            base, patch, strategy=list_strategy, id_key=list_id_key
        )

    # otherwise → replace
    return copy.deepcopy(patch)


def _merge_wrapped_list(
    base_list: list, patch_wrapper: dict, *, strategy: str, id_key: Optional[str]
) -> list:
    """
    Handle overlay of the form:
      { strategy: 'unique', id_key: 'id', __list__: [...] }
    """
    local_strategy = patch_wrapper.get("strategy", strategy)
    local_id_key = patch_wrapper.get("id_key", id_key)
    data = patch_wrapper.get("__list__", [])
    if not isinstance(data, list):
        # if user forgot __list__, treat wrapper as replacement (preserve behavior)
        return copy.deepcopy(data)
    return _merge_lists(base_list, data, strategy=local_strategy, id_key=local_id_key)


# ---------- Schemas (minimal, extend as needed)

PACK_MANIFEST_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "version",
    ],
    "properties": {
        "pack_name": {"type": "string"},
        "version": {"type": "string"},  # semver string; format check optional
        "target_component": {"enum": ["fm_app", "db-meta", "db-ref"]},
        "license": {"type": "string"},
        "dependencies": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "version"],
                "properties": {
                    "name": {"type": "string"},
                    "version": {"type": "string"},
                },
            },
        },
        "slots": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "required": {"type": "boolean"},
                    "inputs": {"type": "array", "items": {"type": "string"}},
                    "outputs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "provenance": {"type": "object"},
    },
    "additionalProperties": True,
}

# ---------- Data models


@dataclass(frozen=True)
class PackRef:
    root: pathlib.Path
    manifest: Dict[str, Any]
    version: str
    pack_name: str
    target_component: str
    hash: str  # content hash of the pack directory (rough)


@dataclass
class SlotMaterial:
    slot: str
    prompt_text: str
    extras: Dict[str, str]  # e.g., {"policy.md": "...", "fewshot.yaml": "..."}
    lineage: Dict[str, Any]  # manifest + overlay info + hashes


class PackValidationError(Exception): ...


class SlotNotFound(Exception): ...


class OverlayError(Exception): ...


class RenderError(Exception): ...


# ---------- Loader


def _dir_hash(root: pathlib.Path) -> str:
    """Compute a simple content hash for a directory (names + bytes)."""
    hasher = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root)).encode()
            hasher.update(rel)
            hasher.update(p.read_bytes())
    return hasher.hexdigest()


def load_pack(pack_dir: pathlib.Path) -> PackRef:
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise PackValidationError(f"manifest.yaml not found in {pack_dir}")
    manifest = read_yaml(manifest_path) or {}
    try:
        validate(manifest, PACK_MANIFEST_SCHEMA, cls=Draft202012Validator)
    except jsonschema_ex.ValidationError as e:
        raise PackValidationError(f"Manifest invalid: {e.message}") from e
    version = manifest["version"]
    # pack_name = manifest["pack_name"]
    # target = manifest["target_component"]
    return PackRef(
        root=pack_dir,
        manifest=manifest,
        version=version,
        pack_name="resources",  # pack_name,
        target_component="dbmeta_app",  # target,
        hash=_dir_hash(pack_dir),
    )


def find_system_pack(
    repo_root: pathlib.Path, component: str, version: Optional[str] = None
) -> PackRef:
    base = repo_root / "resources" / component / "system-pack"
    if version:
        pack_dir = base / version
        if not pack_dir.exists():
            raise FileNotFoundError(
                f"System pack {component}@{version} not found at {pack_dir}"
            )
        return load_pack(pack_dir)
    # pick latest semver-like folder name lexicographically as a heuristic
    candidates = [p for p in base.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No system packs found at {base}")
    chosen = sorted(candidates, key=lambda p: p.name)[-1]
    return load_pack(chosen)


def find_client_overlay(
    repo_root: pathlib.Path, client: str, env: str, component: str
) -> Optional[pathlib.Path]:
    p = repo_root / "client-configs" / client / env / component / "overlays"
    return p if p.exists() else None


# ---------- Overlay assembly (by file)


def _collect_files(root: pathlib.Path) -> Dict[str, pathlib.Path]:
    """
    Return map of relative posix path -> absolute path for all files under root,
    excluding hidden dirs like .git
    """
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            if "/." in rel or rel.startswith("."):
                continue
            out[rel] = p
    return out


def _read_overlay_json_if_exists(path: pathlib.Path) -> Optional[Dict[str, Any]]:
    """
    If file ends with .json or .yaml and alongside there's a
    .patch.(json|yaml), apply patch.
    """
    # Pattern: for JSON/YAML documents you can provide a sibling
    # *.patch.json(yaml) with diff but default approach: we overlay
    # by file replacement. JSON Merge Patch is best for *.json/*.yaml
    # named exactly same in overlay.
    return None


def assemble_tree(
    system_root: pathlib.Path, overlays: List[pathlib.Path]
) -> Dict[str, bytes]:
    """
    Build the effective file tree:
    - Start with system pack files
    - For each overlay (in order), replace files by name.
    - For *.json/*.yaml where both base and overlay are mappings, apply JSON Merge Patch
    Returns dict: relpath -> bytes
    """
    print('tree', system_root, overlays)
    base_files = _collect_files(system_root)
    tree: Dict[str, bytes] = {}
    for rel, ap in base_files.items():
        tree[rel] = ap.read_bytes()

    for overlay_root in overlays:
        ov_files = _collect_files(overlay_root)
        for rel, ap in ov_files.items():
            # Try merge for yaml/json if both are mappings
            if rel.endswith((".json", ".yaml", ".yml")) and rel in tree:
                try:
                    base_doc = yaml.safe_load(tree[rel].decode("utf-8"))
                    ov_doc = yaml.safe_load(ap.read_text(encoding="utf-8"))
                    if isinstance(base_doc, dict) and isinstance(ov_doc, dict):
                        merged = json_merge_patch(base_doc, ov_doc)
                        tree[rel] = yaml.safe_dump(merged, sort_keys=False).encode(
                            "utf-8"
                        )
                        continue
                except Exception as e:
                    print(f"Error while merging {overlay_root}/{rel}: {str(e)}")
                    # fall back to replacement
                    pass
            tree[rel] = ap.read_bytes()
    return tree


def _semver_key(name: str):
    """
    Sort helper: tries to parse x.y.z; falls back to plain string order.
    """
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", name)
    if m:
        return tuple(int(x) for x in m.groups())
    return (0, 0, 0, name)


def assemble_effective_tree(
    REPO_ROOT, profile: str, client: str | None, env: str | None
) -> Dict[str, bytes]:
    """
    base = REPO_ROOT / "packs" / "system-pack" / <latest-version>/
    overlays (in order; later wins):
      1) REPO_ROOT / "client-configs" / <client> / "common" / "db-meta" / "overlays"
      2) REPO_ROOT / "client-configs" / <client> / <env>     / "db-meta" / "overlays"
    Returns: { relative_path: bytes }
    """
    packs_root = REPO_ROOT / "resources" / "dbmeta_app" / "system-pack"
    if not packs_root.exists():
        raise FileNotFoundError(f"System-pack root not found: {packs_root}")

    # choose latest version dir
    candidates = [p for p in packs_root.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No versions under {packs_root}")
    base_dir = sorted(candidates, key=lambda p: _semver_key(p.name))[-1]

    overlay_dirs: List[pathlib.Path] = []
    if client:
        common_ov = (
            REPO_ROOT / "client-configs" / client / "common" / "dbmeta_app" / "overlays"
        )
        env_ov = (
            REPO_ROOT
            / "client-configs"
            / client
            / (env or "")
            / "dbmeta_app"
            / "overlays"
        )
        if common_ov.exists():
            overlay_dirs.append(common_ov)
        if env and env_ov.exists():
            overlay_dirs.append(env_ov)

    # If you need profile-specific subtrees in overlays, you can add them here
    # e.g., overlays/profile/<profile>/... placed after generic overlays:
    if client:
        cand = (
            REPO_ROOT
            / "client-configs"
            / client
            / (env or "common")
            / "dbmeta_app"
            / "overlays"
            / "profiles"
            / profile
        )
        if cand.exists():
            overlay_dirs.append(cand)

    return assemble_tree(base_dir, overlay_dirs)


# ---------- async MCP registry helper


# helper to freeze context
def _freeze(obj):
    if isinstance(obj, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in obj.items()))
    if isinstance(obj, list):
        return tuple(_freeze(x) for x in obj)
    return obj
