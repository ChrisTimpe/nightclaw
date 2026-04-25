"""tests/core/test_thesis_alignment.py — architectural invariants for Pass 8.

Pass 8 retired the _legacy.py shim and migrated SCR-01 + SCR-06 from
regex-over-rendered-prose to typed model queries, aligning the protocol
layer with the stated thesis:

    "Prose for everything the LLM reasons about. Tools for everything
     the runtime must guarantee."

These tests encode that alignment as a CI invariant so future edits cannot
silently reintroduce either the prose-regex data-access pattern or the
transitional back-compat shim.

The checks are static (file-contents inspection + import probes). They do
not execute any predicate, so they stay cheap and deterministic.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


ENGINE_DIR = REPO_ROOT / "nightclaw_engine"
PROTOCOL_DIR = ENGINE_DIR / "protocol"


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


# ---------------------------------------------------------------------------
# Invariant 1 — the _legacy.py shim is gone and nothing imports it.
# ---------------------------------------------------------------------------

# @invariant: ID=INV-01 | domain=legacy-shim | fails_on=_legacy.py file restored under nightclaw_engine/ | remediation=delete nightclaw_engine/_legacy.py; move any behaviour to nightclaw_engine/commands/
def test_legacy_shim_source_is_deleted():
    """Pass 8 removed nightclaw_engine/_legacy.py. It must not come back."""
    assert not (ENGINE_DIR / "_legacy.py").exists(), (
        "nightclaw_engine/_legacy.py was retired in Pass 8 — do not restore it. "
        "Downstream callers must import from nightclaw_engine or "
        "nightclaw_engine.commands directly."
    )


# @invariant: ID=INV-02 | domain=legacy-shim | fails_on=any repo .py imports nightclaw_engine._legacy | remediation=replace with 'from nightclaw_engine import commands' or direct imports from nightclaw_engine.commands.<module>
def test_no_module_imports_legacy_shim():
    """No file in the repo imports nightclaw_engine._legacy."""
    offenders: list[str] = []
    search_roots = [
        REPO_ROOT / "nightclaw_engine",
        REPO_ROOT / "scripts",
        REPO_ROOT / "tests",
        REPO_ROOT / "nightclaw_ops",
        REPO_ROOT / "nightclaw_bridge",
    ]
    for root in search_roots:
        if not root.exists():
            continue
        for path in _python_files(root):
            # Skip this very test file (it mentions the name in strings).
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            if "nightclaw_engine._legacy" in text or "from nightclaw_engine import _legacy" in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"These files still import the retired _legacy shim: {offenders}. "
        "Replace with 'from nightclaw_engine import commands' or direct "
        "imports from nightclaw_engine.commands.<module>."
    )


# ---------------------------------------------------------------------------
# Invariant 2 — no SCR predicate reads rendered prose via _registry_sections.
# ---------------------------------------------------------------------------

# @invariant: ID=INV-03 | domain=predicate/thesis | fails_on=an SCR predicate calls _registry_sections (regex over rendered REGISTRY.md prose) | remediation=refactor the predicate to traverse SchemaModel.routes / .edges / .bundles directly
def test_predicates_do_not_call_registry_sections():
    """SCR predicates must query the typed model, not regex over REGISTRY.md.

    _registry_sections() parses rendered prose; relying on it creates a
    drift hazard (schema YAML is the source of truth, REGISTRY.md is
    regenerated). Pass 8 migrated SCR-01 + SCR-06 off this helper. Keep it
    that way — new predicates should accept (model, root) and traverse the
    SchemaModel dataclasses directly.
    """
    integrity_src = (PROTOCOL_DIR / "integrity.py").read_text(encoding="utf-8")
    tree = ast.parse(integrity_src)

    predicate_funcs: list[ast.FunctionDef] = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("pred_")
    ]
    assert predicate_funcs, "expected pred_* functions in protocol/integrity.py"

    offenders: list[str] = []
    for fn in predicate_funcs:
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                func = sub.func
                name = (
                    func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name)
                    else None
                )
                if name == "_registry_sections":
                    offenders.append(fn.name)
                    break
    assert not offenders, (
        f"These predicates still call _registry_sections (prose-regex): "
        f"{offenders}. Query model.routes / model.edges / model.bundles "
        f"instead — that is the Pass 8 invariant."
    )


# ---------------------------------------------------------------------------
# Invariant 3 — every SCR predicate has the canonical (model, root) signature.
# ---------------------------------------------------------------------------

# @invariant: ID=INV-04 | domain=predicate/signature | fails_on=any pred_* function has signature other than (model, root, ...) | remediation=rename/re-order arguments to the canonical (model, root, ...) signature; update PREDICATE_REGISTRY if needed
def test_all_predicates_accept_model_and_root():
    """Predicate contract: pred_xxx(model: SchemaModel, root: Path) -> ...

    The typed model is the first argument so predicates can query structure
    without re-reading files. ``root`` stays available for the few cases
    that legitimately touch the filesystem (e.g., SCR-09 prompt prose,
    SCR-10 code-file existence).
    """
    from nightclaw_engine.protocol import integrity as _integrity  # noqa: F401

    integrity_src = (PROTOCOL_DIR / "integrity.py").read_text(encoding="utf-8")
    tree = ast.parse(integrity_src)

    bad: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("pred_"):
            continue
        arg_names = [a.arg for a in node.args.args]
        if arg_names[:2] != ["model", "root"]:
            bad.append(f"{node.name}({', '.join(arg_names)})")
    assert not bad, (
        f"Predicates must have signature (model, root, ...). Offenders: {bad}"
    )


# ---------------------------------------------------------------------------
# Invariant 4 — the public import surface still works.
# ---------------------------------------------------------------------------

# @invariant: ID=INV-05 | domain=public-api | fails_on=nightclaw_engine.COMMANDS or nightclaw_engine.main missing after import | remediation=ensure nightclaw_engine/__init__.py re-exports COMMANDS + main from nightclaw_engine.commands
def test_public_surface_imports_cleanly():
    """Removing _legacy must not break the documented import surface."""
    # Force a fresh import in case an earlier test cached a stale module.
    for mod in list(sys.modules):
        if mod == "nightclaw_engine" or mod.startswith("nightclaw_engine."):
            del sys.modules[mod]
    ne = importlib.import_module("nightclaw_engine")
    assert hasattr(ne, "COMMANDS"), "nightclaw_engine.COMMANDS must be re-exported"
    assert hasattr(ne, "main"), "nightclaw_engine.main must be re-exported"
    assert callable(ne.main)
    assert isinstance(ne.COMMANDS, dict) and ne.COMMANDS, "COMMANDS table must be non-empty"


# ---------------------------------------------------------------------------
# Invariant 5 (Pass 9) — bundle runtime reads the typed SchemaModel, not
# REGISTRY.md prose.
#
# Pass 9 migrated ``parse_r5_bundle()`` from regex-over-REGISTRY.md to
# ``spec_from_model()`` projecting ``SchemaModel.bundles``. The rendered
# REGISTRY.md is a *projection* of the YAML; the YAML is authoritative.
#
# These invariants ensure future edits cannot silently restore the
# prose-regex pattern in the hot path.
# ---------------------------------------------------------------------------


def _bundle_module_source() -> str:
    return (ENGINE_DIR / "commands" / "bundle.py").read_text(encoding="utf-8")


# @invariant: ID=INV-06 | domain=bundle/thesis | fails_on=any function other than _parse_r5_bundle_legacy reads orchestration-os/REGISTRY.md in commands/bundle.py | remediation=replace the read with spec_from_model(_load_schema_model(), bundle_name) so the runtime consumes the typed model, not the rendered projection
def test_pass9_bundle_exec_does_not_regex_registry_md():
    """``cmd_bundle_exec`` and the default ``parse_r5_bundle`` path must not
    call ``_shared.read_file("orchestration-os/REGISTRY.md")``.

    The legacy fallback ``_parse_r5_bundle_legacy`` is allowed one such call
    (it is retained for drift-audit only, reachable solely via
    ``NIGHTCLAW_BUNDLE_LEGACY_PARSER=1``). Any second call indicates a
    regression of the Pass 9 migration.
    """
    src = _bundle_module_source()
    tree = ast.parse(src)

    # Find all calls to _shared.read_file(...) whose argument is the literal
    # string "orchestration-os/REGISTRY.md".
    offenders: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # match _shared.read_file(...)
        if not (
            isinstance(fn, ast.Attribute)
            and fn.attr == "read_file"
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "_shared"
        ):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == "orchestration-os/REGISTRY.md":
            # Find enclosing function for the offender
            func = _enclosing_func(tree, node)
            offenders.append((func, node.lineno))

    # Legacy path gets exactly one allowance.
    legacy_hits = [o for o in offenders if o[0] == "_parse_r5_bundle_legacy"]
    other_hits = [o for o in offenders if o[0] != "_parse_r5_bundle_legacy"]

    assert len(legacy_hits) == 1, (
        f"_parse_r5_bundle_legacy must contain exactly one read of "
        f"REGISTRY.md (found {len(legacy_hits)})."
    )
    assert not other_hits, (
        "Pass 9 forbids regex-parsing REGISTRY.md in the bundle hot path. "
        f"Offending call sites: {other_hits}. Use spec_from_model(model, name) "
        "against SchemaModel.bundles instead."
    )


# @invariant: ID=INV-07 | domain=framework-contract | fails_on=spec_from_model or _load_schema_model removed from commands/bundle.py | remediation=restore the adapter functions; they are the framework contract any new bundle relies on (see test_bundle_positive_path.py)
def test_pass9_spec_from_model_exists_and_is_exported():
    """The migration guarantees a framework-ready adapter: any bundle in
    ``bundles.yaml`` must be executable via the typed model with no Python
    changes. That contract is embodied by ``spec_from_model(model, name)``.
    """
    src = _bundle_module_source()
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "spec_from_model" in names, (
        "spec_from_model(model, bundle_name) is the Pass 9 model adapter; "
        "removing it reintroduces single-implementation coupling."
    )
    assert "_load_schema_model" in names, (
        "_load_schema_model() is the cache-friendly loader used by both "
        "parse_r5_bundle and cmd_validate_bundles; do not inline it."
    )


# @invariant: ID=INV-08 | domain=bundle/thesis | fails_on=cmd_validate_bundles contains a re.{match,search,findall,finditer} whose pattern mentions 'BUNDLE:' | remediation=iterate model.bundles instead of regex-scanning REGISTRY.md
def test_pass9_validate_bundles_discovers_names_from_model():
    """``cmd_validate_bundles`` must source bundle names from
    ``model.bundles`` rather than regex-scanning REGISTRY.md line text.
    """
    src = _bundle_module_source()
    tree = ast.parse(src)

    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_validate_bundles":
            target = node
            break
    assert target is not None, "cmd_validate_bundles must exist"

    # Inspect the function body for any re.match/re.search/re.findall calls
    # whose pattern literal mentions 'BUNDLE:'.
    bad: list[int] = []
    for node in ast.walk(target):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (
            isinstance(fn, ast.Attribute)
            and fn.attr in {"match", "search", "findall", "finditer"}
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "re"
        ):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            pat = node.args[0].value
            if isinstance(pat, str) and "BUNDLE:" in pat:
                bad.append(node.lineno)
    assert not bad, (
        "cmd_validate_bundles must discover bundle names from model.bundles, "
        f"not by regex over REGISTRY.md text. Offending lines: {bad}"
    )


# ---------------------------------------------------------------------------
# Pass 9.1 — skills/ distribution parity invariant
# ---------------------------------------------------------------------------
#
# ``skills/nightclaw_engine/`` exists as a self-contained copy of the canonical
# engine for skill-bundle distribution. ``scripts/skills-sync.py`` produces it
# by verbatim copy from ``nightclaw_engine/``. If the two trees diverge, the
# packaged distribution silently ships stale code while the root runtime and
# its CI suite stay green — exactly the failure mode Pass 9.1 discovered for
# the Pass 9 migration (the skills/ bundle.py lacked spec_from_model until a
# manual sync was run).
#
# This invariant enforces byte-equality so skills-sync must be re-run as part
# of any engine edit, closing the drift loop.

import hashlib


def _tree_hash(root: Path) -> dict[str, str]:
    """Return {relative_path: sha256} for every .py file under ``root``,
    excluding __pycache__ / .pyc so the hash is deterministic across
    environments."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# @invariant: ID=INV-09 | domain=distribution/drift | fails_on=skills/nightclaw_engine/ has any .py that is missing, extra, or differs from the canonical nightclaw_engine/ | remediation=run 'python3 scripts/skills-sync.py' from the workspace root; never hand-edit files under skills/
