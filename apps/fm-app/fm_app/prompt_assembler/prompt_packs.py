# from __future__ import annotations

import copy
import hashlib
import os
import pathlib
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import yaml
from jinja2 import BaseLoader, Environment, StrictUndefined
from jsonschema import Draft202012Validator, validate
from jsonschema import exceptions as jsonschema_ex

# ---------- Utilities


def _get_effective_text(effective_tree: Dict[str, bytes], rel: str) -> Optional[str]:
    b = effective_tree.get(rel)
    if b is None:
        return None
    return b.decode("utf-8", errors="ignore")


def _apply_default_decorators(
    prompt_text: str,
    slot: str,
    env: Environment,
    effective_tree: Dict[str, bytes],
) -> str:
    # allow opt-out per slot
    no_default_marker = f"slots/{slot}/.no-default"
    if no_default_marker in effective_tree:
        return prompt_text

    # 1) wrapper.md takes precedence if present
    wrapper_rel = "slots/__default/wrapper.md"
    wrapper_src = _get_effective_text(effective_tree, wrapper_rel)
    if wrapper_src:
        try:
            # Render wrapper via Jinja too, with {{ content }} available
            # Make a one-off template from string (keeps your existing loader)
            tmpl = env.from_string(wrapper_src)
            return tmpl.render(content=prompt_text)
        except Exception:
            pass  # fall back to pre/post

    # 2) prelude + postlude
    pre = _get_effective_text(effective_tree, "slots/__default/prefix.md") or ""
    post = _get_effective_text(effective_tree, "slots/__default/postfix.md") or ""
    if pre or post:
        return f"{pre.rstrip()}\n\n{prompt_text.strip()}\n\n{post.lstrip()}"
    return prompt_text


