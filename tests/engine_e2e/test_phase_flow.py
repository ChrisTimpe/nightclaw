"""tests/engine_e2e/test_phase_flow.py — phase machine + LONGRUNNER render flow.

Exercises the Tier C surface end-to-end:
  * phase-validate permits the first declared transition
  * phase-validate denies reverse and skip transitions
  * longrunner-render renders a machine card into LONGRUNNER.md
  * running longrunner-render twice is idempotent (byte-equality)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_REL = Path("scripts") / "nightclaw-ops.py"
SCRIPT = REPO_ROOT / SCRIPT_REL


def _run(*args, cwd: Path | None = None):
    """Invoke nightclaw-ops.py. ``cwd`` defaults to REPO_ROOT for tests that
    do not mutate the workspace; tests that render LONGRUNNER.md or otherwise
    write should pass a tmp sandbox ``cwd`` (see ``_sandbox`` below)."""
    base = cwd if cwd is not None else REPO_ROOT
    script = base / SCRIPT_REL
    env = os.environ.copy()
    env["PYTHONPATH"] = str(base) + os.pathsep + env.get("PYTHONPATH", "")
    env["NIGHTCLAW_WORKSPACE"] = str(base)
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(base),
        env=env,
        capture_output=True,
        text=True,
    )


def _sandbox(tmp_path: Path) -> Path:
    """Copy the repo into ``tmp_path`` so a test can write without touching
    the working tree (H-TEST-13). Skips the same caches test_bundle_handshake
    skips so we don't bloat the sandbox."""
    dst = tmp_path / "nightclaw_sandbox"
    shutil.copytree(
        REPO_ROOT,
        dst,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", ".git",
            "node_modules", ".venv",
        ),
        dirs_exist_ok=False,
    )
    return dst


def test_phase_forward_transition_ok():
    r = _run("phase-validate", "example-research", "exploration", "adversarial-challenge")
    assert r.returncode == 0
    assert r.stdout.strip() == "PHASE:OK"


def test_phase_backward_transition_denied():
    r = _run("phase-validate", "example-research", "adversarial-challenge", "exploration")
    assert r.returncode == 1
    assert "PHASE:DENIED:NOT_DECLARED" in r.stdout


def test_phase_skip_transition_denied():
    r = _run("phase-validate", "example-research", "exploration", "publication")
    assert r.returncode == 1
    assert "PHASE:DENIED:NOT_DECLARED" in r.stdout


def test_longrunner_render_is_idempotent(tmp_path: Path):
    # Run in a sandboxed copy of the repo so the real
    # PROJECTS/example-research/LONGRUNNER.md is never touched — previously
    # a SIGKILL during the test would leave the file mutated (H-TEST-13).
    sandbox = _sandbox(tmp_path)
    lr_path = sandbox / "PROJECTS" / "example-research" / "LONGRUNNER.md"

    r1 = _run("longrunner-render", "example-research", cwd=sandbox)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert "LONGRUNNER:OK:" in r1.stdout
    after_first = lr_path.read_text(encoding="utf-8")
    r2 = _run("longrunner-render", "example-research", cwd=sandbox)
    assert r2.returncode == 0
    after_second = lr_path.read_text(encoding="utf-8")
    # Two consecutive renders must produce byte-identical output.
    assert after_first == after_second
    # And the render must not lose the original doctrine content.
    assert "# LONGRUNNER" in after_first


def test_longrunner_render_rejects_missing_machine():
    r = _run("longrunner-render", "no-such-project")
    assert r.returncode == 1
    assert "LONGRUNNER:ERROR:machine_missing" in r.stdout
