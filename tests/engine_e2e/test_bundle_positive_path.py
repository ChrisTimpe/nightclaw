"""tests/engine_e2e/test_bundle_positive_path.py — Pass 9 positive-path
coverage for bundle-exec.

The Pass 8 handshake suite verified the four *negative* paths (unknown
bundle, missing arg, malformed JSON, guard failure) — all of which halt
before any write. The hot path (valid args + passing guards → actual
mutations + audit rows) was only exercised indirectly via telemetry
tests. Pass 9 closes that gap: this suite runs a real bundle through
``bundle-exec`` and asserts the observable filesystem effects.

Every test runs against a *copy* of the repo in tmp_path so production
state is never touched. The subprocess dispatches through the real
``scripts/nightclaw-ops.py`` — the exact path cron prompts invoke.
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


def _copy_repo(dst: Path) -> None:
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
# Positive path — route_block: simplest validates, predictable mutations.
# ---------------------------------------------------------------------------


def test_route_block_happy_path_writes_audit_row(sandbox: Path):
    """``route_block`` with all required args + passing guards must:

      1. Exit 0.
      2. Print ``RETURNS:SUCCESS`` then the completion line.
      3. Append an ``audit/AUDIT-LOG.md`` row matching the R5 template.

    This is the first test in the suite that asserts on successful
    side-effects — the Pass-8 handshake tests only asserted on
    failure-with-no-mutation.
    """
    audit_path = sandbox / "audit" / "AUDIT-LOG.md"
    audit_before = audit_path.read_text(encoding="utf-8")

    r = _run(
        sandbox, "bundle-exec", "route_block",
        "slug=nightclaw",
        "run_id=RUN-POSPATH-001",
        "reason=upstream tool unavailable",
    )

    assert r.returncode == 0, f"expected success; stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "RETURNS:SUCCESS" in r.stdout, r.stdout
    assert "BUNDLE:route_block completed" in r.stdout, r.stdout

    audit_after = audit_path.read_text(encoding="utf-8")
    assert len(audit_after) > len(audit_before), (
        "AUDIT-LOG.md must have grown. Before/after lengths: "
        f"{len(audit_before)}/{len(audit_after)}"
    )

    # The appended row must carry the run_id and bundle name per the R5
    # APPEND template: "TASK:{run_id}.T2 | TYPE:BUNDLE | BUNDLE:route_block | RESULT:BLOCKED"
    new_content = audit_after[len(audit_before):]
    assert "RUN-POSPATH-001" in new_content, new_content
    assert "BUNDLE:route_block" in new_content, new_content
    assert "RESULT:BLOCKED" in new_content, new_content


def test_route_block_returns_token_is_first_whitespace_token(sandbox: Path):
    """Regression guard for the pa_invoke-style ``RETURNS:`` truncation.

    Historical regex semantics were ``RETURNS:\\s*(\\S+)`` — the first
    whitespace-delimited token of the YAML ``returns`` field. Pass 9's
    ``spec_from_model`` must preserve that exactly, otherwise
    ``route_block`` stdout drifts and downstream prompts parse wrong.
    """
    r = _run(
        sandbox, "bundle-exec", "route_block",
        "slug=nightclaw", "run_id=RUN-POSPATH-002",
        "reason=token-check",
    )
    assert r.returncode == 0
    # Exactly the single-token form — no spaces, no pipe:
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RETURNS:")]
    assert lines == ["RETURNS:SUCCESS"], lines


def test_framework_new_bundle_flows_through_without_code_change(sandbox: Path, tmp_path: Path):
    """Framework-ready contract: adding a bundle to ``bundles.yaml`` must
    make it immediately executable via bundle-exec \u2014 no Python changes.

    This is the Pass 9 "dynamically capable framework" promise made
    executable. We synthesize a trivial audit-only bundle in the
    sandbox's bundles.yaml and verify ``bundle-exec`` resolves it and
    writes the audit row.
    """
    bundles_yaml = sandbox / "orchestration-os" / "schema" / "bundles.yaml"
    original = bundles_yaml.read_text(encoding="utf-8")

    # Append a synthetic bundle. YAML indentation matches the existing
    # "- name: ..." blocks in the file.
    synth = (
        "\n  - name: pass9_framework_probe\n"
        "    trigger: \"synthetic \u2014 pass9 framework probe\"\n"
        "    args: [run_id, note]\n"
        "    validates:\n"
        "      - \"note NOT_EMPTY\"\n"
        "    append:\n"
        "      \"audit/AUDIT-LOG.md\": \"TASK:{run_id}.T9 | TYPE:BUNDLE | BUNDLE:pass9_framework_probe | NOTE:{note}\"\n"
        "    returns: SUCCESS\n"
    )
    bundles_yaml.write_text(original + synth, encoding="utf-8")

    audit_path = sandbox / "audit" / "AUDIT-LOG.md"
    audit_before = audit_path.read_text(encoding="utf-8")

    r = _run(
        sandbox, "bundle-exec", "pass9_framework_probe",
        "run_id=RUN-FRAMEWORK-001",
        "note=hello",
    )
    assert r.returncode == 0, (
        f"Framework promise broken: adding a bundle to bundles.yaml did NOT "
        f"make it executable. stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    assert "RETURNS:SUCCESS" in r.stdout, r.stdout

    audit_after = audit_path.read_text(encoding="utf-8")
    new_content = audit_after[len(audit_before):]
    assert "pass9_framework_probe" in new_content, new_content
    assert "RUN-FRAMEWORK-001" in new_content, new_content
    assert "NOTE:hello" in new_content, new_content


def test_framework_new_bundle_guard_still_blocks(sandbox: Path):
    """Companion to the framework test: the guard on a newly-declared
    bundle must be evaluated and enforced, not just parsed. Prevents a
    regression where ``spec_from_model`` produces the spec but
    ``cmd_bundle_exec`` silently skips GUARDS for the new path.
    """
    bundles_yaml = sandbox / "orchestration-os" / "schema" / "bundles.yaml"
    original = bundles_yaml.read_text(encoding="utf-8")
    bundles_yaml.write_text(
        original
        + "\n  - name: pass9_guard_probe\n"
        + "    trigger: synthetic\n"
        + "    args: [run_id, note]\n"
        + "    validates:\n"
        + "      - \"note NOT_EMPTY\"\n"
        + "    append:\n"
        + "      \"audit/AUDIT-LOG.md\": \"TASK:{run_id}.T9 | TYPE:BUNDLE | BUNDLE:pass9_guard_probe\"\n"
        + "    returns: SUCCESS\n",
        encoding="utf-8",
    )

    audit_path = sandbox / "audit" / "AUDIT-LOG.md"
    audit_before = audit_path.read_text(encoding="utf-8")

    # Empty ``note`` must trip the NOT_EMPTY guard.
    r = _run(
        sandbox, "bundle-exec", "pass9_guard_probe",
        "run_id=RUN-GUARD-001", "note=",
    )
    assert r.returncode != 0, "empty-note guard must fail the bundle"
    assert "GUARD_FAILED" in r.stdout, r.stdout

    # And no audit row was written.
    assert audit_path.read_text(encoding="utf-8") == audit_before


# ---------------------------------------------------------------------------
# Positive path — phase_transition: exercises the R5 resolver's {NOW} and
# {NOW+field} COMPUTED placeholders. Regression guard against silent
# state-file corruption when the placeholder pattern fails to match and
# falls through to the LITERAL branch.
# ---------------------------------------------------------------------------


def _prime_phase_transition_sandbox(sandbox: Path, slug: str) -> None:
    """Inject the minimum state phase_transition's guards require:

      * a LONGRUNNER.md for ``slug`` with ``phase.status: active`` and a
        known ``transition_timeout_days`` (used by the ``{NOW+field}``
        resolver in bundle.py::resolve_expression);
      * a matching DISPATCH row in ACTIVE-PROJECTS.md so the
        ``DISPATCH:{slug}`` write target can locate the row it needs to
        mutate (status → TRANSITION-HOLD, escalation_pending → …).

    The example-research LONGRUNNER ships with
    ``transition_timeout_days: 3`` and ``phase.status: "active"`` — we
    reuse its shape by renaming to ``slug`` to avoid templating drift.
    """
    projects = sandbox / "PROJECTS"
    src = projects / "example-research"
    dst = projects / slug
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    # Inject a DISPATCH row for this slug. The mutate_dispatch_field path
    # requires the row to already exist — the bundle only *updates* it.
    active = sandbox / "ACTIVE-PROJECTS.md"
    text = active.read_text(encoding="utf-8")
    placeholder_row = "| \u2014 | _(no projects yet)_ | \u2014 | \u2014 | \u2014 | \u2014 | \u2014 |"
    new_row = (
        f"| 1 | {slug} | PROJECTS/{slug}/LONGRUNNER.md | exploration | "
        f"active | 2026-04-20T00:00:00Z | none |"
    )
    assert placeholder_row in text, "ACTIVE-PROJECTS.md placeholder row missing"
    active.write_text(text.replace(placeholder_row, new_row), encoding="utf-8")


def test_phase_transition_resolves_NOW_plus_field_to_iso_timestamp(sandbox: Path):
    """F1 regression — the ``phase_transition`` bundle writes
    ``transition_expires: {NOW+transition_timeout_days}``. Before Pass 3.2
    that placeholder was silently written **literally** into LONGRUNNER.md
    because:

      (a) ``bundle.py`` imported ``datetime, timezone`` but not
          ``timedelta``, so the resolver branch would NameError, and
      (b) the strict-mode regex ``^\\{(\\w+)\\}$`` rejected ``NOW+...``
          since ``\\w`` excludes ``+`` — so the code never reached the
          NameError; it fell through to the LITERAL branch.

    The test asserts the resolver actually substitutes an ISO-8601 UTC
    timestamp between 1 and 30 days from now (the bundle ships with
    ``transition_timeout_days: 3`` in the example project). A literal
    \"{NOW+transition_timeout_days}\" in the file is the failure mode.
    """
    slug = "f1-phase-transition-pos"
    _prime_phase_transition_sandbox(sandbox, slug)

    lr_path = sandbox / "PROJECTS" / slug / "LONGRUNNER.md"

    r = _run(
        sandbox, "bundle-exec", "phase_transition",
        f"slug={slug}",
        "run_id=RUN-F1-POS-001",
        "successor=adversarial-challenge",
        "escalation_text=stop_condition met; ready for phase advance",
        "action_text=review phase artifacts and approve transition",
    )

    assert r.returncode == 0, (
        f"bundle-exec phase_transition failed unexpectedly.\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    )
    assert "RETURNS:SUCCESS" in r.stdout, r.stdout

    lr_after = lr_path.read_text(encoding="utf-8")

    # The literal placeholder MUST NOT appear anywhere in the mutated
    # file. If it does, the R5 resolver regressed.
    assert "{NOW+transition_timeout_days}" not in lr_after, (
        "F1 regression: {NOW+transition_timeout_days} was written literally "
        "into LONGRUNNER.md. The R5 resolver's COMPUTED branch is broken."
    )
    assert "{NOW}" not in lr_after, (
        "R5 resolver failed to substitute {NOW}: placeholder still present."
    )

    # transition_expires must now be an ISO-8601 UTC timestamp.
    import re as _re
    m = _re.search(
        r'transition_expires:\s*"?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"?',
        lr_after,
    )
    assert m is not None, (
        f"transition_expires did not resolve to an ISO-8601 UTC timestamp.\n"
        f"LONGRUNNER tail:\n{lr_after[-800:]}"
    )

    # And the timestamp must be 3 days out (± a few minutes tolerance) —
    # matching the example LONGRUNNER's transition_timeout_days: 3.
    from datetime import datetime, timedelta, timezone
    got = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    expected = datetime.now(timezone.utc) + timedelta(days=3)
    delta = abs((got - expected).total_seconds())
    assert delta < 300, (  # 5-minute tolerance for test latency
        f"transition_expires drifted too far from NOW+3 days.\n"
        f"got={got!r}  expected≈{expected!r}  delta={delta}s"
    )


def test_phase_transition_also_sets_NOW_and_dispatch_status(sandbox: Path):
    """Companion assertion: ``{NOW}`` (no ``+``) already worked — this
    test nails it down so fixing the ``\\w+`` regex for NOW+ doesn't
    break the plain-NOW path. Also confirms the DISPATCH row flipped to
    TRANSITION-HOLD, which is the contract that unblocks the downstream
    transition-expiry monitor.
    """
    slug = "f1-phase-transition-companion"
    _prime_phase_transition_sandbox(sandbox, slug)

    r = _run(
        sandbox, "bundle-exec", "phase_transition",
        f"slug={slug}",
        "run_id=RUN-F1-POS-002",
        "successor=adversarial-challenge",
        "escalation_text=needs review",
        "action_text=review",
    )
    assert r.returncode == 0, f"stdout={r.stdout!r}  stderr={r.stderr!r}"

    lr = (sandbox / "PROJECTS" / slug / "LONGRUNNER.md").read_text(encoding="utf-8")
    assert "{NOW}" not in lr

    import re as _re
    assert _re.search(
        r'transition_triggered_at:\s*"?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"?',
        lr,
    ), f"transition_triggered_at did not resolve to an ISO timestamp.\n{lr[-600:]}"

    active = (sandbox / "ACTIVE-PROJECTS.md").read_text(encoding="utf-8")
    # The row we injected said status=active; after phase_transition it must
    # read TRANSITION-HOLD.
    row_line = next(
        (ln for ln in active.splitlines() if f"| {slug} |" in ln),
        None,
    )
    assert row_line is not None, "dispatch row for slug disappeared"
    assert "TRANSITION-HOLD" in row_line.upper(), (
        f"dispatch row did not flip to TRANSITION-HOLD: {row_line!r}"
    )


# ---------------------------------------------------------------------------
# Positive path — longrunner_update: the hot T6 path cron fires every pass.
# Exercises LONGRUNNER field writes with plain {NOW}/{TODAY} COMPUTED values
# plus ARG substitution; guards enums with IN comparison.
# ---------------------------------------------------------------------------


def test_longrunner_update_happy_path_mutates_lr_and_dispatch(sandbox: Path):
    """longrunner_update must:
      * write last_pass.* + next_pass.* fields into LONGRUNNER.md;
      * stamp DISPATCH row's last_worker_pass with an ISO NOW timestamp;
      * emit a SUCCESS audit row.
    No positive-path coverage existed for this bundle before Pass 3.2.
    """
    slug = "lr-update-pos"
    _prime_phase_transition_sandbox(sandbox, slug)

    audit_path = sandbox / "audit" / "AUDIT-LOG.md"
    audit_before = audit_path.read_text(encoding="utf-8")

    r = _run(
        sandbox, "bundle-exec", "longrunner_update",
        f"slug={slug}",
        "run_id=RUN-LRU-001",
        "quality=STRONG",
        "objective=Synthesize findings from 12 candidate tools",
        "output_files=PROJECTS/lr-update-pos/notes/discovery.md",
        "next_objective=Run adversarial challenge against top 3",
        "model_tier=standard",
        "context_budget=medium",
        "tools=web_search,fetch_url",
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "RETURNS:SUCCESS" in r.stdout, r.stdout

    lr = (sandbox / "PROJECTS" / slug / "LONGRUNNER.md").read_text(encoding="utf-8")
    # {TODAY} and {NOW} must both have resolved — no literal braces remain.
    assert "{TODAY}" not in lr and "{NOW}" not in lr
    # ARG substitution landed.
    assert "Synthesize findings from 12 candidate tools" in lr
    assert "Run adversarial challenge against top 3" in lr

    # DISPATCH row's last_worker_pass must be an ISO UTC timestamp.
    active = (sandbox / "ACTIVE-PROJECTS.md").read_text(encoding="utf-8")
    row_line = next(ln for ln in active.splitlines() if f"| {slug} |" in ln)
    import re as _re
    assert _re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', row_line), (
        f"last_worker_pass did not resolve: {row_line!r}"
    )

    # Audit row for the bundle run.
    audit_after = audit_path.read_text(encoding="utf-8")
    added = audit_after[len(audit_before):]
    assert "BUNDLE:longrunner_update" in added
    assert "RUN-LRU-001" in added
    assert "RESULT:SUCCESS" in added


def test_longrunner_update_rejects_invalid_quality_enum(sandbox: Path):
    """Guard ``quality IN STRONG,ADEQUATE,WEAK,FAIL`` must block a bogus
    value before any file is touched. Companion to the positive test so
    a regression that silently accepts garbage enums is caught.
    """
    slug = "lr-update-guard"
    _prime_phase_transition_sandbox(sandbox, slug)

    lr_before = (sandbox / "PROJECTS" / slug / "LONGRUNNER.md").read_text(encoding="utf-8")

    r = _run(
        sandbox, "bundle-exec", "longrunner_update",
        f"slug={slug}",
        "run_id=RUN-LRU-GUARD-001",
        "quality=EXCELLENT",  # not in STRONG,ADEQUATE,WEAK,FAIL
        "objective=test",
        "output_files=—",
        "next_objective=test",
        "model_tier=standard",
        "context_budget=medium",
        "tools=none",
    )
    assert r.returncode != 0, "bogus quality enum must fail the guard"
    assert "GUARD_FAILED" in r.stdout, r.stdout
    assert (sandbox / "PROJECTS" / slug / "LONGRUNNER.md").read_text(encoding="utf-8") == lr_before