def _apply_default_slot_overrides(
    effective_tree: Dict[str, bytes], overlay_dirs: list[pathlib.Path]
) -> Dict[str, bytes]:
    """
    If overlays provide slots/__default/<name>.md and no overlay provides slots/<slot>/<name>.md,
    then copy the __default file into each existing system slot path for that <name>.md.
    """
    # collect overlay files
    overlay_files: set[str] = set()
    for ov in overlay_dirs:
        for p in ov.rglob("*"):
            if p.is_file():
                overlay_files.add(p.relative_to(ov).as_posix())

    # for each default file in overlays, project it onto slots/*/<file> when no overlay-specific exists
    for rel in list(effective_tree.keys()):
        # find slot files that exist (from system) and are candidates for default substitution
        m = re.match(r"^slots/([^/]+)/([^/]+\.md)$", rel)
        if not m:
            continue
        slot_name, fname = m.group(1), m.group(2)

        default_rel = f"slots/__default/{fname}"
        slot_overlay_rel = f"slots/{slot_name}/{fname}"

        # if client default exists AND there is no client slot-specific file,
        # then override the effective slot file with the default content
        if default_rel in overlay_files and slot_overlay_rel not in overlay_files:
            # read the overlay default bytes and assign into effective tree at the slot path
            for ov in overlay_dirs:
                default_path = ov / default_rel
                if default_path.exists():
                    effective_tree[rel] = default_path.read_bytes()
                    break
    return effective_tree


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def read_yaml(path: pathlib.Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_text(path: pathlib.Path, s: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-8")


def json_merge_patch(base: Any, patch: Any) -> Any:
    """
    RFC 7386 JSON Merge Patch applied to Python dict/list/primitive.
    - If patch is not a dict: replace
    - If value is null: remove key
    """
    if not isinstance(patch, dict) or not isinstance(base, dict):
        # replace mode
        return copy.deepcopy(patch)
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if v is None:
            if k in out:
                del out[k]
        else:
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = json_merge_patch(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
    return out


def deep_freeze(obj: Any) -> Any:
    """Make obj hashable for caching (tuples/ frozensets)."""
    if isinstance(obj, dict):
        return tuple(sorted((k, deep_freeze(v)) for k, v in obj.items()))
    if isinstance(obj, list):
        return tuple(deep_freeze(x) for x in obj)
    return obj


# ---------- Schemas (minimal, extend as needed)

PACK_MANIFEST_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["pack_name", "version", "target_component", "slots"],
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
    pack_name = manifest["pack_name"]
    target = manifest["target_component"]
    return PackRef(
        root=pack_dir,
        manifest=manifest,
        version=version,
        pack_name=pack_name,
        target_component=target,
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
    """If file ends with .json or .yaml and alongside there's a .patch.(json|yaml), apply patch."""
    # Pattern: for JSON/YAML documents you can provide a sibling *.patch.json(yaml) with diff
    # but default approach: we overlay by file replacement. JSON Merge Patch is best for *.json/*.yaml named exactly same in overlay.
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
                except Exception:
                    # fall back to replacement
                    pass
            tree[rel] = ap.read_bytes()
    return tree


# ---------- async MCP registry helper


# helper to freeze context
def _freeze(obj):
    if isinstance(obj, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in obj.items()))
    if isinstance(obj, list):
        return tuple(_freeze(x) for x in obj)
    return obj


# ---------- Jinja rendering with includes across base+overlays


class MultiRootLoader(BaseLoader):
    def __init__(self, roots: List[pathlib.Path]):
        self.roots = roots

    def get_source(self, environment, template):
        for r in self.roots:
            p = (r / template).resolve()
            if p.exists() and p.is_file():
                source = p.read_text(encoding="utf-8")
                mtime = os.path.getmtime(p)

                def is_up_to_date():
                    return os.path.getmtime(p) == mtime

                return source, str(p), is_up_to_date
        raise FileNotFoundError(template)


def build_jinja_env(search_roots: List[pathlib.Path]) -> Environment:
    env = Environment(
        loader=MultiRootLoader(search_roots),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


# ---------- Slot materialization


def _slot_paths(slot: str) -> Dict[str, str]:
    """
    Convention inside a pack:
    slots/<slot>/prompt.md (required)
    any extra files in that dir are carried along
    """
    base = f"slots/{slot}/"
    return {"prompt": base + "prompt.md"}


def materialize_slot(
    component_root: pathlib.Path,
    effective_tree: Dict[str, bytes],
    slot: str,
    search_roots_for_includes: List[pathlib.Path],
    variables: Dict[str, Any],
    lineage_base: Dict[str, Any],
) -> SlotMaterial:
    paths = _slot_paths(slot)
    prompt_rel = paths["prompt"]
    if prompt_rel not in effective_tree:
        raise SlotNotFound(f"Slot '{slot}' missing prompt at {prompt_rel}")

    # Write effective tree to a temp dir for Jinja includes to work across roots
    # Optimization: we let Jinja read from search_roots (system + overlays) to resolve {% include %} pieces.
    env = build_jinja_env(search_roots_for_includes)

    # Render main prompt
    prompt_template_rel = prompt_rel  # relative path usable by MultiRootLoader
    try:
        template = env.get_template(prompt_template_rel)
        variables = dict(variables)
        variables.setdefault("slot", slot)  # make slot name available in templates
        prompt_text = template.render(**variables)

        # NEW: auto-apply client defaults if present
        prompt_text = _apply_default_decorators(
            prompt_text=prompt_text,
            slot=slot,
            env=env,
            effective_tree=effective_tree,
        )
    except Exception as e:
        raise RenderError(f"Failed to render slot '{slot}': {e}") from e

    # Load extras (non-prompt files in the slot dir) from the *effective* view (overlayed)
    extras: Dict[str, str] = {}
    slot_dir_prefix = f"slots/{slot}/"
    for rel, data in effective_tree.items():
        if rel.startswith(slot_dir_prefix) and rel != prompt_rel:
            extras[rel.split("/")[-1]] = data.decode("utf-8", errors="ignore")

    lineage = dict(lineage_base)
    lineage.update(
        {
            "slot": slot,
            "prompt_sha256": sha256_bytes(prompt_text.encode("utf-8")),
            "extras_sha256": {
                k: sha256_bytes(v.encode("utf-8")) for k, v in extras.items()
            },
        }
    )

    return SlotMaterial(
        slot=slot, prompt_text=prompt_text, extras=extras, lineage=lineage
    )


# ---------- Public API


class PromptAssembler:
    def __init__(
        self,
        repo_root: str | pathlib.Path,
        component: str,  # "fm-app" | "db-meta" | "db-ref"
        client: Optional[str] = None,  # e.g., "acme-corp"
        env: Optional[str] = None,  # e.g., "prod"
        system_version: Optional[str] = None,
    ):
        self.repo_root = pathlib.Path(repo_root)
        self.component = component
        self.client = client
        self.env = env
        self.system_pack = find_system_pack(
            repo_root=self.repo_root,  # <-- just the prompts root
            component=component,
            version=system_version,  # None means latest
        )
        self.overlay_dirs: List[pathlib.Path] = []
        if client and env:
            ov = find_client_overlay(self.repo_root, client, env, component)
            if ov:
                self.overlay_dirs.append(ov)

        # Precompute effective tree & lineage
        roots_for_includes = [self.system_pack.root] + self.overlay_dirs
        self._include_roots = roots_for_includes
        self.tree = assemble_tree(self.system_pack.root, self.overlay_dirs)
        self.tree = _apply_default_slot_overrides(self.tree, self.overlay_dirs)

        def _write_effective_tree_to_tmp(
            effective_tree: dict[str, bytes],
        ) -> pathlib.Path:
            tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="prompt_pack_"))
            for rel, data in effective_tree.items():
                p = tmpdir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            return tmpdir

        self._merged_root = _write_effective_tree_to_tmp(self.tree)

        # 5) Set include roots — merged first
        self._include_roots = [
            self._merged_root,
            self.system_pack.root,
            *self.overlay_dirs,
        ]

        self.lineage_base = {
            "component": component,
            "system_pack": {
                "pack_name": self.system_pack.pack_name,
                "version": self.system_pack.version,
                "hash": self.system_pack.hash,
            },
            "overlays": [
                {"path": str(p), "hash": _dir_hash(p)} for p in self.overlay_dirs
            ],
        }

        self.async_mcp_registry = {}  # name -> async provider
        self._amcp_cache_vars = {}  # (name, slot, frozen_ctx) -> dict

    def register_async_mcp(self, provider):
        self.async_mcp_registry[provider.name] = provider

    def _slot_mcp_requirements(self, slot: str):
        slot_meta = (self.system_pack.manifest.get("slots", {}) or {}).get(
            slot, {}
        ) or {}
        reqs = slot_meta.get("requires", {}).get("mcp", []) or []
        # normalize: expect [{name, vars:[{key, tool}?], resources:[]?}]
        out = []
        for r in reqs:
            out.append(
                {
                    "name": r.get("name"),
                    "vars": r.get("vars", []),  # list of {key, tool?}
                    "resources": r.get("resources", []),
                }
            )
        return out

    def available_slots(self) -> List[str]:
        slots = set()
        for rel in self.tree.keys():
            m = re.match(r"^slots/([^/]+)/prompt\.md$", rel)
            if m:
                slots.add(m.group(1))
        return sorted(slots)

    def render(
        self,
        slot: str,
        variables: Dict[str, Any],
        mcp_caps: Optional[Dict[str, Any]] = None,
    ) -> SlotMaterial:
        merged_vars = dict(variables)
        if mcp_caps:
            merged_vars["capabilities"] = mcp_caps
        # Add a few common runtime vars
        # merged_vars.setdefault("today", os.getenv("PROMPT_TODAY") or "")
        return materialize_slot(
            component_root=self.system_pack.root,
            effective_tree=self.tree,
            slot=slot,
            search_roots_for_includes=self._include_roots,
            variables=merged_vars,
            lineage_base=self.lineage_base,
        )

    async def render_async(
        self,
        slot: str,
        variables: Dict[str, Any],
        req_ctx: Dict[str, Any],
        mcp_caps: Optional[Dict[str, Any]] = None,
    ):
        merged_vars = dict(variables)
        if mcp_caps:
            merged_vars["capabilities"] = mcp_caps
        # merged_vars.setdefault("today", os.getenv("PROMPT_TODAY") or "")

        # Fetch MCP vars declared in manifest
        mcp_lineage = []
        frozen_ctx = _freeze(copy.deepcopy(req_ctx))
        for need in self._slot_mcp_requirements(slot):
            name = need["name"]
            prov = self.async_mcp_registry.get(name)
            if not prov:
                continue  # or raise if strictly required

            cache_key = (name, slot, frozen_ctx)
            if cache_key in self._amcp_cache_vars:
                vars_from_mcp = self._amcp_cache_vars[cache_key]
            else:
                vars_from_mcp = await prov.vars_for_slot(slot, req_ctx)
                self._amcp_cache_vars[cache_key] = vars_from_mcp

            # If manifest lists specific keys, keep only those
            wanted_keys = [v["key"] if isinstance(v, dict) else v for v in need["vars"]]
            if wanted_keys:
                vars_from_mcp = {
                    k: vars_from_mcp.get(k) for k in wanted_keys if k in vars_from_mcp
                }

            merged_vars.update(vars_from_mcp)
            mcp_lineage.append(
                {
                    "provider": name,
                    "vars": sorted(vars_from_mcp.keys()),
                    "resources": [],
                }
            )

        # Render with existing sync machinery
        slot_mat = materialize_slot(
            component_root=self.system_pack.root,
            effective_tree=self.tree,
            slot=slot,
            search_roots_for_includes=self._include_roots,
            variables=merged_vars,
            lineage_base=self.lineage_base,
        )
        slot_mat.lineage["mcp"] = mcp_lineage
        return slot_mat


async def try_mcp(req: Dict[str, Any]) -> None:
    req_ctx = {
        "req": req,
        "flow_step_num": 1,
    }  # anything your provider needs
    _slot = await assembler.render_async(
        "planner",
        variables={
            "client_id": req.client_id,
            "task": req.request,
            # other vars...
        },
        req_ctx=req_ctx,
        mcp_caps={"sql_dialect": "clickhouse", "cost_tier": "standard"},
    )
    print(_slot.prompt_text)
    print(_slot.lineage.get("mcp"))


if __name__ == "__main__":

    # Initialize for fm-app with client overlays
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent.parent.parent  # adjust depth
    print(repo_root)
    assembler = PromptAssembler(
        repo_root=repo_root,  # containing /prompts and /client-configs
        component="fm_app",
        client="apegpt",
        env="prod",
        system_version=None,  # pick latest
    )

    # Register async MCP provider for db-meta
    # get standard logger from your app context

    # logger = structlog.get_logger(__name__)
    # assembler.register_async_mcp(DbMetaAsyncProvider(settings, logger))
    # in your async flow
    # req = {"client_id": "apegpt", "request": "What tables do you have?"}
    # asyncio.get_event_loop().run_until_complete(try_mcp(req))

    print("Slots:", assembler.available_slots())

    # Variables you inject at runtime

    planner_vars = {
        "client_id": "apegpt",
        "intent_hint": "",
        "query_metadata": "",
        "parent_query_metadata": "",
        "parent_session_id": "",
        "selected_row_data": "",
        "selected_column_data": "",
        "current_datetime": datetime.now().replace(microsecond=0),
    }

    # Capabilities coming from MCPs (db-meta/db-ref)
    db_meta_caps = {
        # "sql_dialect": "clickhouse",
        # "cost_tier": "standard",
        # "max_result_rows": 5000,
    }

    slot = assembler.render("planner", planner_vars, mcp_caps=db_meta_caps)

    print("--- PROMPT ---")
    print(slot.prompt_text)
    print("--- EXTRAS ---", list(slot.extras.keys()))
    print("--- LINEAGE ---", slot.lineage)
