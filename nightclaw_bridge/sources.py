"""nightclaw_bridge.sources — read-only adapters that surface repo
governance/audit/notification state to the monitor UI without coupling
the core engine to the bridge.

Everything in this module is read-only. Parsers tolerate missing files,
empty files, malformed or truncated entries, and always cap the number
of items they return so a very large file cannot blow up the ops path.
No parser writes to the filesystem or shells out — they only open a
file, read bytes, and return dicts.

The output shapes are tuned to the event vocabulary the shipped
apps/monitor/nightclaw-monitor.html already consumes (see
``handleEvent`` + the render helpers there). If the repo lacks a
source file we return an empty list; the UI shows its honest empty
state rather than fabricated data.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# NOTIFICATIONS.md  →  list[{ts, message, priority, project, status}]
# ---------------------------------------------------------------------------

_NOTIF_HEADER_RE = re.compile(
    # Timestamp: three supported formats:
    #   [2026-04-21 09:00]   — bracketed, space-separated (legacy template)
    #   [2026-04-23T16:40:00Z] — bracketed ISO8601
    #   2026-04-23T16:40:00Z — bare ISO8601 (actual worker prompt format, no brackets)
    r"^\[?(?P<ts>[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:]+Z?)\]?\s*\|\s*Priority:\s*(?P<prio>[^|]+?)\s*"
    r"(?:\|\s*Project:\s*(?P<project>[^|]+?)\s*)?"
    r"(?:\|\s*Status:\s*(?P<status>[^|]+?)\s*)?$"
)


def parse_notifications(path: str, *, max_entries: int = 40) -> list[dict]:
    """Parse NOTIFICATIONS.md and return the most recent alert entries.

    Each entry is a dict matching the UI's notifications inbox shape:
      {ts, message, priority, project, status}
    Entries flagged '[DONE …] ' at the start of the header line are
    filtered out — the inbox only shows unresolved items.
    """
    lines = _read_lines(path)
    if not lines:
        return []
    entries: list[dict] = []
    current: Optional[dict] = None
    for raw in lines:
        line = raw.rstrip("\n")
        # Skip archived/resolved entries (but flush the pending one first).
        if line.startswith("[DONE"):
            if current is not None:
                entries.append(current)
                current = None
            continue
        m = _NOTIF_HEADER_RE.match(line.strip())
        if m:
            if current is not None:
                entries.append(current)
            raw_status = (m.group("status") or "").strip()
            # Worker prompt writes message body inline after a literal '\n'
            # on the same header line, e.g.:
            #   ... | Status: SCR-FAIL \nSCR-05 FAIL: details here
            # Split on the literal two-character sequence backslash-n.
            if "\\n" in raw_status:
                status_part, _, msg_part = raw_status.partition("\\n")
            else:
                status_part, msg_part = raw_status, ""
            current = {
                "ts": _normalize_ts(m.group("ts")),
                "priority": (m.group("prio") or "").strip(),
                "project": (m.group("project") or "").strip(),
                "status": status_part.strip(),
                "message": msg_part.strip(),
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            # blank line → header only
            continue
        # Accumulate the body (first 3 substantive lines is plenty for UI).
        if current["message"]:
            current["message"] += " | " + stripped
        else:
            current["message"] = stripped
    if current is not None:
        entries.append(current)

    # Return the most recent entries, newest last in file, but UI reverses.
    return entries[-max_entries:]


def has_pending_phase_transition(entries: Iterable[dict]) -> list[dict]:
    """Return the subset of notification entries flagged as phase transitions.

    The admin CLI ``done <line>`` verb approves phase transitions when the
    targeted line mentions TRANSITION-HOLD / phase-transition / phase-complete.
    """
    out: list[dict] = []
    for e in entries:
        blob = " ".join((e.get("status", ""), e.get("message", ""))).upper()
        if ("TRANSITION-HOLD" in blob or "PHASE-TRANSITION" in blob
                or "PHASE-COMPLETE" in blob):
            out.append(e)
    return out


# ---------------------------------------------------------------------------
# audit/AUDIT-LOG.md  →  list[{ts, line, severity, type, result}]
# ---------------------------------------------------------------------------

_AUDIT_V19_RE = re.compile(
    r"^TASK:(?P<task>[^|]+)\|\s*TYPE:(?P<type>[^|]+?)\s*(?:\|\s*(?P<rest>.*))?$"
)
_AUDIT_RESULT_RE = re.compile(r"\bRESULT:\s*([A-Z_]+)")


def parse_audit_tail(path: str, *, count: int = 30) -> list[dict]:
    """Return the last `count` audit entries as structured dicts.

    Each entry: {line, ts, severity, type, result, task}
    Severity: 'ok' for PASS/SUCCESS, 'err' for FAIL/BLOCKED, else 'info'.
    """
    lines = _read_content_lines(path)
    entries: list[dict] = []
    for raw in lines[-max(count * 3, 200):]:
        line = raw.strip()
        if not line.startswith("TASK:"):
            continue
        m = _AUDIT_V19_RE.match(line)
        type_ = result = ""
        task = ""
        if m:
            task = m.group("task").strip()
            type_ = m.group("type").strip()
            rm = _AUDIT_RESULT_RE.search(line)
            if rm:
                result = rm.group(1).strip()
        severity = "info"
        up = result.upper()
        if up in ("PASS", "SUCCESS"):
            severity = "ok"
        elif up in ("FAIL", "BLOCKED"):
            severity = "err"
        entries.append({
            "line": line,
            "ts": _ts_from_run_id(task),
            "severity": severity,
            "type": type_,
            "result": result,
            "task": task,
        })
    return entries[-count:]


# ---------------------------------------------------------------------------
# audit/CHANGE-LOG.md  →  list[{file, field, old_val, new_val, ts, reason}]
# ---------------------------------------------------------------------------

def parse_change_log(path: str, *, count: int = 30) -> list[dict]:
    """Parse the pipe-delimited field-level change log.

    Format: field_path|old|new|agent|run_id|t_written|t_valid|reason|bundle
    Returns the UI shape: {file, field, old_val, new_val, ts, reason}.
    """
    lines = _read_content_lines(path)
    out: list[dict] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "<!--", "---", "```", "FIELD:")):
            continue
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        field_path = parts[0]
        old_val = parts[1] if len(parts) > 1 else ""
        new_val = parts[2] if len(parts) > 2 else ""
        run_id = parts[4] if len(parts) > 4 else ""
        ts = parts[5] if len(parts) > 5 else _ts_from_run_id(run_id)
        reason = parts[7] if len(parts) > 7 else ""
        bundle = parts[8] if len(parts) > 8 else ""
        file_, _, field = field_path.partition("#")
        if file_.upper().startswith("FILE:"):
            file_ = file_[5:]
        out.append({
            "file": file_,
            "field": field,
            "old_val": old_val,
            "new_val": new_val,
            "ts": ts,
            "reason": reason,
            "bundle": bundle,
            "run_id": run_id,
        })
    return out[-count:]


# ---------------------------------------------------------------------------
# audit/AUDIT-LOG.md (BUNDLE lines)  →  list[{bundle_name, ok, ts, run_id,
#                                              mutations_applied, guards_checked}]
# ---------------------------------------------------------------------------

def parse_bundle_history(audit_path: str, *, count: int = 10) -> list[dict]:
    """Scan AUDIT-LOG.md for TYPE:BUNDLE entries and adapt to the UI shape.

    The UI's ``renderBundles()`` expects: {bundle_name, ok, run_id,
    mutations_applied: [str], guards_checked: [str]}. Guards aren't
    carried by the v19 compact format; we leave them empty so the UI
    renders the row without a guard count instead of faking one.
    """
    lines = _read_content_lines(audit_path)
    out: list[dict] = []
    for raw in lines:
        line = raw.strip()
        if not line.startswith("TASK:") or "TYPE:BUNDLE" not in line:
            continue
        m = _AUDIT_V19_RE.match(line)
        if not m:
            continue
        task = m.group("task").strip()
        rest = m.group("rest") or ""
        rm = _AUDIT_RESULT_RE.search(line)
        result = (rm.group(1).strip().upper() if rm else "")
        bundle_name = _extract_kv(line, "BUNDLE") or _extract_kv(rest, "BUNDLE") or "?"
        file_ = _extract_kv(line, "FILE") or ""
        mutations = [file_] if file_ else []
        run_id = task.split(".", 1)[0]
        out.append({
            "bundle_name": bundle_name,
            "ok": result in ("SUCCESS", "PASS"),
            "ts": _ts_from_run_id(run_id),
            "run_id": run_id,
            "mutations_applied": mutations,
            "guards_checked": [],
        })
    return out[-count:]


# ---------------------------------------------------------------------------
# orchestration-os/OPS-PREAPPROVAL.md  →  list[{id, status, expires,
#                                                action_class, scope,
#                                                condition, boundary}]
# ---------------------------------------------------------------------------

_PA_HEADER_RE = re.compile(
    r"^##\s*(?P<id>PA-[0-9A-Za-z]+)\s*\|\s*Status:\s*(?P<status>[^|]+?)\s*"
    r"(?:\|\s*Expires:\s*(?P<expires>.*?))?\s*$"
)


def parse_preapprovals(path: str, *, max_entries: int = 32) -> list[dict]:
    """Extract the PA-N entries from OPS-PREAPPROVAL.md."""
    lines = _read_lines(path)
    out: list[dict] = []
    current: Optional[dict] = None
    for raw in lines:
        line = raw.rstrip("\n")
        m = _PA_HEADER_RE.match(line.strip())
        if m:
            if current is not None:
                out.append(current)
            current = {
                "id": m.group("id").strip(),
                "status": m.group("status").strip(),
                "expires": (m.group("expires") or "").strip() or "—",
                "action_class": "",
                "scope": "",
                "condition": "",
                "boundary": "",
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("## "):
            out.append(current)
            current = None
            continue
        for key, label in (
            ("action_class", "**Action class:**"),
            ("scope",        "**Scope:**"),
            ("condition",    "**Condition:**"),
            ("boundary",     "**Boundary:**"),
        ):
            if stripped.startswith(label):
                current[key] = stripped[len(label):].strip()
                break
    if current is not None:
        out.append(current)
    return out[:max_entries]


# ---------------------------------------------------------------------------
# audit/APPROVAL-CHAIN.md  →  list[{pa_id, invocation, ts, result, by,
#                                    action}]
# ---------------------------------------------------------------------------

_PA_INVOCATION_RE = re.compile(
    r"^##\s*\[?(?P<pa>PA-[0-9A-Za-z]+)\]?-INVOCATION-\[?(?P<n>[0-9A-Za-z]+)\]?\s*"
    r"\|\s*(?P<ts>[^\s|]+)\s*$"
)


def parse_approval_chain(path: str, *, max_entries: int = 20) -> list[dict]:
    """Return recent PA invocation blocks."""
    lines = _read_lines(path)
    out: list[dict] = []
    current: Optional[dict] = None
    for raw in lines:
        line = raw.rstrip("\n")
        m = _PA_INVOCATION_RE.match(line.strip())
        if m:
            if current is not None:
                out.append(current)
            current = {
                "pa_id": m.group("pa"),
                "invocation": m.group("n"),
                "ts": m.group("ts"),
                "by": "",
                "action": "",
                "result": "",
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("## "):
            out.append(current)
            current = None
            continue
        for key, label in (
            ("by",     "**Invoked by:**"),
            ("action", "**Action authorized:**"),
            ("result", "**Result:**"),
        ):
            if stripped.startswith(label):
                current[key] = stripped[len(label):].strip()
                break
    if current is not None:
        out.append(current)
    return out[-max_entries:]


# ---------------------------------------------------------------------------
# ACTIVE-PROJECTS.md  →  list[{priority, slug, phase, status, last_pass,
#                               escalation}]
# ---------------------------------------------------------------------------

def parse_active_projects(path: str) -> list[dict]:
    """Parse the markdown scoreboard table."""
    lines = _read_lines(path)
    out: list[dict] = []
    seen_header = False
    for raw in lines:
        line = raw.rstrip("\n").strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not seen_header:
            # First row with 'Priority' / 'Project Slug' is header
            if any("Priority" in c for c in cells) and any("Slug" in c for c in cells):
                seen_header = True
            continue
        # skip separator row of dashes
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        # Only rows with 7 cells match the scoreboard shape.
        if len(cells) < 7:
            continue
        priority, slug, path_, phase, status, last_pass, escalation = cells[:7]
        # Skip the placeholder "(no projects yet)" row
        if slug.startswith("_(") or slug == "—":
            continue
        out.append({
            "priority": priority,
            "slug": slug,
            "longrunner_path": path_,
            "phase": phase,
            "status": status,
            "last_pass": last_pass,
            "escalation": escalation,
        })
    return out


# ---------------------------------------------------------------------------
# PROJECTS/<slug>/LONGRUNNER.md  →  UI-shaped longrunner dict
# ---------------------------------------------------------------------------

def _parse_longrunner_md(path: str) -> dict:
    """Parse LONGRUNNER.md directly, extracting YAML blocks under each section.

    Reads ## Current Phase, ## Last Pass, ## Next Pass, ## Blockers.
    Returns a flat dict keyed the same way extract_longrunner returns.
    """
    try:
        body = open(path, encoding="utf-8").read()
    except Exception:
        return {}

    def _yaml_block(section_header: str) -> dict:
        """Extract the first ```yaml block under a given ## header."""
        pat = re.compile(
            r"##\s+" + re.escape(section_header) + r"\s*\n.*?```yaml\s*\n(.*?)```",
            re.DOTALL | re.IGNORECASE,
        )
        m = pat.search(body)
        if not m:
            return {}
        block = m.group(1)
        # Simple key: value parser — handles nested keys like phase.name
        result: dict = {}
        _parse_yaml_flat(block, result, prefix="")
        return result

    def _parse_yaml_flat(text: str, out: dict, prefix: str) -> None:
        """Flatten YAML-ish key: value lines into dot-notation dict."""
        indent_stack: list[tuple[int, str]] = []  # (indent, prefix)
        for raw in text.splitlines():
            if not raw.strip() or raw.strip().startswith("#"):
                continue
            stripped = raw.lstrip()
            indent = len(raw) - len(stripped)
            # Pop stack entries that are deeper
            while indent_stack and indent_stack[-1][0] >= indent:
                indent_stack.pop()
            cur_prefix = (indent_stack[-1][1] + ".") if indent_stack else ""
            if prefix:
                cur_prefix = prefix + "." + cur_prefix if cur_prefix else prefix + "."
            if ":" not in stripped:
                continue
            k, _, v = stripped.partition(":")
            k = k.strip().strip('"\'')
            v = v.strip().strip('"\'')
            full_key = (cur_prefix + k).strip(".")
            if v and v not in ("~", "null", "[]"):
                out[full_key] = v
            else:
                # Might be a parent key — push onto stack
                indent_stack.append((indent, full_key))

    cp  = _yaml_block("Current Phase")
    lp  = _yaml_block("Last Pass")
    np_ = _yaml_block("Next Pass")

    # Normalise: the YAML nests under phase: / last_pass: / next_pass:
    # After flattening we get keys like "phase.name", "last_pass.date" etc.
    ph = {k.split(".", 1)[1]: v for k, v in cp.items()  if "." in k}
    la = {k.split(".", 1)[1]: v for k, v in lp.items()  if "." in k}
    nx = {k.split(".", 1)[1]: v for k, v in np_.items() if "." in k}

    # Blockers table — any non-empty rows
    blocker_pat = re.compile(
        r"##\s+Blockers\s*\n.*?\|\s*Blocker\s*\|.*?\n\|[-| ]+\|\n(.*?)(?=\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    blockers: list[str] = []
    bm = blocker_pat.search(body)
    if bm:
        for row in bm.group(1).splitlines():
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if cells and cells[0] and cells[0] not in ("", "Blocker"):
                blockers.append(cells[0])

    tools_raw = nx.get("tools_required", "")
    # Strip YAML list brackets if present
    tools_raw = tools_raw.strip("[]").replace('"', '').replace("'", "")

    weak = la.get("weak_pass", "").lower() == "true"
    valid = la.get("validation_passed", "").lower() == "true"

    return {
        "phase_name":      ph.get("name", ""),
        "phase_objective": ph.get("objective", ""),
        "phase_stop":      ph.get("stop_condition", ""),
        "phase_status":    ph.get("status", ""),
        "phase_successor": ph.get("successor", ""),
        "next_pass":       nx.get("objective", ""),
        "next_tier":       nx.get("model_tier", ""),
        "next_budget":     nx.get("context_budget", ""),
        "next_tools":      tools_raw,
        "last_objective":  la.get("objective", ""),
        "last_output":     la.get("output_files", ""),
        "last_quality":    "weak" if weak else ("ok" if valid else ""),
        "last_date":       la.get("date", ""),
        "routing":         "",
        "is_draft":        "",
        "has_blockers":    "true" if blockers else "false",
        "blockers":        blockers,
        "pa_active":       "",
    }


def extract_longrunner(workspace: str, slug: str,
                       *, timeout: float = 5.0) -> Optional[dict]:
    """Extract longrunner state for slug.

    Strategy:
      1. Parse LONGRUNNER.md directly (full fidelity, no subprocess).
      2. Supplement with ops-script flat keys (routing, is_draft, etc.)
         if nightclaw-ops.py is available — those override blanks only.
    """
    lr_path = os.path.join(workspace, "PROJECTS", slug, "LONGRUNNER.md")
    result = _parse_longrunner_md(lr_path) if os.path.isfile(lr_path) else {}

    # Supplement with ops-script output for keys it uniquely provides
    ops_py = os.path.join(workspace, "scripts", "nightclaw-ops.py")
    if os.path.isfile(ops_py):
        try:
            p = subprocess.run(
                ["python3", ops_py, "longrunner-extract", slug],
                cwd=workspace, capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "NIGHTCLAW_NO_TELEMETRY": "1"},
            )
            if p.returncode == 0:
                kv: dict[str, str] = {}
                for line in (p.stdout or "").splitlines():
                    if "=" in line:
                        k, _, v = line.partition("=")
                        kv[k.strip()] = v.strip()
                # Ops script has authoritative routing / is_draft / has_blockers
                for field, key in [("routing", "routing"),
                                   ("is_draft", "is_draft"),
                                   ("has_blockers", "has_blockers"),
                                   ("next_budget", "next_pass.context_budget")]:
                    if key in kv:
                        result[field] = kv[key]
        except Exception:
            pass

    if result:
        result["slug"] = slug  # Always stamp slug so the monitor can display it
    return result if result else None


# ---------------------------------------------------------------------------
# scripts/nightclaw-ops.py scr-verify  →  UI-shaped SCR dict
# ---------------------------------------------------------------------------

_SCR_LINE_RE = re.compile(
    r"^(?:SCR-(?P<num>\d+)|(?P<cl>CL\d+)):(?P<status>PASS|FAIL|SKIP|INFO)(?:\s+(?P<detail>.*))?$"
)


def run_scr_verify(workspace: str, *, timeout: float = 10.0) -> Optional[dict]:
    """Invoke ops.py scr-verify and return a dict the monitor can render.

    Shape: {ts, checks:{SCR-NN: bool}, statuses:{SCR-NN: str}, details:{SCR-NN: str}, passed, failed}
    ``checks`` maps each rule to True (PASS) or False (FAIL only).
    INFO and SKIP rules are excluded from checks so they never render red.
    ``statuses`` carries the raw status string for all rules so the UI can
    distinguish PASS / FAIL / INFO / SKIP and colour them appropriately.
    Lines the UI does not key on (indented context, CL5/RESULT trailers) are
    ignored rather than fabricated into fields.
    """
    ops_py = os.path.join(workspace, "scripts", "nightclaw-ops.py")
    if not os.path.isfile(ops_py):
        return None
    try:
        p = subprocess.run(
            ["python3", ops_py, "scr-verify"],
            cwd=workspace, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "NIGHTCLAW_NO_TELEMETRY": "1"},
        )
    except Exception:
        return None
    checks: dict[str, bool] = {}
    statuses: dict[str, str] = {}
    details: dict[str, str] = {}
    for line in (p.stdout or "").splitlines():
        m = _SCR_LINE_RE.match(line.strip())
        if not m:
            continue
        # Build key: SCR-NN for numbered rules, raw CL5/CLN for CL checks.
        if m.group('num') is not None:
            key = f"SCR-{int(m.group('num')):02d}"
        else:
            key = m.group('cl')  # e.g. "CL5"
        status = m.group("status")
        detail = (m.group("detail") or "").strip()
        statuses[key] = status
        # INFO and SKIP are not failures — exclude from checks dict so the
        # monitor never renders them red. PASS → True, FAIL → False.
        if status in ("PASS", "FAIL"):
            checks[key] = (status == "PASS")
        if detail:
            details[key] = f"{status}: {detail}"
        else:
            details[key] = status
    if not statuses:
        return None
    passed = sum(1 for s in statuses.values() if s == "PASS")
    failed = sum(1 for s in statuses.values() if s == "FAIL")
    import datetime
    return {
        "event_type": "scr_verify_result",
        "checks": checks,
        "statuses": statuses,
        "details": details,
        "passed": passed,
        "failed": failed,
        "ts": datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read_lines(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return []
    except OSError:
        return []


def _read_content_lines(path: str) -> list[str]:
    """Return non-empty, non-comment lines."""
    out: list[str] = []
    for line in _read_lines(path):
        s = line.strip()
        if not s:
            continue
        if s.startswith(("#", "<!--", "```", "---")):
            continue
        out.append(line)
    return out


def _ts_from_run_id(run_id: str) -> str:
    """Best-effort: RUN-YYYYMMDD-NNN -> 'YYYY-MM-DDT00:00:00Z'.

    BUG-4: fmtTs() in the monitor expects an ISO-8601 string including a time
    component; returning only YYYY-MM-DD produces 'Invalid Date' in some
    browsers (Safari, mobile Chrome) because Date.parse() requires a full
    timestamp for ISO strings without an explicit time zone.  Append
    T00:00:00Z so the string always parses cleanly.
    """
    m = re.match(r"^RUN-(\d{4})(\d{2})(\d{2})", run_id or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T00:00:00Z"
    return ""


def _normalize_ts(raw: str) -> str:
    """'2026-04-21 14:05' → '2026-04-21T14:05:00Z' (best-effort)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?", raw)
    if not m:
        return raw
    sec = m.group(4) or "00"
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{sec}Z"


_KV_RE = re.compile(r"\b([A-Z][A-Z_]*)\s*:\s*([^|]+?)(?=\s*\||\s*$)")


def _extract_kv(blob: str, key: str) -> Optional[str]:
    for k, v in _KV_RE.findall(blob or ""):
        if k == key:
            return v.strip()
    return None
