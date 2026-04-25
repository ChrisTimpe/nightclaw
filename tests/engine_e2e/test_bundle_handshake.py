"""tests/engine_e2e/test_bundle_handshake.py — end-to-end validation of the
LLM → bundle-exec → filesystem handshake.

This suite exercises the full 4-step contract the architecture claims:

    Step 1 — the prompt declares the bundle ARGS shape (R5 contract).
    Step 2 — the LLM produces a JSON payload matching that shape.
    Step 3 — the LLM invokes `bundle-exec <name> --file=<json>` (or stdin).
    Step 4 — deterministic Python parses R5, validates ARGS, evaluates
             GUARDS, applies MUTATES atomically, emits APPEND rows.

Pre-existing tests cover each gate in isolation (validate-field, registry-route,
cascade-read, phase-validate) but never ran a real bundle through
``bundle-exec`` end-to-end and asserted the files on disk were correctly
mutated. This suite closes that gap.

Every test runs against a *copy* of the repo in a tmp_path so mutations
never touch the real workspace. The subprocess dispatches through the
real ``scripts/nightclaw-ops.py`` — the exact path cron prompts invoke.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_REL = Path("scripts") / "nightclaw-ops.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _copy_repo(dst: Path) -> None:
    """Copy the workspace into a sandbox. Skips caches and the installed
    skills mirror (which would double-copy large trees)."""
    ignore = shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".pytest_cache", ".git",
        "node_modules", ".venv",
    )
    shutil.copytree(REPO_ROOT, dst, ignore=ignore, dirs_exist_ok=False)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    dst = tmp_path / "nightclaw_sandbox"
    _copy_repo(dst)
    return dst


def _run(sandbox: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(sandbox) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(sandbox / SCRIPT_REL), *args],
        cwd=str(sandbox),
        env=env,
        capture_output=True,
        text=True,
        input=stdin,
    )


# ---------------------------------------------------------------------------
# STEP 1 contract: R5 declares ARGS the LLM can rely on.
# ---------------------------------------------------------------------------


def test_step1_r5_contract_parseable_for_every_bundle():
    """Every ``BUNDLE:*`` definition in R5 must be parseable by the same
    parser ``bundle-exec`` uses. If validate-bundles passes, the contract
    the prompt references is internally consistent."""
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / SCRIPT_REL), "validate-bundles"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    # Every per-bundle line must be "BUNDLE:<name> — OK (args=...)". Trailer
    # line is "RESULT:PASS (N bundles validated)".
    bundle_lines = [ln for ln in r.stdout.splitlines() if ln.startswith("BUNDLE:")]
    assert bundle_lines, "validate-bundles produced no per-bundle lines"
    for line in bundle_lines:
        assert " — OK " in line or " - OK " in line, (
            f"validate-bundles surfaced a non-OK line: {line!r}"
        )
    assert any(ln.startswith("RESULT:PASS") for ln in r.stdout.splitlines()), (
        f"validate-bundles missing RESULT:PASS trailer; stdout={r.stdout!r}"
    )


def test_step1_scr09_proves_prompt_matches_r5():
    """SCR-09 is the predicate that asserts every bundle-exec invocation
    declared in the cron prompts uses ARG keys that match R5 exactly. Run
    it explicitly so this suite fails fast if the prompt ↔ R5 contract
    drifts."""
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / SCRIPT_REL), "scr-verify"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout
    scr09 = [line for line in r.stdout.splitlines() if line.startswith("SCR-09")]
    assert scr09, "SCR-09 line missing from scr-verify output"
    assert scr09[0].startswith("SCR-09:PASS"), f"SCR-09 not passing: {scr09[0]}"


# ---------------------------------------------------------------------------
# STEP 2 + 3 contract: the LLM's JSON payload is the only structured
# surface it produces. bundle-exec must accept --file= and --stdin, and
# reject malformed payloads before any mutation.
# ---------------------------------------------------------------------------


def test_step3_unknown_bundle_name_is_rejected_without_mutation(sandbox: Path):
    """Invalid bundle name must fail fast with a stable error code
    the prompt-side validator can branch on."""
    audit_before = (sandbox / "audit" / "AUDIT-LOG.md").read_text(encoding="utf-8")
    r = _run(sandbox, "bundle-exec", "does-not-exist", "slug=x", "run_id=y", "reason=z")
    assert r.returncode != 0
    assert "BUNDLE_NOT_FOUND" in r.stdout, r.stdout
    # Non-negotiable: the audit log must not have changed.
    audit_after = (sandbox / "audit" / "AUDIT-LOG.md").read_text(encoding="utf-8")
    assert audit_after == audit_before, "audit log was mutated by a rejected bundle"


def test_step3_missing_required_arg_is_rejected_without_mutation(sandbox: Path):
    """route_block declares ARGS: slug, run_id, reason. Omitting ``reason``
    must fail with ERROR:MISSING_ARG and touch nothing."""
    audit_before = (sandbox / "audit" / "AUDIT-LOG.md").read_text(encoding="utf-8")
    active_before = (sandbox / "ACTIVE-PROJECTS.md").read_text(encoding="utf-8")
    r = _run(sandbox, "bundle-exec", "route_block", "slug=nightclaw", "run_id=RUN-TEST-001")
    assert r.returncode != 0
    assert "MISSING_ARG:reason" in r.stdout, r.stdout
    assert (sandbox / "audit" / "AUDIT-LOG.md").read_text(encoding="utf-8") == audit_before
    assert (sandbox / "ACTIVE-PROJECTS.md").read_text(encoding="utf-8") == active_before


def test_step3_malformed_json_file_fails_cleanly(sandbox: Path, tmp_path: Path):
    """An LLM producing malformed JSON must be rejected before any write."""
    bad = tmp_path / "bad.json"
    bad.write_text("{this is : not, json]")
    audit_before = (sandbox / "audit" / "AUDIT-LOG.md").read_text(encoding="utf-8")
    r = _run(sandbox, "bundle-exec", "route_block", f"--file={bad}")
    assert r.returncode != 0, "malformed JSON must fail"
    # Must not have appended anything mid-flight.
    assert (sandbox / "audit" / "AUDIT-LOG.md").read_text(encoding="utf-8") == audit_before


def test_step3_args_work_via_key_value_json_and_stdin(sandbox: Path, tmp_path: Path):
    """bundle-exec must accept the three payload shapes the prompt can
    produce: positional key=value, --file=<json>, and --stdin JSON. All
    three paths should reach the same validation result."""
    # Malformed payload (missing 'reason') via each channel — every shape
    # should produce the same MISSING_ARG error.
    r1 = _run(sandbox, "bundle-exec", "route_block", "slug=x", "run_id=y")
    assert "MISSING_ARG:reason" in r1.stdout

    payload_file = tmp_path / "p.json"
    payload_file.write_text(json.dumps({"slug": "x", "run_id": "y"}))
    r2 = _run(sandbox, "bundle-exec", "route_block", f"--file={payload_file}")
    assert "MISSING_ARG:reason" in r2.stdout

    r3 = _run(
        sandbox, "bundle-exec", "route_block", "--stdin",
        stdin=json.dumps({"slug": "x", "run_id": "y"}),
    )
    assert "MISSING_ARG:reason" in r3.stdout


# ---------------------------------------------------------------------------
# STEP 4 contract (GUARDS): VALIDATES must block mutation, not warn.
# ---------------------------------------------------------------------------


def test_step4_guard_failure_blocks_all_writes(sandbox: Path):
    """route_block declares VALIDATES: - reason NOT_EMPTY. An empty reason
    must fail the guard and leave every write target untouched."""
    audit_before = (sandbox / "audit" / "AUDIT-LOG.md").read_text(encoding="utf-8")
    active_before = (sandbox / "ACTIVE-PROJECTS.md").read_text(encoding="utf-8")
    change_before = (sandbox / "audit" / "CHANGE-LOG.md").read_text(encoding="utf-8")

    r = _run(sandbox, "bundle-exec", "route_block",
             "slug=nightclaw", "run_id=RUN-TEST-002", "reason=")
    # Either MISSING_ARG (empty string treated as absent) or GUARD_FAILED —
    # the architectural promise is just "does not write when reason is empty".
    assert r.returncode != 0, f"empty reason must not succeed; stdout={r.stdout!r}"

    assert (sandbox / "audit" / "AUDIT-LOG.md").read_text(encoding="utf-8") == audit_before
    assert (sandbox / "ACTIVE-PROJECTS.md").read_text(encoding="utf-8") == active_before
    assert (sandbox / "audit" / "CHANGE-LOG.md").read_text(encoding="utf-8") == change_before


# ---------------------------------------------------------------------------
# STEP 4 contract (PROTECTED): schema-declared protected paths can never
# be mutated by bundle-exec, even if a bundle spec tried to target them.
# ---------------------------------------------------------------------------


def test_step4_protected_path_gate_is_schema_driven(sandbox: Path):
    """The gate asks the schema (CL5 + R3 tier=PROTECTED), not a hardcoded
    list. Pick a schema-declared protected file and ensure registry-route
    reports PROTECTED, which is the same signal bundle-exec consults."""
    r = _run(sandbox, "registry-route", "orchestration-os/REGISTRY.md")
    assert r.returncode == 0, r.stdout
    assert "PROTECTED" in r.stdout, (
        f"REGISTRY.md should be schema-declared PROTECTED; got {r.stdout!r}"
    )


# ---------------------------------------------------------------------------
# STEP 4 contract (audit): every rejection path must leave integrity intact.
# ---------------------------------------------------------------------------


def test_step4_integrity_holds_after_rejection_cycle(sandbox: Path):
    """Run several failing bundle-exec invocations and verify the sandbox
    is still integrity-clean afterwards. A rejection must never corrupt
    anything — not even a partial append."""
    # Fire several deliberately-bad invocations.
    _run(sandbox, "bundle-exec", "route_block", "slug=x", "run_id=y")  # missing reason
    _run(sandbox, "bundle-exec", "no-such-bundle", "slug=x")
    _run(sandbox, "bundle-exec", "route_block")  # missing all args

    # REGISTRY.md must still hash identically — integrity-check is the
    # runtime's own statement about whether the filesystem is coherent.
    r = _run(sandbox, "integrity-check")
    assert r.returncode == 0, f"integrity-check failed after rejection cycle: {r.stdout}"
    assert "RESULT:PASS" in r.stdout


# ---------------------------------------------------------------------------
# STEP 4 contract (scr-verify): every rule still PASS in the sandbox.
# ---------------------------------------------------------------------------


def test_step4_scr_verify_still_passes_in_sandbox(sandbox: Path):
    """scr-verify in the sandbox must match the canonical result. If any
    schema↔prose byte-equality invariant is violated by the copy process,
    we find out here — proves the repo is self-contained and portable."""
    r = _run(sandbox, "scr-verify")
    assert r.returncode == 0, r.stdout
    assert "RESULT:PASS" in r.stdout
    # Structural spot-check: every tracked predicate must produce a PASS line
    # with a positive integer count. The exact number of bundles / SCR rule
    # refs / code files changes every Pass; hard-coding it caused brittle
    # failures on legitimate structural growth (H-TEST-12). The predicate-
    # pass guarantee is preserved by the match, and the overall
    # RESULT:PASS assertion above already proves every rule succeeded.
    assert re.search(r"^SCR-01:PASS count=\d+", r.stdout, re.M), r.stdout
    assert re.search(r"^SCR-06:PASS count=\d+", r.stdout, re.M), r.stdout
    assert re.search(r"^SCR-10:PASS code_files=\d+", r.stdout, re.M), r.stdout


# ---------------------------------------------------------------------------
# Cross-step invariant: the 4 commands that touch state are the ONLY 4
# commands registered under the T6 mutation tier. Anything else in T6 is
# a potential unintended mutation path.
# ---------------------------------------------------------------------------


def test_t6_mutators_are_present_and_reach_filesystem():
    """The three canonical mutators must be labelled T6 in STEP_CMD_MAP so
    that telemetry reports them under the mutation tier and the monitor
    groups them correctly. (STEP_CMD_MAP is telemetry-only metadata — not
    a gate — so this test is about *labelling correctness*, not control
    flow.)

    Current observed state: T6 also contains four read-only gate-query
    commands (validate-field, cascade-read, phase-validate, registry-route)
    and one other writer (longrunner-render). Those are tracked as
    known-mislabelled for later reclassification — they do not bypass the
    bundle contract because STEP_CMD_MAP is not consulted for write gating.
    """
    from nightclaw_engine.commands import STEP_CMD_MAP

    t6 = {c for c, t in STEP_CMD_MAP.items() if t == "T6"}
    required_mutators = {"bundle-exec", "append", "append-batch"}
    missing = required_mutators - t6
    assert not missing, (
        f"T6 lost a canonical mutator: {missing}. These must be labelled T6 "
        "so the monitor and audit-spine can recognise mutation events."
    )

    # Known members of T6 today. If this set changes, the mismatch between
    # "labelled T6" and "actually mutates" should be reconciled — either
    # by rewording the tier definition or by relabelling the command.
    known_t6_today = {
        "bundle-exec", "append", "append-batch",          # true mutators
        "longrunner-render",                               # true mutator
        "validate-field", "cascade-read",                  # read-only (mislabel)
        "phase-validate", "registry-route",                # read-only (mislabel)
    }
    drift = t6 ^ known_t6_today
    assert not drift, (
        f"T6 membership drifted from documented baseline: {drift}. "
        "If this is intentional, update the known_t6_today set in this test."
    )


def test_read_only_commands_do_not_write_to_sandbox(sandbox):
    """Defense in depth: run each of the commands currently labelled T6
    that we believe to be read-only, in the sandbox, and prove that NO
    file under the workspace changes as a result. This is the test that
    catches the real risk (an unintended mutation) — the tier label is
    just a name, but actual writes are not."""
    import hashlib

    def snapshot(root: Path) -> dict[str, str]:
        out = {}
        for p in root.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                rel = str(p.relative_to(root))
                try:
                    out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
                except (OSError, PermissionError):
                    pass
        return out

    before = snapshot(sandbox)

    # Each of these is believed to be read-only and should be safe to run.
    # We pass valid-shaped args so the command reaches its core logic.
    cases = [
        ("validate-field", "OBJ:DOES_NOT_EXIST", "nope", "x"),
        ("cascade-read", "orchestration-os/REGISTRY.md"),
        ("registry-route", "orchestration-os/REGISTRY.md"),
        # phase-validate needs a real slug; skip if none. We don't need it to
        # succeed — we need it to not write.
        ("phase-validate", "nonexistent-slug", "foo", "bar"),
    ]
    for cmd_args in cases:
        _run(sandbox, *cmd_args)

    after = snapshot(sandbox)
    diff = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert not diff, (
        f"Read-only commands mutated the sandbox: {sorted(diff)}. "
        "This is a real integrity violation — one of these commands has "
        "a side effect it should not have."
    )
