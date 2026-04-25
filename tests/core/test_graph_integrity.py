"""tests/core/test_graph_integrity.py — R4 edge + R3 route invariants.

These tests encode the "isolated session retrieves complete context" product
claim as gates. They were added in the 2026-04-24 release-prep graph-integrity
review, after the engine-side normalizers in
``nightclaw_engine/engine/gates.py`` (note-stripping + glob expansion) landed.

Every edge endpoint in ``orchestration-os/schema/edges.yaml`` must resolve to
a known node — an R3 file (possibly via glob), an R1 object file, an R5
bundle, or an explicitly documented runtime marker (worker:/manager:/
browser:/agent:/socket/URL). A failing test means a new edge was added whose
endpoint is not queryable by any consumer of the registry — exactly the
silent false-negative class the normalizers were introduced to kill.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.engine import gates
from nightclaw_engine.schema.loader import load as load_schema


_NOTE_RE = re.compile(r"\s*\([^)]*\)\s*$")
_MARKER_PREFIX = ("worker:", "manager:", "browser:", "agent:")


def _strip_note(s: str) -> str:
    return _NOTE_RE.sub("", s).strip()


def _is_marker(s: str) -> bool:
    return s.startswith(_MARKER_PREFIX) or s.startswith("/tmp/") or s.startswith("ws:") or s.startswith("http")


@pytest.fixture(scope="module")
def model():
    return load_schema(REPO_ROOT / "orchestration-os" / "schema")


def _glob_has_disk_match(pattern: str) -> bool:
    """True if ``pattern`` (which may contain `*`) matches at least one file
    under the repo root. Used for glob endpoints that point at real on-disk
    directories like ``apps/monitor/*.html`` or ``PROJECTS/*/phases.yaml``.
    """
    if "*" not in pattern:
        return (REPO_ROOT / pattern).exists()
    # pathlib.Path.glob wants a pattern relative to a base — split off the
    # literal head so we anchor the glob correctly.
    try:
        return any(REPO_ROOT.glob(pattern))
    except Exception:
        return False


def _endpoint_resolves(model, endpoint: str) -> bool:
    """Is this edge endpoint queryable by at least one consumer of the graph?"""
    raw = endpoint.strip()
    if not raw:
        return False
    # BUNDLE:<name> must exist in R5.
    if raw.startswith("BUNDLE:"):
        return raw in {f"BUNDLE:{b.name}" for b in model.bundles}
    clean = _strip_note(raw)
    if _is_marker(clean):
        return True
    # An R3 route row (glob- or literal-matched) is the strongest signal the
    # path is a live workspace object.
    if gates.route_for(model, clean) is not None:
        return True
    # Files declared as R1 objects count — the glob/object-file convention
    # differs in a handful of places, so accept either notation. Match
    # directory-style object paths too (e.g. ``nightclaw_engine/`` or
    # ``apps/monitor/``) — a file-glob target like ``apps/monitor/*.html``
    # resolves to the ``apps/monitor/`` object.
    for obj in model.objects:
        obj_path = obj.file.replace("[slug]", "*").rstrip("/")
        if obj_path == clean.rstrip("/"):
            return True
        if obj_path.endswith("/") or "/" not in obj_path:
            continue
        # A glob endpoint whose parent directory is an R1 object counts.
        parent = clean.rsplit("/", 1)[0] if "/" in clean else ""
        if parent and parent == obj_path:
            return True
    # Glob endpoint that hits at least one file on disk also counts — this
    # covers ``orchestration-os/schema/*.yaml``, ``PROJECTS/*/phases.yaml``.
    if _glob_has_disk_match(clean):
        return True
    # Allow the handful of sub-symbol / composite endpoints that exist
    # specifically to carry extra runtime context (known-list whitelist).
    allow = {
        "scripts/nightclaw-ops.py:bundle-exec",  # REGISTRY reads bundle-exec sub-symbol
    }
    return clean in allow


def test_every_edge_endpoint_resolves(model):
    """Every edge endpoint must be queryable by some registry consumer."""
    offenders = []
    for e in model.edges:
        for label, val in (("source", e.source), ("target", e.target)):
            if not _endpoint_resolves(model, val):
                offenders.append(f"[{e.type}] {label}={val!r}  (src={e.source})")
    assert not offenders, (
        "Unresolvable edge endpoints (add R3 row, R1 object, R5 bundle, "
        "marker prefix, or on-disk file; or update the allowlist):\n  "
        + "\n  ".join(offenders)
    )


def test_edge_paren_notes_are_single_level(model):
    """Every endpoint, once note-stripped, must be paren-free.

    This guards against someone adding a nested-paren edge target that would
    slip past the single-level note stripper in gates._strip_note.
    """
    offenders = []
    for e in model.edges:
        for label, val in (("source", e.source), ("target", e.target)):
            stripped = _strip_note(val)
            if "(" in stripped or ")" in stripped:
                offenders.append(f"[{e.type}] {label}={val!r}")
    assert not offenders, (
        "Edge endpoints with non-trailing or nested parens — the note "
        "stripper handles one trailing `(...)` only:\n  "
        + "\n  ".join(offenders)
    )


def test_cascade_upstream_round_trip_on_glob_source(model):
    """Every glob-source edge must be reachable via a concrete expansion.

    This pins the fix for the cascade_for/cascade_upstream glob-expansion
    regression: a worker session holding a concrete slug path must receive
    the same outgoing edges as the glob source declares.
    """
    glob_edges = [e for e in model.edges if "*" in e.source]
    if not glob_edges:
        pytest.skip("no glob-source edges in baseline")
    # For each unique glob source, synthesize a concrete path and assert the
    # concrete query returns the same edges as the glob query.
    tested = set()
    for e in glob_edges:
        if e.source in tested:
            continue
        tested.add(e.source)
        glob_out = set(
            (ge.type, ge.target) for ge in gates.cascade_for(model, e.source)
        )
        concrete = e.source.replace("*", "round-trip-probe", 1)
        concrete_out = set(
            (ge.type, ge.target) for ge in gates.cascade_for(model, concrete)
        )
        assert glob_out == concrete_out, (
            f"round-trip mismatch for {e.source!r}: glob={glob_out} vs "
            f"concrete ({concrete!r})={concrete_out}"
        )


def test_registry_route_runtime_entrypoint(model):
    """scripts/nightclaw-ops.py must have a declared R3 tier.

    Regression: the runtime entrypoint used to return ROUTE:UNKNOWN. Any
    future removal of its routing row should fail loudly.
    """
    r = gates.route_for(model, "scripts/nightclaw-ops.py")
    assert r is not None, "scripts/nightclaw-ops.py must have an R3 row"
    assert r.tier.upper() == "STANDARD"
