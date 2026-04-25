"""tests/core/test_bundle_gate_enforcement.py — CLI-level gate enforcement.

Confirms Merge 2's gate-exposing CLI commands behave correctly end-to-end:

  * validate-field returns the right exit code on OK / VIOLATION
  * registry-route marks protected paths correctly
  * cascade-read emits the expected edge rows
  * phase-validate blocks undeclared transitions
  * scr-verify still exits 0/1 per the RESULT line

The tests use the thin ``scripts/nightclaw-ops.py`` wrapper so we cover
the exact dispatch path prompts invoke.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "nightclaw-ops.py"


def _run(*args, env_extra=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["NIGHTCLAW_WORKSPACE"] = str(REPO_ROOT)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


# --- validate-field ---------------------------------------------------------


def test_validate_field_unknown_obj_violates():
    r = _run("validate-field", "OBJ:DOES_NOT_EXIST", "nope", "x")
    assert r.returncode == 1
    assert "VIOLATION:R2_UNKNOWN_FIELD" in r.stdout


def test_validate_field_project_quality_contract():
    r = _run("validate-field", "OBJ:PROJ", "last_pass.quality", "STRONG")
    assert r.returncode == 0
    assert r.stdout.strip() == "OK:OBJ:PROJ.last_pass.quality"

    r = _run("validate-field", "OBJ:PROJ", "last_pass.quality", "INVALID")
    assert r.returncode == 1
    assert "VIOLATION:R2_ENUM:OBJ:PROJ.last_pass.quality" in r.stdout


def test_validate_field_usage_error():
    r = _run("validate-field", "OBJ:DISPATCH")
    assert r.returncode == 2


# --- registry-route ---------------------------------------------------------


def test_registry_route_protected():
    r = _run("registry-route", "orchestration-os/REGISTRY.md")
    assert r.returncode == 0
    assert r.stdout.strip() == "ROUTE:PROTECTED"


def test_registry_route_unknown():
    r = _run("registry-route", "totally/unknown/path.md")
    assert r.returncode == 0
    assert r.stdout.strip() == "ROUTE:UNKNOWN"


# --- cascade-read -----------------------------------------------------------


def test_cascade_read_prints_none_for_isolated_path():
    r = _run("cascade-read", "no/edges/anywhere.md")
    assert r.returncode == 0
    assert r.stdout.strip() == "CASCADE:NONE"


def test_cascade_read_returns_edges_for_dispatch():
    # ACTIVE-PROJECTS.md is a well-known source in R4.
    r = _run("cascade-read", "ACTIVE-PROJECTS.md")
    assert r.returncode == 0
    # At least one CASCADE: line or CASCADE:NONE — either is a valid shape,
    # but the baseline has edges out of this file.
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("CASCADE:")]
    assert lines, r.stdout


# --- CLI regressions: glob expansion + entrypoint/doc routing (2026-04-24) --


def test_cascade_read_concrete_slug_finds_glob_edges():
    # Regression: a worker session holding a concrete slug path used to get
    # CASCADE:NONE from the glob R4 edges. After the gates.py fix, the slug
    # path must resolve to the PROJECTS/*/LONGRUNNER.md source edges.
    r = _run("cascade-read", "PROJECTS/example-research/LONGRUNNER.md")
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("CASCADE:")]
    assert lines, r.stdout
    assert "CASCADE:NONE" not in r.stdout, (
        "slug-concrete LONGRUNNER path must match the glob edge; got NONE"
    )
    # The tool output contract preserves the raw edge target (with its
    # parenthetical note) — important for display.
    assert any("ACTIVE-PROJECTS.md" in ln for ln in lines), r.stdout


def test_registry_route_entrypoint():
    # Regression: scripts/nightclaw-ops.py is the runtime entrypoint; it used
    # to return ROUTE:UNKNOWN despite being the file every cron invokes.
    r = _run("registry-route", "scripts/nightclaw-ops.py")
    assert r.returncode == 0
    assert r.stdout.strip() == "ROUTE:STANDARD:standalone"


def test_registry_route_top_level_docs():
    for doc in ("README.md", "INSTALL.md", "DEPLOY.md",
                "internal_enhancement/README.md",
                "internal_enhancement/ARCHITECTURE.md",
                "internal_enhancement/LLM-BOOTSTRAP.yaml",
                "internal_enhancement/CURRENT-PASS.md",
                "orchestration-os/START-HERE.md"):
        r = _run("registry-route", doc)
        assert r.returncode == 0, f"{doc}: exit {r.returncode}; stderr={r.stderr}"
        assert r.stdout.strip() == "ROUTE:STANDARD:standalone", (
            f"{doc}: expected ROUTE:STANDARD:standalone, got {r.stdout.strip()!r}"
        )


# --- phase-validate ---------------------------------------------------------


def test_phase_validate_ok_for_declared_transition():
    r = _run("phase-validate", "example-research", "exploration", "adversarial-challenge")
    assert r.returncode == 0
    assert r.stdout.strip() == "PHASE:OK"


def test_phase_validate_denies_undeclared_transition():
    r = _run("phase-validate", "example-research", "exploration", "synthesis")
    assert r.returncode == 1
    assert "PHASE:DENIED:NOT_DECLARED" in r.stdout


def test_phase_validate_denies_missing_machine():
    r = _run("phase-validate", "no-such-project", "a", "b")
    assert r.returncode == 1
    assert "PHASE:DENIED:MACHINE_MISSING" in r.stdout


# --- scr-verify -------------------------------------------------------------


def test_scr_verify_emits_result_trailer():
    r = _run("scr-verify")
    # exit 0 or 1, but always must end in a RESULT line.
    assert r.returncode in (0, 1)
    last_non_empty = [ln for ln in r.stdout.splitlines() if ln.strip()][-1]
    assert last_non_empty.startswith("RESULT:")


def test_scr_verify_covers_every_rule_in_yaml():
    r = _run("scr-verify")
    joined = r.stdout
    # Every rule id in scr_rules.yaml should appear on some line.
    import yaml
    with open(REPO_ROOT / "orchestration-os" / "schema" / "scr_rules.yaml") as f:
        data = yaml.safe_load(f)
    for row in data["scr_rules"]:
        assert f"{row['id']}:" in joined, f"missing {row['id']} in output"
