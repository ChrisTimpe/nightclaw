"""tests/core/test_scr_predicates.py — protocol.integrity registry.

Confirms Merge 2's conversion of cmd_scr_verify to a predicate registry
driven by ``orchestration-os/schema/scr_rules.yaml``:

  * every predicate name declared in the YAML resolves in PREDICATE_REGISTRY
  * SCR-09 (``prompt_bundle_args_match_r5``) is present and executable
  * run_scr_verify produces the legacy output format (SCR-NN + CL5 + RESULT)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.protocol import integrity
from nightclaw_engine.schema.loader import load as load_schema


@pytest.fixture(scope="module")
def model():
    return load_schema(REPO_ROOT / "orchestration-os" / "schema")


def test_every_scr_rule_has_predicate(model):
    missing = [r.id for r in model.scr_rules
               if r.predicate not in integrity.PREDICATE_REGISTRY]
    assert missing == [], f"SCR rules lacking a predicate: {missing}"


def test_scr_09_predicate_present():
    assert "prompt_bundle_args_match_r5" in integrity.PREDICATE_REGISTRY


def test_scr_09_predicate_runs(model):
    pred = integrity.PREDICATE_REGISTRY["prompt_bundle_args_match_r5"]
    outs = pred(model, REPO_ROOT)
    assert outs, "predicate must emit at least one result row"
    for r in outs:
        assert r.status in ("PASS", "FAIL", "SKIP", "INFO")


def test_scr_09_passes_in_repo(model):
    """Pass 7 governance invariant: SCR-09 must PASS in the live repo.

    Pre-Pass-7 the predicate reported three false-positive FAILs from prose
    references to ``bundle-exec <name>`` and from ``--file=<json>`` invocations
    whose keys it could not parse. The Pass 7 fix requires a full CLI anchor
    (``Execute: python3 scripts/nightclaw-ops.py bundle-exec ...``) and reads
    JSON payload keys from the inline ``containing {...}`` hint.
    """
    pred = integrity.PREDICATE_REGISTRY["prompt_bundle_args_match_r5"]
    outs = pred(model, REPO_ROOT)
    failures = [r for r in outs if r.status == "FAIL"]
    assert not failures, f"SCR-09 failed: {[f.detail for f in failures]}"


def test_scr_02_passes_in_repo(model):
    """Pass 7 governance invariant: SCR-02 must PASS in the live repo.

    Pre-Pass-7 the predicate matched ``OBJ:RUN (when locked)`` as an OBJ name
    because the FK column was copied verbatim. Pass 7 extracts OBJ:NAME tokens
    with a strict regex so scope qualifiers do not leak into the FK set.
    """
    pred = integrity.PREDICATE_REGISTRY["r2_foreign_keys_resolve_to_r1"]
    outs = pred(model, REPO_ROOT)
    failures = [r for r in outs if r.status == "FAIL"]
    assert not failures, f"SCR-02 failed: {[f.detail for f in failures]}"


def test_scr_03_passes_in_repo(model):
    """Pass 7 governance invariant: SCR-03 must PASS in the live repo.

    Pre-Pass-7 the predicate compared R3 files verbatim (including scope
    qualifiers like ``REGISTRY.md(structural)``) against VALIDATES edges
    (which target bare paths). Pass 7 canonicalises both sides before
    set-compare.
    """
    pred = integrity.PREDICATE_REGISTRY["r3_protected_files_are_in_manifest"]
    outs = pred(model, REPO_ROOT)
    failures = [r for r in outs if r.status == "FAIL"]
    assert not failures, f"SCR-03 failed: {[f.detail for f in failures]}"


def test_scr_verify_all_rules_pass_in_repo(model):
    """Pass 7 exit-gate invariant: ``scr-verify`` must report RESULT:PASS.

    Before Pass 7 this test would fail on SCR-02, SCR-03, SCR-09 and CL5.
    After Pass 7 all ten SCR rules plus the CL5 cross-check must be green.
    Guards against regressions in any predicate or CL5 path canonicalisation.
    """
    report = integrity.run_scr_verify(model, REPO_ROOT)
    assert not report.failed, (
        f"scr-verify reports failures: {report.failed}\n"
        + "\n".join(report.lines)
    )


def test_run_scr_verify_emits_expected_shape(model):
    report = integrity.run_scr_verify(model, REPO_ROOT)
    joined = "\n".join(report.lines)
    # Legacy contract: every SCR id in yaml should appear in output.
    for rule in model.scr_rules:
        assert f"{rule.id}:" in joined, f"{rule.id} missing from output"
    # CL5 line always present.
    assert any(ln.startswith("CL5:") for ln in report.lines)
    # RESULT trailer always present.
    assert report.lines[-1].startswith("RESULT:")


def test_predicate_results_are_typed(model):
    # Each predicate must return a list of PredicateResult, not a mix of types.
    for name, pred in integrity.PREDICATE_REGISTRY.items():
        outs = pred(model, REPO_ROOT)
        assert isinstance(outs, list), f"{name} did not return a list"
        for r in outs:
            assert isinstance(r, integrity.PredicateResult)
            assert r.status in ("PASS", "FAIL", "SKIP", "INFO"), (name, r)


# --- SCR-10: code_files_have_r3_rows (Pass 5) --------------------------------


def test_scr_10_predicate_present():
    assert "code_files_have_r3_rows" in integrity.PREDICATE_REGISTRY


def test_scr_10_passes_in_repo(model):
    """Governance invariant: every .py file under the four code packages and
    every .html file under apps/monitor/ must have a CODE-tier row in R3.

    If this test fails, either a new code file was added without an R3 row,
    or an R3 row was added for a file that no longer exists on disk.
    """
    pred = integrity.PREDICATE_REGISTRY["code_files_have_r3_rows"]
    outs = pred(model, REPO_ROOT)
    assert outs, "SCR-10 returned no results"
    failures = [r for r in outs if r.status == "FAIL"]
    assert not failures, f"SCR-10 failed: {[f.detail for f in failures]}"
    assert any(r.status == "PASS" for r in outs), "SCR-10 produced no PASS row"


# --- SCR-11 / INV-13: r3_code_rows_exist_on_disk (Pass 13) -------------------


def test_scr_11_predicate_present():
    """INV-13: the predicate must be registered under its canonical name."""
    assert "r3_code_rows_exist_on_disk" in integrity.PREDICATE_REGISTRY


def test_scr_11_passes_in_repo(model):
    """Governance invariant (INV-13): every R3 route row at tier CODE must
    name a file that exists on disk.

    If this test fails: either a code file was renamed/moved without
    updating its R3 row in orchestration-os/schema/objects.yaml, or an
    R3 row was added for a file that was never created. Run
    ``python3 scripts/nightclaw-ops.py scr-verify`` to see which paths
    are missing.
    """
    pred = integrity.PREDICATE_REGISTRY["r3_code_rows_exist_on_disk"]
    outs = pred(model, REPO_ROOT)
    assert outs, "SCR-11 returned no results"
    failures = [r for r in outs if r.status == "FAIL"]
    assert not failures, (
        f"SCR-11 failed \u2014 R3 CODE rows reference files not on disk:\n"
        + "\n".join(f"  {r.detail}" for r in failures)
    )
    assert any(r.status == "PASS" for r in outs), "SCR-11 produced no PASS row"


def test_scr_11_flags_missing_file_synthetic(model):
    """Negative: inject a synthetic CODE route pointing at a non-existent
    file into a copy of the model and confirm the predicate FAILs. This
    guards the predicate itself against silent regressions where it always
    returns PASS regardless of input.
    """
    import copy
    import dataclasses

    fake_model = copy.copy(model)
    # Rebuild routes with one synthetic missing-file row appended.
    routes = list(model.routes)
    # Clone an existing CODE route so all required fields are populated,
    # then redirect its file to a guaranteed-missing path.
    seed = next(r for r in routes if r.tier.upper() == "CODE")
    bad = dataclasses.replace(
        seed,
        file="does/not/exist/__inv13_synthetic__.py",
    )
    fake_model = dataclasses.replace(model, routes=tuple(routes) + (bad,))

    pred = integrity.PREDICATE_REGISTRY["r3_code_rows_exist_on_disk"]
    outs = pred(fake_model, REPO_ROOT)
    assert any(r.status == "FAIL" for r in outs), (
        f"INV-13 predicate did not FAIL on a synthetic missing file: {outs!r}"
    )
    assert any(
        "__inv13_synthetic__" in r.detail for r in outs if r.status == "FAIL"
    ), f"FAIL detail missing the synthetic path: {outs!r}"
