"""tests/engine_e2e/test_engine_smoke.py — minimal end-to-end smoke for Merge 1.

Confirms the public engine surface stays intact after the package extraction:
  * ``nightclaw_engine`` exports ``COMMANDS`` + ``main``.
  * ``COMMANDS`` contains every pre-refactor command name plus the two new
    schema-* commands.
  * The thin ``scripts/nightclaw-ops.py`` dispatcher imports and runs without
    side effects at import time.
  * ``schema-render`` + ``schema-lint`` run as a subprocess pair and produce
    the documented machine-parseable output.

Intentionally NOT covered here (deferred to Merge 2 / dedicated suites):
  * Full bundle-exec round trip — covered by existing bridge/ops tests.
  * Registry replacement swap — not wired in Merge 1.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import nightclaw_engine


# --- Public package surface -------------------------------------------------


REQUIRED_LEGACY_COMMANDS = {
    "integrity-check",
    "next-run-id",
    "dispatch",
    "scan-notifications",
    "timing-check",
    "crash-detect",
    "transition-expiry",
    "change-detect",
    "audit-spine",
    "audit-anomalies",
    "prune-candidates",
    "scr-verify",
    "dispatch-validate",
    "longrunner-extract",
    "idle-triage",
    "strategic-context",
    "t7-dedup",
    "crash-context",
    "append",
    "append-batch",
    "bundle-exec",
    "validate-bundles",
}

NEW_MERGE1_COMMANDS = {"schema-render", "schema-lint"}
NEW_PASS10_COMMANDS = {"bootstrap"}


def test_engine_exports_commands_and_main():
    assert hasattr(nightclaw_engine, "COMMANDS")
    assert hasattr(nightclaw_engine, "main")
    assert callable(nightclaw_engine.main)


def test_engine_commands_are_callable():
    for name, fn in nightclaw_engine.COMMANDS.items():
        assert callable(fn), f"COMMANDS['{name}'] is not callable"


def test_all_legacy_commands_preserved():
    missing = REQUIRED_LEGACY_COMMANDS - set(nightclaw_engine.COMMANDS)
    assert not missing, f"missing legacy commands after extraction: {sorted(missing)}"


def test_merge1_schema_commands_present():
    missing = NEW_MERGE1_COMMANDS - set(nightclaw_engine.COMMANDS)
    assert not missing, f"missing Merge-1 schema commands: {sorted(missing)}"


def test_pass10_bootstrap_command_present():
    """Pass 10 registers the ``bootstrap`` command for LLM onboarding
    projection. It must live in COMMANDS + STEP_CMD_MAP so the dispatcher
    routes it and telemetry tags it (T0 — startup tier)."""
    from nightclaw_engine.commands import STEP_CMD_MAP
    missing = NEW_PASS10_COMMANDS - set(nightclaw_engine.COMMANDS)
    assert not missing, f"missing Pass 10 bootstrap command: {sorted(missing)}"
    assert STEP_CMD_MAP.get("bootstrap") == "T0", (
        "bootstrap must be labelled T0 (startup tier) in STEP_CMD_MAP"
    )


# --- Thin dispatcher sanity -------------------------------------------------


def _run_cli(args, cwd=REPO_ROOT):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "scripts/nightclaw-ops.py", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_dispatcher_help_lists_new_commands():
    proc = _run_cli(["--help"])
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "schema-render" in out
    assert "schema-lint" in out


def test_dispatcher_rejects_unknown_command():
    proc = _run_cli(["totally-not-a-command"])
    assert proc.returncode == 2
    assert "Unknown command" in proc.stderr


# --- schema-render / schema-lint end-to-end --------------------------------


def test_schema_render_then_lint_roundtrip(tmp_path: Path, monkeypatch):
    # Run inside the canonical repo tree — schema commands key off workspace_root.
    render = _run_cli(["schema-render"])
    assert render.returncode == 0, render.stderr
    assert render.stdout.startswith("SCHEMA-RENDER:OK:"), render.stdout

    # Fingerprint surfaces in the render output line.
    parts = render.stdout.strip().split(":")
    assert len(parts) >= 3
    fingerprint = parts[2]
    assert len(fingerprint) == 64

    # Immediately lint: should be byte-identical.
    lint = _run_cli(["schema-lint"])
    assert lint.returncode == 0, lint.stderr
    assert lint.stdout.startswith("SCHEMA-LINT:OK:"), lint.stdout
    assert fingerprint in lint.stdout


def test_schema_render_writes_generated_registry(tmp_path: Path):
    # Sandbox: schema-render writes REGISTRY.generated.md next to LOCK.md /
    # SOUL.md, which workspace_root() detects. Running in a tmp copy keeps
    # the working tree clean (H-TEST-04).
    sandbox = tmp_path / "nightclaw_sandbox"
    shutil.copytree(
        REPO_ROOT,
        sandbox,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", ".git",
            "node_modules", ".venv",
        ),
        dirs_exist_ok=False,
    )
    generated = sandbox / "REGISTRY.generated.md"
    # Remove any stale copy that survived the copytree so we assert a fresh
    # write, not an artefact.
    if generated.exists():
        generated.unlink()

    render = _run_cli(["schema-render"], cwd=sandbox)
    assert render.returncode == 0, render.stderr
    assert generated.exists(), "schema-render must write REGISTRY.generated.md"
    body = generated.read_text(encoding="utf-8")
    assert "<!-- nightclaw:render " in body
    assert body.rstrip().endswith("<!-- /nightclaw:render -->")
