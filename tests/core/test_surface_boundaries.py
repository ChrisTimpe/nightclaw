"""tests/core/test_surface_boundaries.py — surface-1..5 boundary invariants.

These tests pin the architectural claims documented in internal_enhancement/ARCHITECTURE.md §0
("Surfaces") and CONTRIBUTING.md §"Monitor admin panel" / §"Monitor data-flow
SVG". Each one fails loudly if a future change blurs the boundary the
release-prep audit confirmed:

  * core engine never imports the bridge or the monitor packages
  * the bridge never imports the engine package directly
    (it shells out to scripts/nightclaw-{ops,admin}.{py,sh} instead)
  * cron prompts never reference LLM-BOOTSTRAP.yaml or the `bootstrap` command
  * the monitor's two step→nodes tables (parent + iframe) have the same keys

The HTML asserts are deliberately syntactic — they look for declared-name
prefixes only, not coordinates or coupling-by-coordinate. Pixel/coordinate
tests are explicitly out of scope.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _py_files_under(rel: str) -> list[Path]:
    base = REPO_ROOT / rel
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _imports_any(py_path: Path, forbidden_modules: tuple[str, ...]) -> list[str]:
    """Return the offending top-level module names found via import / from-import.

    Matches both ``import nightclaw_X`` and ``from nightclaw_X.…``. Does not
    walk strings or comments — only real Python import statements.
    """
    text = py_path.read_text(encoding="utf-8", errors="replace")
    hits: list[str] = []
    for mod in forbidden_modules:
        # Anchor at start-of-line (with optional leading whitespace) so we
        # don't match these names appearing inside docstrings or comments.
        # `import X[.…]` and `from X[.…] import …` are the two real forms.
        rx = re.compile(
            rf"^[ \t]*(?:from\s+{re.escape(mod)}(?:\.\S+)?\s+import\s|import\s+{re.escape(mod)}(?:\s|\.|$))",
            re.MULTILINE,
        )
        if rx.search(text):
            hits.append(mod)
    return hits


# ---------------------------------------------------------------------------
# Surface 1 (core engine) does not import surfaces 3 or 4
# ---------------------------------------------------------------------------

def test_engine_does_not_import_bridge_or_monitor():
    """Core engine code must not import nightclaw_bridge or nightclaw_monitor.

    The dependency direction is strictly engine ← bridge ← monitor (with
    nightclaw_ops as an optional, fail-open emitter on the engine side).
    Reversing it would mean the cron worker silently depends on the bridge
    being installed, which contradicts internal_enhancement/ARCHITECTURE.md §0 and the README's
    "Phase 1 minimal install" promise.
    """
    forbidden = ("nightclaw_bridge", "nightclaw_monitor")
    offenders: list[str] = []
    for py in _py_files_under("nightclaw_engine"):
        hits = _imports_any(py, forbidden)
        if hits:
            offenders.append(f"{py.relative_to(REPO_ROOT)}: imports {hits!r}")
    assert not offenders, (
        "engine ↛ bridge/monitor DAG violation:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Surface 3 (bridge) does not import surface 1 (engine) directly
# ---------------------------------------------------------------------------

def test_bridge_does_not_import_engine_package():
    """The bridge invokes engine functionality via subprocess only.

    It spawns scripts/nightclaw-ops.py and scripts/nightclaw-admin.sh. Direct
    Python imports of nightclaw_engine would couple the bridge to engine
    internals and undo the process-isolation property documented in
    nightclaw_bridge/runtime.py:1-9 and internal_enhancement/ARCHITECTURE.md §0.

    nightclaw_ops is allowed (the bridge consumes the ops socket protocol);
    only nightclaw_engine imports are forbidden.
    """
    offenders: list[str] = []
    for py in _py_files_under("nightclaw_bridge"):
        hits = _imports_any(py, ("nightclaw_engine",))
        if hits:
            offenders.append(f"{py.relative_to(REPO_ROOT)}: imports {hits!r}")
    assert not offenders, (
        "bridge ↛ engine DAG violation (use subprocess shell-out instead):\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Cron prompts never reference the bootstrap surface
# ---------------------------------------------------------------------------

def test_cron_prompts_do_not_reference_llm_bootstrap_yaml():
    """Surface 5 (LLM bootstrap) is for human/agent-dev orientation only.

    CRON-WORKER-PROMPT.md and CRON-MANAGER-PROMPT.md must never mention
    LLM-BOOTSTRAP.yaml or invoke `nightclaw-ops.py bootstrap` — those would
    convert a developer tool into an autonomous-runtime dependency. README.md
    and CONTRIBUTING.md both make this contract explicit.

    The word 'bootstrap' alone is fine — CRON-WORKER-PROMPT.md uses it as a
    plain noun for "starter objective." We only fail on the YAML filename or
    the `bootstrap` command invocation.
    """
    prompts = [
        REPO_ROOT / "orchestration-os" / "CRON-WORKER-PROMPT.md",
        REPO_ROOT / "orchestration-os" / "CRON-MANAGER-PROMPT.md",
    ]
    forbidden = (
        "LLM-BOOTSTRAP.yaml",
        "llm-bootstrap.yaml",
        "nightclaw-ops.py bootstrap",
        "bootstrap --track",
    )
    offenders: list[str] = []
    for p in prompts:
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{p.name}: contains {needle!r}")
    assert not offenders, (
        "Cron prompt references the LLM-BOOTSTRAP surface — that surface is "
        "agent-dev only:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Monitor SVG postMessage contract + step-map parity
# ---------------------------------------------------------------------------

def _extract_step_keys(text: str, table_name: str) -> set[str]:
    """Pull the keys of a JS object literal named ``table_name`` from HTML/JS.

    Looks for a declaration like ``const STEP_NODES = { startup: [...], T0: [...], ... };``
    and returns the set of left-hand identifiers. Bracket-balance walks past
    nested arrays so commas inside [...] don't confuse us.
    """
    m = re.search(
        rf"(?:const|let|var)\s+{re.escape(table_name)}\s*=\s*\{{",
        text,
    )
    if not m:
        return set()
    start = m.end()  # one char past the '{'
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = text[start:i]
    keys: set[str] = set()
    # Top-level keys are at depth 0 within the object body.
    depth_local = 0
    j = 0
    line_start = 0
    while j < len(body):
        c = body[j]
        if c in "([{":
            depth_local += 1
        elif c in ")]}":
            depth_local -= 1
        elif c == "," and depth_local == 0:
            chunk = body[line_start:j]
            km = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", chunk)
            if km:
                keys.add(km.group(1))
            line_start = j + 1
        j += 1
    chunk = body[line_start:]
    km = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", chunk)
    if km:
        keys.add(km.group(1))
    return keys


def test_monitor_step_node_maps_have_same_keys():
    """STEP_GRAPH_MAP (parent monitor) and STEP_NODES (data-flow iframe) must
    declare the same step keys.

    The iframe falls back to its own STEP_NODES table whenever the parent's
    postMessage omits the ``nodes`` array. If the keysets drift, a parent
    fallback for step T0 might find no entry in the iframe map and the SVG
    would silently render no highlight. Both files are hand-curated; this is
    the cheapest gate to keep them in sync.
    """
    monitor = (REPO_ROOT / "apps" / "monitor" / "nightclaw-monitor.html").read_text(
        encoding="utf-8"
    )
    dataflow = (REPO_ROOT / "apps" / "monitor" / "NightClaw-Data-Flow.html").read_text(
        encoding="utf-8"
    )
    parent_keys = _extract_step_keys(monitor, "STEP_GRAPH_MAP")
    iframe_keys = _extract_step_keys(dataflow, "STEP_NODES")
    assert parent_keys, "could not parse STEP_GRAPH_MAP from nightclaw-monitor.html"
    assert iframe_keys, "could not parse STEP_NODES from NightClaw-Data-Flow.html"
    assert parent_keys == iframe_keys, (
        "Parent STEP_GRAPH_MAP and iframe STEP_NODES drifted.\n"
        f"only in parent:  {sorted(parent_keys - iframe_keys)}\n"
        f"only in iframe:  {sorted(iframe_keys - parent_keys)}"
    )


def test_monitor_dataflow_iframe_postmessage_contract():
    """The data-flow iframe must accept exactly the documented postMessage
    types: ``nc-highlight`` and ``nc-theme``.

    This pins the contract documented in internal_enhancement/ARCHITECTURE.md §0 and the comment
    block at the top of NightClaw-Data-Flow.html. A new message type that
    enters here without a doc update would silently extend the bridge↔UI
    surface; conversely, removing one would break the parent's send paths.
    """
    text = (REPO_ROOT / "apps" / "monitor" / "NightClaw-Data-Flow.html").read_text(
        encoding="utf-8"
    )
    # The iframe's message handler must reference both literal type strings.
    assert "'nc-highlight'" in text or '"nc-highlight"' in text, (
        "data-flow iframe missing 'nc-highlight' postMessage handler"
    )
    assert "'nc-theme'" in text or '"nc-theme"' in text, (
        "data-flow iframe missing 'nc-theme' postMessage handler"
    )
    # Parent must send these and only these — match the type strings, not
    # full {type:'…'} blobs (formatting varies).
    parent = (REPO_ROOT / "apps" / "monitor" / "nightclaw-monitor.html").read_text(
        encoding="utf-8"
    )
    assert "nc-highlight" in parent, "parent monitor never sends nc-highlight"
    assert "nc-theme" in parent, "parent monitor never sends nc-theme"


# ---------------------------------------------------------------------------
# Bridge admin verb vocabulary stays a closed set
# ---------------------------------------------------------------------------

def test_bridge_admin_verb_vocabulary_is_a_closed_set():
    """ADMIN_CMD_RO and ADMIN_CMD_RW in nightclaw_bridge.runtime are the
    *only* verbs the monitor admin panel can issue.

    The release-prep audit confirmed that ``run_admin_command`` rejects
    anything outside ``ADMIN_CMD_RO | ADMIN_CMD_RW`` before any work happens.
    This test pins that the union is non-empty (nobody accidentally emptied
    the table) and that it still contains the canonical owner-CLI verbs the
    UI buttons rely on. A regression here would be a real security signal,
    not a stylistic one.
    """
    from nightclaw_bridge.runtime import (
        ADMIN_CMD_ALL,
        ADMIN_CMD_RO,
        ADMIN_CMD_RW,
    )

    # The union must equal ADMIN_CMD_ALL.
    assert ADMIN_CMD_ALL == ADMIN_CMD_RO | ADMIN_CMD_RW
    # RO and RW must be disjoint — a verb cannot be both.
    assert ADMIN_CMD_RO.isdisjoint(ADMIN_CMD_RW), (
        f"verbs in both RO and RW: {ADMIN_CMD_RO & ADMIN_CMD_RW!r}"
    )
    # Pin the canonical owner-CLI verbs exposed by scripts/nightclaw-admin.sh
    # so a refactor cannot silently drop them.
    canonical_rw = {"approve", "decline", "pause", "unpause", "guide",
                    "arm", "disarm", "priority", "done"}
    missing = canonical_rw - ADMIN_CMD_RW
    assert not missing, f"canonical RW verbs missing from ADMIN_CMD_RW: {missing!r}"
