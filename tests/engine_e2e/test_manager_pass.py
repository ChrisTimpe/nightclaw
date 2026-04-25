"""tests/engine_e2e/test_manager_pass.py — manager-tier command smoke.

Confirms the manager-side commands that got rewritten in Merge 2 still
behave correctly under the predicate/gate architecture:

  * scr-verify     -> predicate registry driver
  * dispatch-validate -> gates.validate_field per field
  * schema-render  -> unchanged from Merge 1
  * schema-lint    -> unchanged from Merge 1
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "nightclaw-ops.py"


def _run(*args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["NIGHTCLAW_WORKSPACE"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def test_scr_verify_prints_all_scr_ids():
    r = _run("scr-verify")
    for i in range(1, 10):
        assert f"SCR-0{i}:" in r.stdout, f"missing SCR-0{i}"


def test_dispatch_validate_runs():
    r = _run("dispatch-validate")
    # Whatever rows look like, the command must not crash or produce an
    # unexpected shape. VALID or VIOLATION lines + TOTAL_VIOLATIONS trailer.
    if r.returncode == 0:
        assert r.stdout.strip().endswith("VALID") or "SKIP" in r.stdout
    else:
        assert "TOTAL_VIOLATIONS:" in r.stdout


def test_schema_render_round_trip():
    r = _run("schema-render")
    assert r.returncode == 0
    assert r.stdout.startswith("SCHEMA-RENDER:OK:"), r.stdout
    # After render, schema-lint should confirm stability.
    r2 = _run("schema-lint")
    assert r2.returncode == 0
    assert "SCHEMA-LINT:OK:" in r2.stdout


def test_registry_markers_present():
    # Merge 2 inserted render markers for all machine-derived sections.
    text = (REPO_ROOT / "orchestration-os" / "REGISTRY.md").read_text(encoding="utf-8")
    for sid in ("R1", "R2", "R3", "R4", "R5", "R6", "CL5"):
        assert f'nightclaw:render section="{sid}"' in text, (
            f"missing render-open marker for {sid}"
        )
    # Doctrine sections preserved without render markers.
    for sid in ("R7", "CL1", "CL2", "CL3", "CL4", "CL6"):
        assert f'section="{sid}"' not in text, (
            f"doctrine section {sid} should not be render-wrapped"
        )
