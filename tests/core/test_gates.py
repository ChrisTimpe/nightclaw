"""tests/core/test_gates.py — Merge-2 gate primitives.

Covers the pure-function validators in ``nightclaw_engine.engine.gates``:
  * validate_field: R2 contract checks (REQ / TYPE / ENUM / UNKNOWN_FIELD)
  * route_for / is_protected / route_check: R3 + CL5 routing
  * cascade_for / cascade_upstream: R4 edge traversal
  * allowed_tool: phase tool-policy enforcement
  * summarise: fold GateResult sequence to audit-lines

All assertions use the live workspace schema under
``orchestration-os/schema/`` so we catch contract drift between gates and
data at test time.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.engine import gates
from nightclaw_engine.schema.loader import load as load_schema


@pytest.fixture(scope="module")
def model():
    return load_schema(REPO_ROOT / "orchestration-os" / "schema")


# --- validate_field ---------------------------------------------------------


def test_validate_field_unknown_returns_unknown_field(model):
    r = gates.validate_field(model, "OBJ:DOES_NOT_EXIST", "nope", "x")
    assert not r.ok
    assert r.code == "R2_UNKNOWN_FIELD"


def test_validate_field_required_empty_rejected(model):
    # Find any REQ=y field to exercise the required-empty path.
    required = [f for f in model.fields if f.req.lower() == "y"]
    assert required, "baseline expects at least one required field"
    spec = required[0]
    r = gates.validate_field(model, spec.obj, spec.field, "")
    assert not r.ok
    assert r.code == "R2_REQUIRED_EMPTY"


def test_validate_field_optional_empty_ok(model):
    optional = [f for f in model.fields if f.req.lower() != "y"]
    if not optional:
        pytest.skip("no optional fields in baseline")
    spec = optional[0]
    r = gates.validate_field(model, spec.obj, spec.field, "")
    assert r.ok, r.as_line()


def test_validate_field_enum_rejects_out_of_set(model):
    # Find an ENUM-typed field with a parseable enum list.
    for f in model.fields:
        if f.type.strip().upper() != "ENUM":
            continue
        enum = gates._parse_enum(f.constraint)
        if enum and len(enum) >= 2:
            good = enum[0]
            bad = good + "_NOT_IN_ENUM"
            assert gates.validate_field(model, f.obj, f.field, good).ok
            bad_res = gates.validate_field(model, f.obj, f.field, bad)
            assert not bad_res.ok
            assert bad_res.code == "R2_ENUM"
            return
    pytest.skip("no parseable enum fields in baseline")


def test_validate_field_type_hash_regex(model):
    for f in model.fields:
        if f.type.strip().upper() == "HASH":
            ok = gates.validate_field(model, f.obj, f.field, "a" * 64)
            bad = gates.validate_field(model, f.obj, f.field, "notahash")
            assert ok.ok, ok.as_line()
            assert not bad.ok
            assert bad.code == "R2_TYPE"
            return
    pytest.skip("no HASH-typed fields in baseline")


# --- route_for / is_protected -----------------------------------------------


def test_is_protected_registry_is_protected(model):
    assert gates.is_protected(model, "orchestration-os/REGISTRY.md")


def test_is_protected_unknown_path_not_protected(model):
    assert not gates.is_protected(model, "some/transient/notes.md")


def test_route_check_protected_blocks_write(model):
    r = gates.route_check(model, "orchestration-os/REGISTRY.md", "any_bundle")
    assert not r.ok
    assert r.code == "R3_PROTECTED"


def test_route_check_unknown_path_returns_route_unknown(model):
    r = gates.route_check(model, "totally/unknown/path.md", "any_bundle")
    assert not r.ok
    assert r.code == "R3_ROUTE_UNKNOWN"


# --- cascade_for / cascade_upstream -----------------------------------------


def test_cascade_for_returns_tuple(model):
    # Every source in an edge must come back from cascade_for(src).
    if not model.edges:
        pytest.skip("no R4 edges in baseline")
    edge = model.edges[0]
    out = gates.cascade_for(model, edge.source)
    assert any(e.target == edge.target and e.type == edge.type for e in out)


def test_cascade_upstream_returns_tuple(model):
    if not model.edges:
        pytest.skip("no R4 edges in baseline")
    edge = model.edges[0]
    out = gates.cascade_upstream(model, edge.target)
    assert any(e.source == edge.source and e.type == edge.type for e in out)


# --- endpoint normalization + glob expansion (regression: 2026-04-24) -------
# These pin the engine-side fix for silent false-negatives in cascade / route
# lookups described in the release-prep graph-integrity stress review. The
# fix strips a trailing parenthetical note from schema endpoint strings and
# treats "*" as a single-segment glob on the schema side of the compare.


def test_cascade_upstream_strips_paren_note_change_log(model):
    # edges.yaml declares:
    #   PROJECTS/*/LONGRUNNER.md  WRITES  audit/CHANGE-LOG.md (via T4)
    # A bare-name query used to miss it because of the trailing note.
    upstream = gates.cascade_upstream(model, "audit/CHANGE-LOG.md")
    sources = {e.source for e in upstream}
    assert "PROJECTS/*/LONGRUNNER.md" in sources, (
        "cascade_upstream(audit/CHANGE-LOG.md) must include the LONGRUNNER "
        "WRITES edge; got sources = " + ", ".join(sorted(sources))
    )


def test_cascade_upstream_strips_paren_note_soul(model):
    # edges.yaml declares:
    #   PROJECTS/*/LONGRUNNER-DRAFT.md  READS  SOUL.md (manager T3.5-A — domain anchor alignment check)
    upstream = gates.cascade_upstream(model, "SOUL.md")
    sources = {e.source for e in upstream}
    assert "PROJECTS/*/LONGRUNNER-DRAFT.md" in sources, (
        "cascade_upstream(SOUL.md) must include the LONGRUNNER-DRAFT READS "
        "edge; got sources = " + ", ".join(sorted(sources))
    )


def test_cascade_for_glob_expands_to_concrete_slug(model):
    # A worker session holding a concrete slug path must receive the same
    # outgoing edges as the schema glob source.
    out = gates.cascade_for(model, "PROJECTS/example-research/LONGRUNNER.md")
    assert out, "cascade_for on a concrete slug path must not return empty"
    # At least one downstream target must be ACTIVE-PROJECTS.md (one of the
    # declared WRITES from PROJECTS/*/LONGRUNNER.md, possibly note-suffixed).
    targets = [e.target for e in out]
    assert any(t.startswith("ACTIVE-PROJECTS.md") for t in targets), (
        "expected ACTIVE-PROJECTS.md in downstream targets; got " + repr(targets)
    )


def test_cascade_for_glob_does_not_cross_segments(model):
    # "PROJECTS/a/b/LONGRUNNER.md" has an extra segment — the "*" in
    # "PROJECTS/*/LONGRUNNER.md" must NOT cross the slash.
    out = gates.cascade_for(model, "PROJECTS/a/b/LONGRUNNER.md")
    # There should be no edge whose source is the glob form.
    assert not any(e.source.startswith("PROJECTS/*/LONGRUNNER.md") for e in out)


def test_route_for_glob_matches_concrete_slug(model):
    # registry-route must resolve a concrete slug to the glob R3 row.
    r = gates.route_for(model, "PROJECTS/example-research/LONGRUNNER.md")
    assert r is not None
    assert r.file == "PROJECTS/*/LONGRUNNER.md"
    assert r.tier.upper() == "STANDARD"


def test_route_for_does_not_overmatch_unrelated_path(model):
    # A path that shares no structure with any glob must still return None
    # (unchanged behaviour). Pick a deliberately unrouted path.
    assert gates.route_for(model, "some/unrouted/sandbox/thing.md") is None


def test_cascade_preserves_raw_target_string(model):
    # The fix is in the matcher, not in stored Edge fields: cmd_cascade_read
    # still prints the raw edge target (with its parenthetical note) so the
    # tool output contract is unchanged.
    out = gates.cascade_upstream(model, "audit/CHANGE-LOG.md")
    long_writer = [e for e in out if e.source == "PROJECTS/*/LONGRUNNER.md"]
    assert long_writer, "expected the LONGRUNNER writer edge"
    assert long_writer[0].target == "audit/CHANGE-LOG.md (via T4)", (
        "raw edge target must be preserved for display; got "
        + repr(long_writer[0].target)
    )


# --- allowed_tool + summarise ----------------------------------------------


def test_allowed_tool_empty_allowlist_is_ok():
    r = gates.allowed_tool([], "web_search")
    assert r.ok


def test_allowed_tool_denies_not_in_list():
    r = gates.allowed_tool(["file_system"], "web_search")
    assert not r.ok
    assert r.code == "C_TOOL_DENIED"


def test_summarise_folds_results():
    ok = gates.GateResult(True, "OK")
    bad = gates.GateResult(False, "R2_TYPE", "x.y")
    all_ok, lines = gates.summarise([ok, bad, ok])
    assert not all_ok
    assert any("VIOLATION:R2_TYPE" in ln for ln in lines)
    assert sum(1 for ln in lines if ln.startswith("OK")) == 2
