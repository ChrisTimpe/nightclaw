"""nightclaw_bridge.runtime -- optional local runtime that serves the
shipped HTML monitor/sessions pages and exposes browser-facing WebSocket
endpoints backed by the existing ops-socket ingest path.

This module is explicitly opt-in: core nightclaw_engine / nightclaw_ops do
NOT import it, and the engine's emit_step path is indifferent to whether
the runtime is up. If no runtime is listening on the ops socket, ops
emissions are dropped by the transport layer (already true today) — so
adding this runtime cannot block or slow the core runtime.

Scope of the first slice:
  * Serve apps/monitor/*.html plus a tiny nc_config.json over HTTP.
  * Accept browser WebSocket connections on /ws (main monitor) and
    /sessions (sessions dashboard).
  * Translate canonical bridge payloads (opsstepevent) into the minimal
    HTML-facing event shapes the shipped pages already consume:
      - main /ws: connect_required / connect_ack / step / session_open /
        session_close / bridge_shutdown
      - /sessions: connect_required / connect_ack / sessions_snapshot
  * Expose a narrow allowlisted admin_command path that invokes
    scripts/nightclaw-admin.sh with guardrails. No shell interpolation;
    only positional args from a fixed vocabulary are forwarded.

Pieces intentionally deferred (noted in the slice summary):
  * SCR / bundle / notification / audit_tail events — core does not emit
    them through the ops socket today; we surface what ops does emit and
    leave those UI panes gracefully empty rather than faking data.
  * TLS / multi-user auth / remote access — local-only by contract.
  * Session-token rotation — accept any non-empty token as RW in local
    mode; reject /sessions RO-only violations; no expiry schedule.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import os
import time
import shutil
import subprocess
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Awaitable, Callable, Mapping, Optional

from .repository import MemorySessionRepository, FileSessionRepository
from .server import BridgeServer, start_ops_sink
from . import sources


# ----------------------------------------------------------------------------
# Session → step mapping. The main monitor HTML keys its step-list on
# {'INIT','T0'..'T9'}. The ops telemetry tier vocabulary is richer
# (T1.5, T2.5, T7a..d, etc.). We collapse half-steps to their parent tier
# so the existing UI keys remain lit. Raw tier is preserved elsewhere.
# ----------------------------------------------------------------------------

_TIER_TO_STEP = {
    "T0": "T0",
    "T1": "T1", "T1.5": "T1",
    "T2": "T2", "T2.5": "T2", "T2.7": "T2",
    "T3": "T3", "T3.5": "T3",
    "T4": "T4",
    "T5": "T5", "T5.5": "T5",
    "T6": "T6",
    "T7": "T7", "T7a": "T7", "T7b": "T7", "T7c": "T7", "T7d": "T7",
    "T8": "T8", "T8.3": "T8", "T8.5": "T8",
    "T9": "T9",
}


def _tier_to_step(tier: str) -> str:
    return _TIER_TO_STEP.get(tier, tier)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _notif_summary(n: Mapping[str, Any]) -> str:
    """Render a single-line notification summary suitable for the UI toast.

    Prefers the first line of the multi-line message body, falling back to
    the status / project chip.
    """
    msg = (n.get("message") or "").strip()
    if msg:
        first = msg.split(" | ", 1)[0].strip()
        if first:
            return first
    bits = []
    if n.get("priority"):
        bits.append(str(n["priority"]))
    if n.get("project"):
        bits.append(str(n["project"]))
    if n.get("status"):
        bits.append(str(n["status"]))
    return " • ".join(bits) if bits else "(notification)"


# ----------------------------------------------------------------------------
# Allowlisted admin commands.
#
# Each entry maps a UI command name to the invocation it triggers on the host.
# The UI ships these buttons: status, alerts, log, changes, approve, decline,
# pause, unpause, guide, arm, disarm, file_diff, crash_context.
#
#   * status/alerts/log/changes → scripts/nightclaw-admin.sh
#   * approve/decline/pause/unpause → scripts/nightclaw-admin.sh <cmd> <slug>
#   * guide → scripts/nightclaw-admin.sh guide "<message>"
#   * arm/disarm → scripts/nightclaw-admin.sh arm|disarm [PA-NNN]
#   * file_diff/crash_context → scripts/nightclaw-ops.py <cmd> ...
#
# Privilege: status/alerts/log/changes/file_diff/crash_context are RO-safe;
# approve/decline/pause/unpause/guide/arm/disarm require RW privilege (i.e.
# the client supplied a non-empty token). We do NOT ship a token file;
# operators set NIGHTCLAW_BRIDGE_TOKEN before starting the runtime. If it's
# unset, RW commands are refused with a clear error rather than silently
# running — safer default for a read-mostly local console.
# ----------------------------------------------------------------------------

ADMIN_CMD_RO = frozenset({
    "status", "alerts", "log", "changes", "file_diff", "crash_context",
    # New read-only surfaces for nontechnical users.
    "notifications", "notifications_pending", "audit",
    "preapprovals", "approval_chain",
    "scr", "phase", "active_projects",
    "diag_longrunner",
})
ADMIN_CMD_RW = frozenset({
    "approve", "decline", "pause", "unpause", "guide", "arm", "disarm",
    "priority", "done",
    "clear_notifications",
    "archive_project",
    "resign",
    "validate",
})
ADMIN_CMD_ALL = ADMIN_CMD_RO | ADMIN_CMD_RW


def _resolve_slug(rows: list) -> "str | None":
    """Pick the best slug from parsed ACTIVE-PROJECTS rows.

    Priority:
      1. First 'active' row (highest priority in table order)
      2. First 'blocked' row (still has live state worth showing)
      3. None — archived/unknown rows are skipped entirely
    """
    for status in ("active", "blocked"):
        for r in rows:
            if r.get("status", "").lower() == status:
                return r["slug"]
    return None


def _slug_ok(s: Any) -> bool:
    """Validate slug: matches bash validate_slug exactly.

    Pattern: ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$
    - lowercase alphanumeric and hyphens only
    - must start and end with alphanumeric (no leading/trailing dash)
    - max 64 chars
    Kept in sync with scripts/nightclaw-admin.sh::validate_slug so Python
    and bash agree on what constitutes a valid slug (NIST defense-in-depth).
    """
    import re as _re
    if not isinstance(s, str) or not s:
        return False
    if len(s) > 64:
        return False
    return bool(_re.fullmatch(r'[a-z0-9]([a-z0-9-]*[a-z0-9])?', s))


def _pa_ok(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    if len(s) > 16:
        return False
    return all(ch.isalnum() or ch == "-" for ch in s)


def _build_admin_argv(workspace: str, cmd: str, args: Mapping[str, Any]) -> Optional[list[str]]:
    """Return a safe argv for subprocess, or None if args are invalid.

    Never concatenates user input into a shell string; every element is a
    separate argv entry. No *args is passed to a shell.
    """
    admin_sh = os.path.join(workspace, "scripts", "nightclaw-admin.sh")
    ops_py = os.path.join(workspace, "scripts", "nightclaw-ops.py")

    if cmd == "status":
        return ["bash", admin_sh, "status"]
    if cmd == "alerts":
        return ["bash", admin_sh, "alerts"]
    if cmd == "log":
        count = args.get("count", 10)
        try:
            n = max(1, min(200, int(count)))
        except (TypeError, ValueError):
            n = 10
        return ["bash", admin_sh, "log", str(n)]
    if cmd == "changes":
        # nightclaw-admin.sh does not ship a `changes` verb; surface the
        # change log through a safe tail against audit/CHANGE-LOG.md.
        count = args.get("count", 20)
        try:
            n = max(1, min(500, int(count)))
        except (TypeError, ValueError):
            n = 20
        change_log = os.path.join(workspace, "audit", "CHANGE-LOG.md")
        return ["tail", "-n", str(n), change_log]
    if cmd in ("approve", "decline", "pause", "unpause"):
        slug = args.get("slug")
        if not _slug_ok(slug):
            return None
        argv = ["bash", admin_sh, cmd, slug]
        if cmd == "decline":
            reason = args.get("reason")
            if isinstance(reason, str) and reason and len(reason) <= 200:
                argv.append(reason)
        return argv
    if cmd == "guide":
        message = args.get("message")
        if not isinstance(message, str) or not message or len(message) > 400:
            return None
        return ["bash", admin_sh, "guide", message]
    if cmd == "arm":
        pa_id = args.get("pa_id")
        argv = ["bash", admin_sh, "arm"]
        if pa_id is not None:
            if not _pa_ok(pa_id):
                return None
            argv.append(pa_id)
        return argv
    if cmd == "disarm":
        pa_id = args.get("pa_id")
        argv = ["bash", admin_sh, "disarm"]
        if pa_id is not None:
            if not _pa_ok(pa_id):
                return None
            argv.append(pa_id)
        return argv
    if cmd == "file_diff":
        file_rel = args.get("file")
        run_id = args.get("run_id")
        if not isinstance(file_rel, str) or ".." in file_rel or file_rel.startswith("/"):
            return None
        # Best-effort: show the working-tree state of the requested file.
        # Diff-vs-prior-commit would require git; we keep this dependency-free.
        target = os.path.join(workspace, file_rel)
        if not os.path.isfile(target):
            return None
        return ["cat", target]
    if cmd == "crash_context":
        run_id = args.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            return None
        if not all(ch.isalnum() or ch in "-_" for ch in run_id) or len(run_id) > 64:
            return None
        return ["python3", ops_py, "crash-context", run_id]
    # ---- New RO surfaces (pure reads / existing ops.py subcommands) ------
    if cmd == "notifications":
        count = args.get("count", 40)
        try:
            n = max(1, min(500, int(count)))
        except (TypeError, ValueError):
            n = 40
        path = os.path.join(workspace, "NOTIFICATIONS.md")
        return ["tail", "-n", str(n), path]
    if cmd == "audit":
        count = args.get("count", 40)
        try:
            n = max(1, min(500, int(count)))
        except (TypeError, ValueError):
            n = 40
        path = os.path.join(workspace, "audit", "AUDIT-LOG.md")
        return ["tail", "-n", str(n), path]
    # "preapprovals", "approval_chain", "notifications_pending" are served
    # from the in-process parsers; no argv to build.
    if cmd == "scr":
        return ["python3", ops_py, "scr-verify"]
    if cmd == "phase":
        slug = args.get("slug")
        if not _slug_ok(slug):
            return None
        return ["python3", ops_py, "longrunner-extract", slug]
    if cmd == "active_projects":
        path = os.path.join(workspace, "ACTIVE-PROJECTS.md")
        return ["cat", path]
    if cmd == "diag_longrunner":
        # Diagnose why Project State panel is empty
        import subprocess as _sp
        lines = []
        ap_path = os.path.join(workspace, "ACTIVE-PROJECTS.md")
        lines.append(f"workspace: {workspace}")
        lines.append(f"ACTIVE-PROJECTS.md exists: {os.path.isfile(ap_path)}")
        try:
            rows = sources.parse_active_projects(ap_path)
            lines.append(f"active_projects rows: {len(rows)}")
            for r in rows[:3]:
                lines.append(f"  slug={r.get('slug')} status={r.get('status')}")
            slug = _resolve_slug(rows)
        except Exception as e:
            lines.append(f"parse_active_projects error: {e}")
            slug = None
        ops_py = os.path.join(workspace, "scripts", "nightclaw-ops.py")
        lines.append(f"nightclaw-ops.py exists: {os.path.isfile(ops_py)}")
        lines.append(f"resolved slug: {slug}")
        if slug and os.path.isfile(ops_py):
            try:
                p = _sp.run(["python3", ops_py, "longrunner-extract", slug],
                            cwd=workspace, capture_output=True, text=True, timeout=5)
                lines.append(f"longrunner-extract exit: {p.returncode}")
                lines.append(f"stdout: {(p.stdout or '').strip()[:300]}")
                if p.stderr: lines.append(f"stderr: {p.stderr.strip()[:200]}")
            except Exception as e:
                lines.append(f"longrunner-extract exception: {e}")
        return {"ok": True, "output": "\n".join(lines)}
    # ---- New RW admin verbs ----------------------------------------------
    if cmd == "priority":
        slug = args.get("slug")
        n = args.get("n") or args.get("priority")
        if not _slug_ok(slug):
            return None
        try:
            pr = int(n)
        except (TypeError, ValueError):
            return None
        if pr < 0 or pr > 9999:
            return None
        return ["bash", admin_sh, "priority", slug, str(pr)]
    if cmd == "done":
        line_num = args.get("line") or args.get("line_num")
        try:
            ln = int(line_num)
        except (TypeError, ValueError):
            return None
        if ln < 1 or ln > 100000:
            return None
        return ["bash", admin_sh, "done", str(ln)]
    return None


# ----------------------------------------------------------------------------
# Snapshot adapters — bridge canonical snapshot → HTML sessions payload.
# ----------------------------------------------------------------------------

def _state_replay_payload(repo, *, workspace: Optional[str] = None) -> dict:
    """Build the main monitor's initial state_replay payload from the event log.

    Shape keys match apps/monitor/nightclaw-monitor.html handleEvent():
      session (current), session_history[], step_history[], notifications[],
      change_log[], bundle_history[], scr_last, longrunner.

    When ``workspace`` is supplied, repo governance/audit files are read via
    nightclaw_bridge.sources to populate the additional panes; otherwise
    those panes stay honestly empty.
    """
    events = repo.load_events()
    sessions_by_run: dict[str, dict] = {}
    step_history: list[dict] = []
    current_run: Optional[str] = None
    current_session: Optional[dict] = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") != "opsstepevent":
            continue
        run = ev.get("run_id", "")
        if not run:
            continue
        tier = ev.get("tier", "")
        ts = ev.get("t_emitted", "")
        step = _tier_to_step(tier)
        step_history.append({
            "step": step,
            "tier": tier,
            "cmd": ev.get("cmd", ""),
            "ts": ts,
            "run_id": run,
        })
        if run not in sessions_by_run:
            sessions_by_run[run] = {
                "run_id": run,
                "agent_type": ev.get("session") or "worker",
                "outcome": "running",
                "ts": ts,
                "has_t0": False,
            }
        # Stamp project_slug from any step that carries it (T2+ dispatch may be first to know)
        if ev.get("slug") and not sessions_by_run[run].get("project_slug"):
            sessions_by_run[run]["project_slug"] = ev.get("slug")
        if tier == "T0":
            sessions_by_run[run]["has_t0"] = True
            sessions_by_run[run]["ts"] = ts  # use T0 ts as canonical session start
            if ev.get("slug"):  # stamp project_slug on session entry so UI can filter by project
                sessions_by_run[run]["project_slug"] = ev.get("slug")
            current_run = run
            current_session = {
                "run_id": run,
                "agent_type": ev.get("session") or "worker",
                "ts": ts,
                "project_slug": ev.get("slug"),
            }
        if tier == "T9":
            sessions_by_run[run]["outcome"] = (
                "clean" if ev.get("exit_code", 0) in (0, None) else "crash"
            )
            if current_run == run:
                current_run = None
                current_session = None

    # Only include the most recent run's step_history so the UI step-list
    # reflects the currently-visible session, matching session_open semantics.
    last_run_id = current_run
    if last_run_id is None and step_history:
        last_run_id = step_history[-1]["run_id"]
    if last_run_id:
        last_run_steps = [s for s in step_history if s["run_id"] == last_run_id]
    else:
        last_run_steps = []

    notifications: list[dict] = []
    change_log: list[dict] = []
    bundle_history: list[dict] = []
    longrunner: Optional[dict] = None
    scr_last: Optional[dict] = None
    if workspace:
        try:
            notifications = sources.parse_notifications(
                os.path.join(workspace, "NOTIFICATIONS.md"))
        except Exception:
            notifications = []
        try:
            change_log = sources.parse_change_log(
                os.path.join(workspace, "audit", "CHANGE-LOG.md"))
        except Exception:
            change_log = []
        try:
            bundle_history = sources.parse_bundle_history(
                os.path.join(workspace, "audit", "AUDIT-LOG.md"))
        except Exception:
            bundle_history = []
        # Try to resolve a phase snapshot for the currently visible session.
        slug = None
        if current_session and current_session.get("project_slug"):
            slug = current_session["project_slug"]
        else:
            try:
                rows = sources.parse_active_projects(
                    os.path.join(workspace, "ACTIVE-PROJECTS.md"))
                # active first, blocked second, archived skipped
                slug = _resolve_slug(rows)
            except Exception:
                slug = None
        if slug:
            try:
                longrunner = sources.extract_longrunner(workspace, slug)
            except Exception:
                longrunner = None

    # Include active_projects list so the monitor can populate slug dropdowns
    # without requiring the user to type slugs manually.
    try:
        _ap_rows = sources.parse_active_projects(
            os.path.join(workspace, "ACTIVE-PROJECTS.md"))
        active_projects_list = [
            {"slug": r["slug"], "status": r.get("status", ""), "priority": r.get("priority", "")}
            for r in _ap_rows
        ]
    except Exception:
        active_projects_list = []

    payload: dict[str, Any] = {
        "event_type": "state_replay",
        "session_history": list(sessions_by_run.values()),
        "step_history": last_run_steps,
        "notifications": notifications,
        "change_log": change_log,
        "bundle_history": bundle_history,
        "active_projects": active_projects_list,
    }
    if longrunner is not None:
        payload["longrunner"] = longrunner
    if scr_last is not None:
        payload["scr_last"] = scr_last
    if current_session is not None:
        payload["session"] = current_session
    return payload


# ----------------------------------------------------------------------------
# Project / session-replay payloads — additive read surfaces for the owner UI.
# Everything here is composed from existing sources.* parsers; no new event
# shapes are emitted, no state is persisted, and the signed schema fingerprint
# is unaffected. Both payloads are strict supersets of the live _state_replay
# envelope filtered down to a single project (or a single historical run),
# so the monitor's existing handleEvent() dispatch can render them unchanged.
# ----------------------------------------------------------------------------

_LR_FIELDS = (
    "phase.name", "phase.objective", "phase.stop_condition", "phase.status",
    "phase.successor",
    "next_pass.objective", "next_pass.model_tier", "next_pass.context_budget",
    "next_pass.tools_required",
    "last_pass.objective", "last_pass.output_files", "last_pass.date",
    "last_pass.validation_passed", "last_pass.weak_pass",
    "routing",
)


def _reconstruct_longrunner_at(workspace: Optional[str], slug: str,
                               run_id: str,
                               change_log: list[dict]) -> tuple[Optional[dict], bool]:
    """Return (longrunner_snapshot_at_run_end, exact) where exact=False means
    the reconstruction couldn't find enough change-log history to guarantee
    fidelity — the UI badges that case as "partial".

    Strategy: start from the current on-disk longrunner (authoritative now),
    then walk change_log rows *written after* run_id in reverse and undo each
    LONGRUNNER mutation (new_val -> old_val) to rewind to the state as of the
    target run's completion. If the workspace lacks scripts/nightclaw-ops.py
    we return (None, False); if no rows mutate longrunner fields after run_id
    we return (current, True) -- nothing has changed, current *is* the answer.
    """
    if not workspace:
        return None, False
    current = sources.extract_longrunner(workspace, slug)
    if current is None:
        return None, False
    # Collect mutations newer than the target run, touching a longrunner
    # field in a LONGRUNNER.md file for the requested slug.
    lr_file_marker = f"PROJECTS/{slug}/LONGRUNNER.md"
    newer: list[dict] = []
    saw_target_run = False
    for row in change_log:
        rid = row.get("run_id", "")
        fld = row.get("field", "")
        fpath = row.get("file", "")
        if rid == run_id:
            saw_target_run = True
            continue
        if not saw_target_run:
            # parse_change_log returns oldest-first; rows before the target
            # are already baked into current state, leave them alone.
            continue
        if lr_file_marker not in fpath:
            continue
        if fld not in _LR_FIELDS:
            continue
        newer.append(row)
    # If the target run_id never appears in the change-log at all, the run
    # either predates log retention or emitted no mutations. Be honest.
    if not saw_target_run and newer == []:
        return current, False
    # Rewind: apply new_val -> old_val in reverse chronological order.
    snap = dict(current)
    for row in reversed(newer):
        fld = row["field"]
        old = row.get("old_val", "")
        # Map dotted field to UI key the monitor consumes.
        ui_key = {
            "phase.name": "phase_name",
            "phase.objective": "phase_objective",
            "phase.stop_condition": "phase_stop",
            "phase.status": "phase_status",
            "phase.successor": "phase_successor",
            "next_pass.objective": "next_pass",
            "next_pass.model_tier": "next_tier",
            "next_pass.context_budget": "next_budget",
            "next_pass.tools_required": "next_tools",
            "last_pass.objective": "last_objective",
            "last_pass.output_files": "last_output",
            "last_pass.date": "last_date",
            "routing": "routing",
        }.get(fld)
        if ui_key is not None:
            snap[ui_key] = old
    return snap, True


def _project_snapshot_payload(repo, *, workspace: Optional[str],
                              slug: str) -> dict:
    """State-replay envelope filtered to one project slug.

    Reuses every parser the live /ws replay uses; just scopes the results so
    the owner UI can pin to a single project while the worker cron rotates
    across all of them. Shape keys are identical to _state_replay_payload so
    the monitor's handleEvent('state_replay', ...) path renders it verbatim.
    """
    # Start from the canonical envelope, then filter.
    envelope = _state_replay_payload(repo, workspace=workspace)
    envelope["event_type"] = "project_snapshot"
    envelope["project_slug"] = slug
    # Filter session_history to runs explicitly stamped with this project slug.
    # Runs with no project_slug are excluded — they belong to the unscoped view.
    envelope["session_history"] = [
        s for s in envelope.get("session_history", [])
        if (s.get("project_slug") or "") == slug
    ]
    # Collect the run_ids that belong to this project for downstream filters.
    project_run_ids = {s["run_id"] for s in envelope["session_history"] if s.get("run_id")}
    # step_history is scoped to the current run; only include when that run
    # belongs to this project.
    cur = envelope.get("session") or {}
    if cur.get("project_slug") and cur.get("project_slug") != slug:
        envelope["session"] = None
        envelope["step_history"] = []
    # Filter notifications by project tag (NOTIFICATIONS.md carries project).
    envelope["notifications"] = [
        n for n in envelope.get("notifications", [])
        if (n.get("project") or "") in ("", slug)
    ]
    # Filter change_log to rows whose file path mentions this project.
    # Re-parse with a higher count so older project entries aren't silently
    # dropped by the default-30 tail in _state_replay_payload.
    marker = f"PROJECTS/{slug}/"
    if workspace:
        try:
            change_log_full = sources.parse_change_log(
                os.path.join(workspace, "audit", "CHANGE-LOG.md"),
                count=200,
            )
        except Exception:
            change_log_full = envelope.get("change_log", [])
    else:
        change_log_full = envelope.get("change_log", [])
    envelope["change_log"] = [
        r for r in change_log_full
        if marker in (r.get("file") or "")
    ]
    # Filter bundle_history to bundles executed during this project's sessions.
    # Bundle entries carry run_id but not project_slug, so cross-reference.
    envelope["bundle_history"] = [
        b for b in envelope.get("bundle_history", [])
        if not b.get("run_id") or b["run_id"] in project_run_ids
    ]
    # Resolve longrunner for this slug even if the current session is elsewhere.
    if workspace:
        try:
            lr = sources.extract_longrunner(workspace, slug)
            if lr is not None:
                envelope["longrunner"] = lr
        except Exception:
            pass
    return envelope


def _session_replay_payload(repo, *, workspace: Optional[str],
                            run_id: str) -> dict:
    """State-replay envelope frozen at a historical run's completion.

    Packs step_history for the requested run plus reconstructed longrunner
    snapshot, scoped notifications/change_log/bundles. Flags 'partial' when
    longrunner reconstruction could not be guaranteed exact (see
    _reconstruct_longrunner_at) so the UI can badge the replay honestly.
    """
    events = repo.load_events()
    # Collect every step event for this run, in order of emission.
    steps: list[dict] = []
    slug = ""
    outcome = "running"
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") != "opsstepevent":
            continue
        if ev.get("run_id") != run_id:
            continue
        tier = ev.get("tier", "")
        step = _tier_to_step(tier)
        steps.append({
            "step": step,
            "tier": tier,
            "cmd": ev.get("cmd", ""),
            "ts": ev.get("t_emitted", ""),
            "run_id": run_id,
        })
        if not slug and ev.get("slug"):
            slug = ev.get("slug", "")
        if tier == "T9":
            outcome = ("clean" if ev.get("exit_code", 0) in (0, None)
                       else "crash")
    # Build the scoped supporting panes from existing parsers.
    notifications: list[dict] = []
    change_log: list[dict] = []
    bundle_history: list[dict] = []
    longrunner_snap: Optional[dict] = None
    partial = False
    if workspace:
        # Notifications are workspace-wide — always include full current list
        # so the monitor panel stays accurate regardless of which session is viewed.
        try:
            notifications = sources.parse_notifications(
                os.path.join(workspace, "NOTIFICATIONS.md"))
        except Exception:
            notifications = []
        try:
            change_log_full = sources.parse_change_log(
                os.path.join(workspace, "audit", "CHANGE-LOG.md"))
        except Exception:
            change_log_full = []
        change_log = [r for r in change_log_full if r.get("run_id") == run_id]
        try:
            bundle_full = sources.parse_bundle_history(
                os.path.join(workspace, "audit", "AUDIT-LOG.md"))
        except Exception:
            bundle_full = []
        bundle_history = [b for b in bundle_full if b.get("run_id") == run_id]
        # Notifications: NOTIFICATIONS.md has no run_id column. Window by the
        # run's [T0.ts, T9-or-last.ts] range and filter by project if known.
        if steps:
            t_lo = steps[0]["ts"]
            t_hi = steps[-1]["ts"]
            try:
                notif_full = sources.parse_notifications(
                    os.path.join(workspace, "NOTIFICATIONS.md"))
            except Exception:
                notif_full = []
            notifications = [
                n for n in notif_full
                if t_lo <= (n.get("ts") or "") <= t_hi
                and (not slug or (n.get("project") or "") in ("", slug))
            ]
        if slug:
            longrunner_snap, exact = _reconstruct_longrunner_at(
                workspace, slug, run_id, change_log_full)
            partial = not exact
    payload: dict[str, Any] = {
        "event_type": "session_replay",
        "run_id": run_id,
        "project_slug": slug,
        "outcome": outcome,
        "step_history": steps,
        "session": ({
            "run_id": run_id,
            "agent_type": "replay",
            "ts": steps[0]["ts"] if steps else "",
            "project_slug": slug,
        }),
        "session_history": [{
            "run_id": run_id,
            "agent_type": "replay",
            "outcome": outcome,
            "ts": steps[0]["ts"] if steps else "",
        }],
        "notifications": notifications,
        "change_log": change_log,
        "bundle_history": bundle_history,
        "partial": partial,
    }
    if longrunner_snap is not None:
        payload["longrunner"] = longrunner_snap
    return payload


def _sessions_snapshot_payload(repo, *, bridge_port: int,
                               workspace: Optional[str] = None,
                               scr_last: Optional[dict] = None) -> dict:
    """Build the sessions page payload from the canonical event log.

    Shape keys match apps/monitor/nightclaw-sessions.html:
      sessions[], step_times{}, scrlast, bridgeport
    """
    events = repo.load_events()
    sessions: list[dict] = []
    step_times: dict[str, list[str]] = {}
    seen_runs: dict[str, dict] = {}
    has_t0: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):  # guard against malformed lines (e.g. bare [] in sessions.json)
            continue
        run = ev.get("run_id")
        if not run:
            continue
        if ev.get("type") == "opsstepevent":
            step_times.setdefault(run, []).append(ev.get("t_emitted", ""))
            tier = ev.get("tier", "")
            if tier == "T0":
                has_t0.add(run)
                # Use T0 timestamp as canonical session start
                if run not in seen_runs:
                    seen_runs[run] = {
                        "runid": run,
                        "agenttype": ev.get("session") or "worker",
                        "outcome": "running",
                        "mutationcount": 0,
                        "ts": ev.get("t_emitted", ""),
                    }
                else:
                    seen_runs[run]["ts"] = ev.get("t_emitted", "")
            if run not in seen_runs:
                seen_runs[run] = {
                    "runid": run,
                    "agenttype": ev.get("session") or "worker",
                    "outcome": "running",
                    "mutationcount": 0,
                    "ts": ev.get("t_emitted", ""),
                }
            # T9 marks session-close → outcome=clean unless exit_code!=0 seen
            if tier == "T9":
                seen_runs[run]["outcome"] = (
                    "clean" if ev.get("exit_code", 0) in (0, None) else "crash"
                )
    # Only surface sessions that:
    #   1. Had a confirmed T0 (real session open — not a bridge polling artifact).
    #   2. Have a RUN- prefixed run_id (cron worker/manager registry-backed IDs).
    # CLI- prefixed IDs are ad-hoc nightclaw-ops invocations — they may emit T0
    # (e.g. lock-acquire, crash-detect) but are not worker/manager sessions.
    # nightclaw-ops.py documents this split explicitly:
    #   "Format deliberately distinct from the registry-backed RUN-YYYYMMDD-NNN"
    for run_id, row in seen_runs.items():
        if run_id in has_t0 and run_id.startswith("RUN-"):
            sessions.append(row)

    return {
        "event_type": "sessions_snapshot",
        "type": "sessions_snapshot",
        "sessions": sessions,
        "step_times": step_times,
        "scrlast": scr_last,
        "bridgeport": bridge_port,
        "t_emitted": _now_iso(),
    }


# ----------------------------------------------------------------------------
# HTTP static server (asyncio, no framework).
# ----------------------------------------------------------------------------

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
}


async def _http_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                        *, docroot: str, bridge_port: int) -> None:
    try:
        line = await reader.readline()
        if not line:
            return
        try:
            method, path, _ = line.decode("iso-8859-1").split(" ", 2)
        except ValueError:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return
        # drain headers
        while True:
            h = await reader.readline()
            if h in (b"\r\n", b"\n", b""):
                break
        if method.upper() not in ("GET", "HEAD"):
            writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return
        # strip query
        raw_path = path.split("?", 1)[0]
        if raw_path == "/":
            raw_path = "/nightclaw-monitor.html"
        if raw_path == "/nc_config.json":
            body = json.dumps({"bridge_port": bridge_port}).encode("utf-8")
            await _send(writer, HTTPStatus.OK, "application/json; charset=utf-8", body,
                        head_only=(method.upper() == "HEAD"))
            return
        # Path safety — no traversal, must live under docroot.
        rel = raw_path.lstrip("/")
        if ".." in rel.split("/"):
            await _send(writer, HTTPStatus.FORBIDDEN, "text/plain", b"forbidden")
            return
        full = os.path.normpath(os.path.join(docroot, rel))
        if not full.startswith(os.path.normpath(docroot)):
            await _send(writer, HTTPStatus.FORBIDDEN, "text/plain", b"forbidden")
            return
        if not os.path.isfile(full):
            await _send(writer, HTTPStatus.NOT_FOUND, "text/plain", b"not found")
            return
        with open(full, "rb") as f:
            data = f.read()
        ext = os.path.splitext(full)[1].lower()
        ctype = _MIME.get(ext, "application/octet-stream")
        await _send(writer, HTTPStatus.OK, ctype, data,
                    head_only=(method.upper() == "HEAD"))
    except Exception:
        # Never let a broken client kill the accept loop.
        try:
            writer.write(b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        except Exception:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _send(writer: asyncio.StreamWriter, status: HTTPStatus, ctype: str,
                body: bytes, head_only: bool = False) -> None:
    reason = status.phrase
    head = (
        f"HTTP/1.1 {status.value} {reason}\r\n"
        f"Content-Type: {ctype}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Cache-Control: no-store\r\n"
        f"Connection: close\r\n\r\n"
    ).encode("iso-8859-1")
    writer.write(head)
    if not head_only:
        writer.write(body)
    await writer.drain()


# ----------------------------------------------------------------------------
# WebSocket support. We lazy-import `websockets` so importing this module
# is cheap even when the runtime is not started.
# ----------------------------------------------------------------------------

@dataclass(eq=False)
class _WsClient:
    ws: Any
    privilege: str  # "ro" or "rw"
    endpoint: str   # "/ws" or "/sessions"


@dataclass
class RuntimeConfig:
    workspace: str
    docroot: str
    bridge_port: int = 8787
    http_port: int = 0  # 0 means "don't start HTTP"
    ops_sock_path: str = "/tmp/nightclaw-ops.sock"
    bridge_token: Optional[str] = None  # None → RO-only
    sessions_path: Optional[str] = None  # persist events if given


class LocalRuntime:
    """Optional local runtime wiring HTTP + WS + ops ingest together."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        repo = (FileSessionRepository(config.sessions_path)
                if config.sessions_path else MemorySessionRepository())
        self._repo = repo
        self._clients: set[_WsClient] = set()
        self._clients_lock = asyncio.Lock()
        self._ws_server: Any = None
        self._http_server: Any = None
        self._ops_sink: Any = None
        self._server = BridgeServer(repo=repo, broadcast=self._broadcast_bridge_event)
        # Supplementary source-file state: dedup keys so we only emit each
        # audit/notification/bundle line once per process lifetime.
        self._seen_audit: set[str] = set()
        self._seen_notifs: set[str] = set()
        self._seen_bundles: set[str] = set()
        self._last_scr: Optional[dict] = None
        # BUG-9: track last change_log/bundle_history fingerprint so we only
        # emit a partial state_replay when the content actually changed, not
        # on every T4-T9 opsstepevent (which caused the console flood).
        self._last_partial_replay_hash: str = ""
        # Rate-limit failed token attempts (NIST SP 800-63B §5.2.2 / OWASP ASVS 2.2.1).
        self._auth_fails: dict = {}  # remote_addr -> list[monotonic timestamps]
        self._AUTH_FAIL_MAX: int = 5
        self._AUTH_FAIL_WINDOW_S: int = 60

    # ------- Broadcast fan-out -------

    async def _broadcast_bridge_event(self, payload: Mapping[str, Any]) -> None:
        """Called by the ops socket path for each accepted payload.

        Fans out adapted events to connected WebSocket clients. Each step
        event also triggers a lightweight re-read of repo governance/audit
        files so the UI's change_log / notifications / audit_tail panes
        update without needing a full page reload.
        """
        main_events = list(self._adapt_for_main(payload))
        # Augment with derived events drawn from the workspace, when the
        # emission was a step event and a workspace is configured.
        if payload.get("type") == "opsstepevent" and self.config.workspace:
            main_events.extend(self._derived_events_from_sources(payload))
        sessions_payload = _sessions_snapshot_payload(
            self._repo, bridge_port=self.config.bridge_port,
            workspace=self.config.workspace, scr_last=self._last_scr)
        await self._broadcast(main_events, sessions_payload)

    def _derived_events_from_sources(self, payload: Mapping[str, Any]) -> list[dict]:
        """Build the supplementary HTML events from repo file reads.

        Events honour existing HTML handlers:
          - audit_tail (per new AUDIT-LOG entry since last emit)
          - notification (per new NOTIFICATIONS.md alert since last emit)
          - state_replay partial (change_log + bundle_history refresh)
        We emit only items the UI hasn't seen yet during this process,
        keyed off an in-memory 'last seen' set.
        """
        tier = payload.get("tier", "")
        ws = self.config.workspace
        out: list[dict] = []
        # Audit tail: emit only rows we haven't emitted yet.
        try:
            audit_tail = sources.parse_audit_tail(
                os.path.join(ws, "audit", "AUDIT-LOG.md"), count=60)
        except Exception:
            audit_tail = []
        for e in audit_tail:
            key = e.get("line", "")
            if not key or key in self._seen_audit:
                continue
            self._seen_audit.add(key)
            out.append({
                "event_type": "audit_tail",
                "line": e["line"],
                "severity": e["severity"],
                "ts": e["ts"] or payload.get("t_emitted", _now_iso()),
            })
        # Bound the seen set so it does not grow unbounded.
        if len(self._seen_audit) > 2000:
            self._seen_audit = set(list(self._seen_audit)[-1000:])

        # Notifications: emit new alerts as notification events.
        try:
            notifs = sources.parse_notifications(
                os.path.join(ws, "NOTIFICATIONS.md"), max_entries=80)
        except Exception:
            notifs = []
        for n in notifs:
            key = f"{n.get('ts','')}|{n.get('message','')[:80]}"
            if not key or key in self._seen_notifs:
                continue
            self._seen_notifs.add(key)
            out.append({
                "event_type": "notification",
                "message": _notif_summary(n),
                "ts": n.get("ts", payload.get("t_emitted", _now_iso())),
                "priority": n.get("priority", ""),
                "project": n.get("project", ""),
                "status": n.get("status", ""),
            })
        if len(self._seen_notifs) > 400:
            self._seen_notifs = set(list(self._seen_notifs)[-200:])

        # Change log refresh + bundle emit for tiers that write (T4/T6).
        if tier in ("T4", "T5", "T6", "T7", "T8", "T9"):
            try:
                change_log = sources.parse_change_log(
                    os.path.join(ws, "audit", "CHANGE-LOG.md"))
            except Exception:
                change_log = []
            # Piggy-back on state_replay: the HTML handler will re-render
            # the change-log and bundle panes without resetting the rest.
            try:
                bundle_history = sources.parse_bundle_history(
                    os.path.join(ws, "audit", "AUDIT-LOG.md"))
            except Exception:
                bundle_history = []
            # Emit only new bundles as bundle_exec_result events.
            for b in bundle_history:
                key = f"{b.get('run_id','')}|{b.get('bundle_name','')}|{b.get('ts','')}"
                if not key or key in self._seen_bundles:
                    continue
                self._seen_bundles.add(key)
                out.append({
                    "event_type": "bundle_exec_result",
                    "bundle_name": b["bundle_name"],
                    "ok": b["ok"],
                    "run_id": b["run_id"],
                    "ts": b["ts"],
                    "mutations_applied": b["mutations_applied"],
                    "guards_checked": b["guards_checked"],
                })
            if len(self._seen_bundles) > 400:
                self._seen_bundles = set(list(self._seen_bundles)[-200:])
            # BUG-9: only emit partial state_replay when change_log or
            # bundle_history actually changed vs last emission.  Emitting on
            # every T4-T9 step was causing a console flood in the monitor
            # because state_replay bypasses the pacing buffer.
            _payload_hash = hashlib.md5(
                json.dumps([change_log, bundle_history], sort_keys=True,
                           default=str).encode()
            ).hexdigest()
            if _payload_hash != self._last_partial_replay_hash:
                self._last_partial_replay_hash = _payload_hash
                out.append({
                    "event_type": "state_replay",
                    "change_log": change_log,
                    "bundle_history": bundle_history,
                })
        # Refresh SCR grid when a scr-verify step completes (exit_code present).
        # BUG-10: Previously triggered on every incoming T8 scr-verify event,
        # including the two events emitted by the subprocess we spawn ourselves
        # (lifecycle_step enter + exit).  That created an infinite feedback loop:
        # bridge receives scr-verify → spawns subprocess → subprocess emits
        # scr-verify → bridge receives it → spawns another subprocess → ...
        # Fix: only run the subprocess when the event carries exit_code (i.e. it
        # is the completion event from the *engine*, not our own spawn), AND
        # guard with a cooldown so back-to-back completions don't pile up.
        _scr_exit = payload.get("exit_code")
        if (tier == "T8" and payload.get("cmd", "") == "scr-verify"
                and _scr_exit is not None and self.config.workspace):
            _now = time.monotonic()
            _last = getattr(self, "_last_scr_refresh_ts", 0.0)
            if _now - _last >= 30.0:  # at most once every 30 s
                self._last_scr_refresh_ts = _now
                try:
                    scr = sources.run_scr_verify(self.config.workspace)
                    if scr:
                        self._last_scr = scr
                        out.append(scr)
                except Exception:
                    pass
        return out

    def _adapt_for_main(self, payload: Mapping[str, Any]):
        if payload.get("type") != "opsstepevent":
            return
        tier = payload.get("tier", "")
        step = _tier_to_step(tier)
        run_id = payload.get("run_id", "")
        ts = payload.get("t_emitted", _now_iso())
        if tier == "T0":
            yield {
                "event_type": "session_open",
                "run_id": run_id,
                "agent_type": payload.get("session") or "worker",
                "ts": ts,
            }
        _exit_code = payload.get("exit_code")  # None = enter event, int = exit event
        step_ev: dict = {
            "event_type": "step",
            "step": step,
            "tier": tier,
            "cmd": payload.get("cmd", ""),
            "ts": ts,
            "run_id": run_id,
            "project_slug": payload.get("slug"),
        }
        if _exit_code is not None:
            step_ev["exit_code"] = _exit_code
        yield step_ev
        if tier == "T9":
            yield {
                "event_type": "session_close",
                "run_id": run_id,
                "ts": ts,
            }

    async def _broadcast(self, main_events: list[dict], sessions_payload: dict) -> None:
        async with self._clients_lock:
            clients = list(self._clients)
        for c in clients:
            try:
                if c.endpoint == "/ws":
                    for ev in main_events:
                        await c.ws.send(json.dumps(ev))
                elif c.endpoint == "/sessions":
                    await c.ws.send(json.dumps(sessions_payload))
            except Exception:
                await self._drop_client(c)

    async def _drop_client(self, c: _WsClient) -> None:
        async with self._clients_lock:
            self._clients.discard(c)
        try:
            await c.ws.close()
        except Exception:
            pass

    # ------- WebSocket handshake + message loop -------

    def _refresh_scr_sync(self) -> None:
        """Blocking helper — run in executor so startup stays non-blocking."""
        try:
            scr = sources.run_scr_verify(self.config.workspace)
            if scr:
                self._last_scr = scr
        except Exception:
            pass

    def _privilege_for_token(self, token: str) -> str:
        expected = self.config.bridge_token
        if not token:
            return "ro"
        if expected:
            # Constant-time comparison prevents timing-based token enumeration.
            # NIST SP 800-63B §5.2.3 / OWASP ASVS 2.9.1.
            import hmac as _hmac
            if _hmac.compare_digest(token, expected):
                return "rw"
            return "ro"
        # Token-less mode: any non-empty token gets RO only.
        return "ro"

    async def _ws_handler(self, ws, path: str) -> None:  # pragma: no cover - integration-covered
        endpoint = "/sessions" if path.startswith("/sessions") else "/ws"
        # Send connect_required, wait for connect frame
        try:
            await ws.send(json.dumps({"event_type": "connect_required"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        except Exception:
            return
        try:
            req = json.loads(raw)
        except Exception:
            await ws.send(json.dumps({
                "event_type": "auth_failed",
                "output": "malformed connect frame",
                "error_code": "MALFORMED",
            }))
            return
        if req.get("type") != "connect":
            await ws.send(json.dumps({
                "event_type": "auth_failed",
                "output": "expected connect frame",
                "error_code": "EXPECTED_CONNECT",
            }))
            return
        token = req.get("token", "") or ""
        # Rate-limit: refuse clients exceeding failed-auth threshold.
        import time as _time
        _remote = None
        try:
            _remote = ws.remote_address[0] if hasattr(ws, "remote_address") else None
        except Exception:
            pass
        if _remote and token:
            _now = _time.monotonic()
            _fails = [t for t in self._auth_fails.get(_remote, [])
                      if _now - t < self._AUTH_FAIL_WINDOW_S]
            if len(_fails) >= self._AUTH_FAIL_MAX:
                await ws.send(json.dumps({
                    "event_type": "auth_failed",
                    "output": "too many failed attempts — try again later",
                    "error_code": "RATE_LIMITED",
                }))
                return
        privilege = self._privilege_for_token(token)
        # Record failed attempts so rate-limiter can act on the next connection.
        if token and privilege != "rw" and self.config.bridge_token and _remote:
            import time as _time2
            _fails = self._auth_fails.get(_remote, [])
            _fails.append(_time2.monotonic())
            self._auth_fails[_remote] = _fails[-(self._AUTH_FAIL_MAX * 2):]
        ack = {
            "event_type": "connect_ack",
            "v": 7,
            "privilege": privilege,
            "session_token": f"local-{os.getpid()}",
        }
        await ws.send(json.dumps(ack))
        client = _WsClient(ws=ws, privilege=privilege, endpoint=endpoint)
        async with self._clients_lock:
            self._clients.add(client)

        # Send initial state_replay (main) or sessions_snapshot (sessions).
        try:
            if endpoint == "/ws":
                _replay = _state_replay_payload(
                    self._repo, workspace=self.config.workspace)
                if self._last_scr is not None:
                    _replay["scr_last"] = self._last_scr
                await ws.send(json.dumps(_replay))
            else:
                await ws.send(json.dumps(_sessions_snapshot_payload(
                    self._repo, bridge_port=self.config.bridge_port,
                    workspace=self.config.workspace, scr_last=self._last_scr)))
        except Exception:
            pass

        try:
            async for msg in ws:
                await self._handle_client_frame(client, msg)
        except Exception:
            pass
        finally:
            await self._drop_client(client)

    async def _handle_client_frame(self, client: _WsClient, raw) -> None:
        try:
            frame = json.loads(raw)
        except Exception:
            return
        ftype = frame.get("type")
        if ftype == "admin_command":
            cmd = frame.get("cmd", "")
            args = frame.get("args") or {}
            result = await self.run_admin_command(
                cmd, args, privilege=client.privilege)
            try:
                await client.ws.send(json.dumps(result))
            except Exception:
                pass
            return
        # RO read-surfaces for the owner UI. Both are strict supersets of the
        # live state_replay envelope, composed from existing sources parsers;
        # no privilege gate (RO) because they expose only already-readable
        # audit/governance state.
        if ftype == "project_snapshot":
            slug = (frame.get("project_slug") or "").strip()
            if not _slug_ok(slug):
                return
            try:
                payload = _project_snapshot_payload(
                    self._repo, workspace=self.config.workspace, slug=slug)
                await client.ws.send(json.dumps(payload))
            except Exception:
                pass
            return
        if ftype == "session_replay":
            run_id = (frame.get("run_id") or "").strip()
            # Accept any safe run_id (alnum + dash/underscore, max 64 chars)
            import re as _re
            if not run_id or not _re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", run_id):
                return
            try:
                payload = _session_replay_payload(
                    self._repo, workspace=self.config.workspace, run_id=run_id)
                await client.ws.send(json.dumps(payload))
            except Exception:
                pass
            return

    # ------- Admin command runner (also used by tests directly) -------

    async def _run_python_source_command(self, cmd: str, args: Mapping[str, Any] | None = None) -> dict:
        """RO/RW commands served directly from the sources module rather than by
        shelling out. Returns a command_result with structured `output` text
        that the existing HTML command_result handler prints verbatim, plus
        a `data` field for future structured consumption.
        """
        if args is None:
            args = {}
        ws = self.config.workspace
        if cmd == "preapprovals":
            items = sources.parse_preapprovals(
                os.path.join(ws, "orchestration-os", "OPS-PREAPPROVAL.md"))
            lines = [f"{p['id']}  status={p['status']}  expires={p['expires']}  "
                     f"class={p['action_class']}" for p in items]
            return {
                "event_type": "command_result",
                "cmd": cmd, "ok": True,
                "output": "\n".join(lines) if lines
                          else "(no pre-approvals defined)",
                "data": items,
                "exit_code": 0,
            }
        if cmd == "approval_chain":
            items = sources.parse_approval_chain(
                os.path.join(ws, "audit", "APPROVAL-CHAIN.md"))
            lines = [f"{it['ts']}  {it['pa_id']}#{it['invocation']}  "
                     f"result={it['result']}  action={it['action'][:80]}"
                     for it in items]
            return {
                "event_type": "command_result",
                "cmd": cmd, "ok": True,
                "output": "\n".join(lines) if lines
                          else "(no PA invocations recorded)",
                "data": items,
                "exit_code": 0,
            }
        if cmd == "notifications_pending":
            entries = sources.parse_notifications(
                os.path.join(ws, "NOTIFICATIONS.md"))
            transitions = sources.has_pending_phase_transition(entries)
            return {
                "event_type": "command_result",
                "cmd": cmd, "ok": True,
                "output": "\n".join(
                    f"{e['ts']}  {e['priority']}  {e['project']}  {e['message'][:80]}"
                    for e in transitions) or "(no pending phase transitions)",
                "data": transitions,
                "exit_code": 0,
            }
        if cmd == "clear_notifications":
            import datetime as _dt
            notif_path = os.path.join(ws, "NOTIFICATIONS.md")
            if not os.path.isfile(notif_path):
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": "NOTIFICATIONS.md not found", "exit_code": 1}
            try:
                content = open(notif_path, encoding="utf-8").read()
                # Only archive if there's actual content beyond a header line
                lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]
                if not lines:
                    return {"event_type": "command_result", "cmd": cmd,
                            "ok": True, "output": "Nothing to clear.", "exit_code": 0}
                # Write archive file
                date_str = _dt.datetime.utcnow().strftime("%Y-%m-%d")
                archive_dir = os.path.join(ws, "audit")
                os.makedirs(archive_dir, exist_ok=True)
                archive_path = os.path.join(archive_dir, f"NOTIFICATIONS-ARCHIVE-{date_str}.md")
                # Append to archive (may already exist for today)
                with open(archive_path, "a", encoding="utf-8") as af:
                    af.write(f"\n<!-- archived {_dt.datetime.utcnow().isoformat()}Z -->\n")
                    af.write(content)
                # Truncate live file to just a header
                with open(notif_path, "w", encoding="utf-8") as nf:
                    nf.write("# NOTIFICATIONS\n")
                return {"event_type": "command_result", "cmd": cmd, "ok": True,
                        "output": f"Archived {len(lines)} entries to audit/{os.path.basename(archive_path)} and cleared NOTIFICATIONS.md",
                        "exit_code": 0}
            except Exception as e:
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": f"Error: {e}", "exit_code": 1}
        if cmd == "diag_longrunner":
            import subprocess as _sp
            lines = []
            ap_path = os.path.join(ws, "ACTIVE-PROJECTS.md")
            lines.append(f"workspace: {ws}")
            lines.append(f"ACTIVE-PROJECTS.md: {os.path.isfile(ap_path)}")
            try:
                rows = sources.parse_active_projects(ap_path)
                lines.append(f"rows found: {len(rows)}")
                for r in rows[:3]:
                    lines.append(f"  slug={r.get('slug')} status={r.get('status')}")
                slug = _resolve_slug(rows)
            except Exception as e:
                lines.append(f"parse_active_projects error: {e}")
                slug = None
            ops_py = os.path.join(ws, "scripts", "nightclaw-ops.py")
            lines.append(f"nightclaw-ops.py: {os.path.isfile(ops_py)}")
            lines.append(f"resolved slug: {slug}")
            lr_path = os.path.join(ws, "PROJECTS", slug, "LONGRUNNER.md") if slug else None
            lines.append(f"LONGRUNNER.md path: {lr_path}")
            lines.append(f"LONGRUNNER.md exists: {os.path.isfile(lr_path) if lr_path else False}")
            if lr_path and os.path.isfile(lr_path):
                parsed = sources._parse_longrunner_md(lr_path)
                populated = {k: v for k, v in parsed.items() if v and v not in ([], 'false', '')}
                lines.append(f"parsed fields: {list(populated.keys())}")
                for k, v in list(populated.items())[:6]:
                    lines.append(f"  {k}: {str(v)[:80]}")
            if slug and os.path.isfile(ops_py):
                try:
                    p = _sp.run(
                        ["python3", ops_py, "longrunner-extract", slug],
                        cwd=ws, capture_output=True, text=True, timeout=5)
                    lines.append(f"exit: {p.returncode}")
                    lines.append(f"stdout: {(p.stdout or '').strip()[:1200]}")
                    # Also show what extract_longrunner maps it to
                    import re as _re
                    kv = {}
                    for ln in (p.stdout or '').splitlines():
                        if '=' in ln:
                            k, _, v = ln.partition('=')
                            kv[k.strip()] = v.strip()
                    mapped_keys = [k for k in kv if k.startswith('phase.')]
                    lines.append(f"phase.* keys in output: {mapped_keys if mapped_keys else 'NONE — monitor will show empty state'}")
                    lines.append(f"all keys: {list(kv.keys())[:20]}")
                    if p.stderr:
                        lines.append(f"stderr: {p.stderr.strip()[:200]}")
                except Exception as e:
                    lines.append(f"exception: {e}")
            return {
                "event_type": "command_result",
                "cmd": cmd, "ok": True,
                "output": "\n".join(lines),
                "exit_code": 0,
            }
        if cmd == "archive_project":
            slug = args.get("slug", "").strip()
            if not _slug_ok(slug):
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": "Invalid or missing slug", "exit_code": 1}
            ap_path = os.path.join(ws, "ACTIVE-PROJECTS.md")
            if not os.path.isfile(ap_path):
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": "ACTIVE-PROJECTS.md not found", "exit_code": 1}
            try:
                text = open(ap_path, encoding="utf-8").read()
                import re as _re
                # Match table row containing this slug; replace its status cell
                # Row format: | priority | slug | phase | status | last_pass | escalation |
                # We find the slug anywhere in a pipe-delimited line and replace status col
                lines_out = []
                changed = False
                for line in text.splitlines(keepends=True):
                    if slug in line and "|" in line:
                        new_line = _re.sub(
                            r'(\|\s*' + _re.escape(slug) + r'\s*\|[^|]*\|[^|]*\|)\s*\w+\s*(\|)',
                            lambda m: m.group(1) + " archived " + m.group(2),
                            line,
                        )
                        if new_line != line:
                            changed = True
                            line = new_line
                    lines_out.append(line)
                if not changed:
                    return {"event_type": "command_result", "cmd": cmd,
                            "ok": False,
                            "output": f"Slug '{slug}' not found in ACTIVE-PROJECTS.md table",
                            "exit_code": 1}
                with open(ap_path, "w", encoding="utf-8") as f:
                    f.write("".join(lines_out))
                return {"event_type": "command_result", "cmd": cmd, "ok": True,
                        "output": f"'{slug}' marked archived in ACTIVE-PROJECTS.md",
                        "exit_code": 0}
            except Exception as e:
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": f"Error: {e}", "exit_code": 1}
        if cmd == "resign":
            import subprocess as _sp
            file_arg = args.get("file", "").strip()
            if not file_arg:
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": "Missing 'file' arg — enter file path in the resign input",
                        "exit_code": 1}
            # Block path traversal
            if ".." in file_arg or file_arg.startswith("/"):
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": "Absolute paths and '..' not allowed", "exit_code": 1}
            resign_sh = os.path.join(ws, "scripts", "resign.sh")
            if not os.path.isfile(resign_sh):
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": "scripts/resign.sh not found", "exit_code": 1}
            try:
                p = _sp.run(["bash", resign_sh, file_arg],
                            cwd=ws, capture_output=True, text=True, timeout=30)
                out = ((p.stdout or "") + (p.stderr or "")).strip()
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": p.returncode == 0,
                        "output": out or "(no output)",
                        "exit_code": p.returncode}
            except Exception as e:
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": f"Error: {e}", "exit_code": 1}
        if cmd == "validate":
            import subprocess as _sp
            validate_sh = os.path.join(ws, "scripts", "validate.sh")
            if not os.path.isfile(validate_sh):
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": "scripts/validate.sh not found", "exit_code": 1}
            try:
                p = _sp.run(["bash", validate_sh],
                            cwd=ws, capture_output=True, text=True, timeout=60)
                # Strip ANSI colour codes so monitor console renders cleanly
                import re as _re
                ansi = _re.compile(r'\x1b\[[0-9;]*m')
                out = ansi.sub("", ((p.stdout or "") + (p.stderr or "")).strip())
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": p.returncode == 0,
                        "output": out or "(no output)",
                        "exit_code": p.returncode}
            except Exception as e:
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": f"Error: {e}", "exit_code": 1}
        if cmd == "scr":
            # Run SCR verify via sources and return a scr_verify_result so the
            # monitor grid updates immediately — not just a console text dump.
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, sources.run_scr_verify, ws)
            if result is None:
                return {"event_type": "command_result", "cmd": cmd,
                        "ok": False, "output": "scr-verify failed (ops.py not found)", "exit_code": 1}
            result["event_type"] = "scr_verify_result"
            result["cmd"] = cmd
            return result
        return {"event_type": "command_result", "cmd": cmd, "ok": False,
                "output": "unknown source command", "exit_code": 1}

    async def run_admin_command(self, cmd: str, args: Mapping[str, Any],
                                *, privilege: str) -> dict:
        if cmd not in ADMIN_CMD_ALL:
            return {
                "event_type": "command_result",
                "cmd": cmd, "ok": False,
                "output": f"unknown command {cmd!r}",
            }
        if cmd in ADMIN_CMD_RW and privilege != "rw":
            return {
                "event_type": "command_result",
                "cmd": cmd, "ok": False,
                "output": "privilege insufficient (RW required)",
            }
        # Commands served directly from parsers / Python handlers — no argv build.
        if cmd in ("preapprovals", "approval_chain", "notifications_pending", "diag_longrunner",
                   "clear_notifications", "archive_project", "resign", "validate", "scr"):
            return await self._run_python_source_command(cmd, args)
        argv = _build_admin_argv(self.config.workspace, cmd, args)
        if argv is None:
            return {
                "event_type": "command_result",
                "cmd": cmd, "ok": False,
                "output": "invalid args",
            }
        # Ensure executables referenced exist before invoking.
        if argv[0] in ("bash", "python3", "cat", "tail") and shutil.which(argv[0]) is None:
            return {
                "event_type": "command_result",
                "cmd": cmd, "ok": False,
                "output": f"missing executable: {argv[0]}",
            }
        loop = asyncio.get_event_loop()
        # 'done' asks for interactive y/N confirmation; feed a confirmed 'y'
        # since the UI reaching this code path is the confirmation gesture.
        stdin_input = "y\n" if cmd == "done" else None
        def _run() -> tuple[int, str]:
            try:
                p = subprocess.run(
                    argv,
                    cwd=self.config.workspace,
                    capture_output=True,
                    text=True,
                    input=stdin_input,
                    timeout=20,
                )
                out = (p.stdout or "") + (p.stderr or "")
                return p.returncode, out
            except subprocess.TimeoutExpired:
                return 124, "timeout"
            except Exception as exc:
                return 1, f"exec error: {exc}"
        rc, out = await loop.run_in_executor(None, _run)
        return {
            "event_type": "command_result",
            "cmd": cmd,
            "ok": rc == 0,
            "output": out,
            "exit_code": rc,
        }

    # ------- Lifecycle -------

    async def start(self) -> None:
        # Populate SCR grid in the background so state_replay includes it
        # without blocking the WS/HTTP server startup.
        if self.config.workspace:
            asyncio.get_event_loop().run_in_executor(None, self._refresh_scr_sync)
        # Start ops sink (unix socket) for telemetry ingest.
        self._ops_sink = await start_ops_sink(
            self._repo, self._broadcast_bridge_event,
            path=self.config.ops_sock_path,
        )
        # Start WebSocket server on bridge_port (if >0).
        if self.config.bridge_port and self.config.bridge_port > 0:
            try:
                import websockets  # type: ignore
            except Exception:  # pragma: no cover
                self._ws_server = None
            else:
                async def _router(ws, path=None):
                    # websockets 14+ does not pass path positionally and the
                    # path lives on ws.request.path (not ws.path). Older
                    # releases passed it as the second positional arg.
                    if path is None:
                        req = getattr(ws, "request", None)
                        if req is not None:
                            path = getattr(req, "path", None)
                        if path is None:
                            path = getattr(ws, "path", None)
                    if not path:
                        path = "/ws"
                    await self._ws_handler(ws, path)
                self._ws_server = await websockets.serve(
                    _router, "127.0.0.1", self.config.bridge_port,
                )
        # Start HTTP on http_port if requested.
        if self.config.http_port and self.config.http_port > 0:
            async def _http_cb(r, w):
                await _http_handler(r, w, docroot=self.config.docroot,
                                    bridge_port=self.config.bridge_port)
            self._http_server = await asyncio.start_server(
                _http_cb, "127.0.0.1", self.config.http_port,
            )

    async def stop(self) -> None:
        # Tell WS clients we are going away so the UI shows a clean reconnect.
        async with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for c in clients:
            try:
                await c.ws.send(json.dumps({"event_type": "bridge_shutdown"}))
                await c.ws.close()
            except Exception:
                pass
        for srv in (self._ws_server, self._http_server, self._ops_sink):
            if srv is None:
                continue
            try:
                srv.close()
                await srv.wait_closed()
            except Exception:
                pass


def build_runtime(
    *,
    workspace: str,
    docroot: Optional[str] = None,
    bridge_port: int = 8787,
    http_port: int = 0,
    ops_sock_path: Optional[str] = None,
    bridge_token: Optional[str] = None,
    sessions_path: Optional[str] = None,
) -> LocalRuntime:
    if docroot is None:
        docroot = os.path.join(workspace, "apps", "monitor")
    if ops_sock_path is None:
        ops_sock_path = os.environ.get("NIGHTCLAW_OPS_SOCK", "/tmp/nightclaw-ops.sock")
    cfg = RuntimeConfig(
        workspace=workspace,
        docroot=docroot,
        bridge_port=bridge_port,
        http_port=http_port,
        ops_sock_path=ops_sock_path,
        bridge_token=bridge_token,
        sessions_path=sessions_path,
    )
    return LocalRuntime(cfg)
