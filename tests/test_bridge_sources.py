"""Unit tests for nightclaw_bridge.sources — the read-only adapters that
surface repo governance/audit/notification state to the monitor UI.

Each parser is exercised with a tiny fixture file on disk so we verify
the actual IO path, not just regex behavior.
"""
from __future__ import annotations

import os

import pytest

from nightclaw_bridge import sources


# ---------------------------------------------------------------------------
# NOTIFICATIONS.md
# ---------------------------------------------------------------------------

def test_parse_notifications_extracts_active_alerts(tmp_path):
    path = tmp_path / "NOTIFICATIONS.md"
    path.write_text(
        "# NOTIFICATIONS.md\n"
        "<!-- header -->\n"
        "\n"
        "[2026-04-21 09:15] | Priority: HIGH | Project: example | Status: TRANSITION-HOLD\n"
        "Context: exploration phase complete. Artifact: outputs/a.md\n"
        "Action required: approve or pause\n"
        "\n"
        "[DONE 2026-04-20 23:59] [2026-04-20 23:00] | Priority: INFO | Project: x | Status: CLEAN\n"
        "Context: archived\n"
        "\n"
        "[2026-04-21 10:00] | Priority: INFO | Project: orch | Status: CLEAN\n"
        "Context: nothing to do\n",
        encoding="utf-8",
    )
    entries = sources.parse_notifications(str(path))
    # The resolved entry should be filtered out.
    assert len(entries) == 2
    a, b = entries
    assert a["priority"] == "HIGH"
    assert a["project"] == "example"
    assert a["status"] == "TRANSITION-HOLD"
    assert "exploration phase" in a["message"]
    assert a["ts"].startswith("2026-04-21T09:15")
    assert b["priority"] == "INFO"


def test_parse_notifications_missing_file_returns_empty(tmp_path):
    assert sources.parse_notifications(str(tmp_path / "nope.md")) == []


def test_has_pending_phase_transition():
    entries = [
        {"priority": "HIGH", "project": "x", "status": "TRANSITION-HOLD",
         "message": "phase complete", "ts": "t"},
        {"priority": "INFO", "project": "y", "status": "CLEAN",
         "message": "", "ts": "t"},
    ]
    pending = sources.has_pending_phase_transition(entries)
    assert len(pending) == 1 and pending[0]["project"] == "x"


# ---------------------------------------------------------------------------
# AUDIT-LOG.md
# ---------------------------------------------------------------------------

def test_parse_audit_tail_extracts_v19_compact(tmp_path):
    path = tmp_path / "AUDIT-LOG.md"
    path.write_text(
        "# AUDIT-LOG.md\n"
        "---\n"
        "TASK:RUN-20260421-001.T0 | TYPE:INTEGRITY_CHECK | RESULT:PASS | FILES:10\n"
        "TASK:RUN-20260421-001.T4.1 | TYPE:EXEC | AUTH:PA-001 | RESULT:SUCCESS | CMD:x\n"
        "TASK:RUN-20260421-001.T6 | TYPE:BUNDLE | BUNDLE:longrunner_update | FILE:PROJECTS/a/L.md | RESULT:FAIL\n",
        encoding="utf-8",
    )
    entries = sources.parse_audit_tail(str(path), count=10)
    assert len(entries) == 3
    assert entries[0]["severity"] == "ok"
    assert entries[0]["result"] == "PASS"
    assert entries[0]["type"] == "INTEGRITY_CHECK"
    assert entries[2]["severity"] == "err"
    assert entries[1]["ts"] == "2026-04-21T00:00:00Z"


def test_parse_audit_tail_handles_missing_file(tmp_path):
    assert sources.parse_audit_tail(str(tmp_path / "none.md")) == []


# ---------------------------------------------------------------------------
# CHANGE-LOG.md
# ---------------------------------------------------------------------------