def test_pass9_1_skills_engine_byte_matches_canonical():
    """``skills/nightclaw_engine/`` must be byte-identical to
    ``nightclaw_engine/``.

    Re-run ``python3 scripts/skills-sync.py`` from the workspace root to
    fix drift. Never hand-edit files under ``skills/`` — the canonical
    source lives in ``nightclaw_engine/``.
    """
    repo_root = Path(__file__).resolve().parents[2]
    canonical = repo_root / "nightclaw_engine"
    packaged = repo_root / "skills" / "nightclaw_engine"

    assert canonical.is_dir(), f"missing canonical engine at {canonical}"
    assert packaged.is_dir(), f"missing packaged engine at {packaged}"

    canonical_hashes = _tree_hash(canonical)
    packaged_hashes = _tree_hash(packaged)

    missing_in_packaged = sorted(set(canonical_hashes) - set(packaged_hashes))
    extra_in_packaged = sorted(set(packaged_hashes) - set(canonical_hashes))
    differing = sorted(
        rel for rel in canonical_hashes
        if rel in packaged_hashes
        and canonical_hashes[rel] != packaged_hashes[rel]
    )

    if missing_in_packaged or extra_in_packaged or differing:
        msg_lines = [
            "skills/nightclaw_engine/ has drifted from nightclaw_engine/.",
            "Run: python3 scripts/skills-sync.py",
            "",
        ]
        if missing_in_packaged:
            msg_lines.append(f"Missing in skills/ ({len(missing_in_packaged)}):")
            msg_lines.extend(f"  - {p}" for p in missing_in_packaged[:10])
        if extra_in_packaged:
            msg_lines.append(f"Extra in skills/ ({len(extra_in_packaged)}):")
            msg_lines.extend(f"  - {p}" for p in extra_in_packaged[:10])
        if differing:
            msg_lines.append(f"Differing contents ({len(differing)}):")
            msg_lines.extend(f"  - {p}" for p in differing[:10])
        pytest.fail("\n".join(msg_lines))


def _enclosing_func(tree: ast.AST, target: ast.AST) -> str:
    """Return the name of the innermost FunctionDef containing ``target``,
    or '<module>' if none."""
    # Walk the tree; for every FunctionDef, check if target is in its subtree.
    best_name = "<module>"
    best_depth = -1
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if sub is target:
                    # Count nesting depth by re-walking from module root.
                    depth = _depth_of(tree, node)
                    if depth > best_depth:
                        best_depth = depth
                        best_name = node.name
                    break
    return best_name


def _depth_of(tree: ast.AST, node: ast.AST, depth: int = 0) -> int:
    if tree is node:
        return depth
    for child in ast.iter_child_nodes(tree):
        r = _depth_of(child, node, depth + 1)
        if r >= 0:
            return r
    return -1