def test_parse_change_log_splits_pipe_rows(tmp_path):
    path = tmp_path / "CHANGE-LOG.md"
    path.write_text(
        "# CHANGE-LOG.md\n"
        "---\n"
        "FILE:ACTIVE-PROJECTS.md#example.priority|1|2|worker|RUN-20260421-001|"
        "2026-04-21T10:00:00Z|2026-04-21T10:00:00Z|owner bumped priority|none\n"
        "FILE:PROJECTS/x/LONGRUNNER.md#phase.status|active|complete|worker|"
        "RUN-20260421-002|2026-04-21T12:00:00Z|2026-04-21T12:00:00Z|"
        "stop condition satisfied|longrunner_update\n",
        encoding="utf-8",
    )
    rows = sources.parse_change_log(str(path))
    assert len(rows) == 2
    assert rows[0]["file"] == "ACTIVE-PROJECTS.md"
    assert rows[0]["field"] == "example.priority"
    assert rows[0]["old_val"] == "1"
    assert rows[0]["new_val"] == "2"
    assert rows[1]["bundle"] == "longrunner_update"


# ---------------------------------------------------------------------------
# BUNDLE history scanning from AUDIT-LOG.md
# ---------------------------------------------------------------------------

def test_parse_bundle_history_finds_bundle_rows(tmp_path):
    path = tmp_path / "AUDIT-LOG.md"
    path.write_text(
        "TASK:RUN-20260421-003.T0 | TYPE:INTEGRITY_CHECK | RESULT:PASS\n"
        "TASK:RUN-20260421-003.T6 | TYPE:BUNDLE | BUNDLE:longrunner_update | "
        "FILE:PROJECTS/x/LONGRUNNER.md | RESULT:SUCCESS\n"
        "TASK:RUN-20260421-004.T6 | TYPE:BUNDLE | BUNDLE:notifications_append | "
        "FILE:NOTIFICATIONS.md | RESULT:FAIL\n",
        encoding="utf-8",
    )
    bundles = sources.parse_bundle_history(str(path))
    assert [b["bundle_name"] for b in bundles] == [
        "longrunner_update", "notifications_append"]
    assert bundles[0]["ok"] is True
    assert bundles[1]["ok"] is False
    assert bundles[0]["mutations_applied"] == ["PROJECTS/x/LONGRUNNER.md"]
    assert bundles[0]["run_id"] == "RUN-20260421-003"
    assert bundles[0]["ts"] == "2026-04-21T00:00:00Z"
    # guards_checked is intentionally empty in the v19 compact format.
    assert bundles[0]["guards_checked"] == []


# ---------------------------------------------------------------------------
# OPS-PREAPPROVAL.md
# ---------------------------------------------------------------------------

def test_parse_preapprovals_extracts_entries(tmp_path):
    path = tmp_path / "OPS-PREAPPROVAL.md"
    path.write_text(
        "# OPS-PREAPPROVAL.md\n"
        "## Active Pre-Approvals\n"
        "\n"
        "## PA-001 | Status: ACTIVE | Expires: 2026-05-01\n"
        "\n"
        "**Action class:** phase-auto-transition\n"
        "**Scope:** all projects\n"
        "**Condition:** stop_condition met\n"
        "**Boundary:** do not skip phases\n"
        "\n"
        "## PA-002 | Status: INACTIVE | Expires: —\n"
        "\n"
        "**Action class:** idle-cycle-autonomy\n"
        "**Scope:** PROJECTS/ + memory/\n"
        "**Condition:** all blocked\n"
        "**Boundary:** no external calls\n",
        encoding="utf-8",
    )
    entries = sources.parse_preapprovals(str(path))
    ids = [e["id"] for e in entries]
    assert "PA-001" in ids and "PA-002" in ids
    pa001 = next(e for e in entries if e["id"] == "PA-001")
    assert pa001["status"] == "ACTIVE"
    assert pa001["action_class"] == "phase-auto-transition"
    assert pa001["boundary"] == "do not skip phases"


# ---------------------------------------------------------------------------
# APPROVAL-CHAIN.md
# ---------------------------------------------------------------------------

def test_parse_approval_chain_extracts_invocations(tmp_path):
    path = tmp_path / "APPROVAL-CHAIN.md"
    path.write_text(
        "# APPROVAL-CHAIN.md\n"
        "## Invocation Log\n"
        "\n"
        "## [PA-001]-INVOCATION-[001] | 2026-04-21T10:05:00Z\n"
        "**Pre-approval:** PA-001\n"
        "**Invoked by:** session:worker run:RUN-20260421-001\n"
        "**Action authorized:** transition to TRANSITION-HOLD\n"
        "**Result:** SUCCESS\n",
        encoding="utf-8",
    )
    items = sources.parse_approval_chain(str(path))
    assert len(items) == 1
    assert items[0]["pa_id"] == "PA-001"
    assert items[0]["invocation"] == "001"
    assert "TRANSITION-HOLD" in items[0]["action"]
    assert items[0]["result"] == "SUCCESS"


# ---------------------------------------------------------------------------
# ACTIVE-PROJECTS.md
# ---------------------------------------------------------------------------

def test_parse_active_projects_reads_scoreboard(tmp_path):
    path = tmp_path / "ACTIVE-PROJECTS.md"
    path.write_text(
        "# ACTIVE-PROJECTS.md\n"
        "| Priority | Project Slug | LONGRUNNER Path | Phase | Status | Last Worker Pass | Escalation Pending |\n"
        "|----------|-------------|-----------------|-------|--------|-----------------|---------------------|\n"
        "| 1 | demo-a | PROJECTS/demo-a/LONGRUNNER.md | exploration | active | 2026-04-20 | none |\n"
        "| 2 | demo-b | PROJECTS/demo-b/LONGRUNNER.md | build | paused | 2026-04-18 | none |\n"
        "| — | _(no projects yet)_ | — | — | — | — | — |\n",
        encoding="utf-8",
    )
    rows = sources.parse_active_projects(str(path))
    assert [r["slug"] for r in rows] == ["demo-a", "demo-b"]
    assert rows[0]["phase"] == "exploration"
    assert rows[1]["status"] == "paused"


def test_parse_active_projects_empty_returns_empty(tmp_path):
    assert sources.parse_active_projects(str(tmp_path / "no.md")) == []


# ---------------------------------------------------------------------------
# SCR runner + longrunner-extract wrapper (uses the real ops script)
# ---------------------------------------------------------------------------

def test_run_scr_verify_against_real_repo(tmp_path):
    workspace = os.path.dirname(os.path.dirname(__file__))
    data = sources.run_scr_verify(workspace)
    # This exercises the live repo — SCR-01 must always be present when the
    # tool works at all.
    assert data is not None
    assert "SCR-01" in data["checks"]
    assert "passed" in data and "failed" in data
    assert data["event_type"] == "scr_verify_result"


def test_run_scr_verify_missing_script_returns_none(tmp_path):
    # An empty tmp dir has no ops.py → return None, do not fabricate.
    assert sources.run_scr_verify(str(tmp_path)) is None


def test_extract_longrunner_missing_script_returns_none(tmp_path):
    assert sources.extract_longrunner(str(tmp_path), "nope") is None


def test_extract_longrunner_real_project():
    workspace = os.path.dirname(os.path.dirname(__file__))
    # example-research ships with the repo.
    lr = sources.extract_longrunner(workspace, "example-research")
    assert lr is not None
    assert lr["phase_name"]
    assert lr["phase_status"]
    # routing must be parseable
    assert lr["routing"]


# ---------------------------------------------------------------------------
# Timestamp and helper micro-tests
# ---------------------------------------------------------------------------

def test_normalize_ts_variants():
    assert sources._normalize_ts("2026-04-21 09:00") == "2026-04-21T09:00:00Z"
    assert sources._normalize_ts("2026-04-21T09:00:30Z") == "2026-04-21T09:00:30Z"
    assert sources._normalize_ts("") == ""
    assert sources._normalize_ts("not-a-date") == "not-a-date"


def test_ts_from_run_id():
    assert sources._ts_from_run_id("RUN-20260421-001") == "2026-04-21T00:00:00Z"
    assert sources._ts_from_run_id("") == ""
    assert sources._ts_from_run_id("RUN-BAD") == ""
