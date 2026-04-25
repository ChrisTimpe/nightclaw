"""nightclaw_engine.commands.audit — observability, detection, pruning.

Nine commands spanning T0, T3, T7, T8:

* ``audit-spine``         — T8: T0→T4→T9 sequence check per session
* ``audit-anomalies``     — T8: AUDIT-LOG anomaly scan
* ``crash-detect``        — T0: cross-ref SESSION-REGISTRY vs AUDIT-LOG
* ``crash-context``       — T0: retrieve crashed session context
* ``prune-candidates``    — T8.3: NOTIFICATIONS entries eligible for pruning
* ``t7-dedup``            — T7: duplicate-signal check
* ``change-detect``       — T3: worker-vs-manager pass divergence
* ``timing-check``        — T0: worker-session recency check
* ``transition-expiry``   — T2: TRANSITION-HOLD expiry
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import _shared


def cmd_timing_check():
    """Check if most recent worker session is still in progress or too recent.
    Output: CONTINUE, DEFER:worker_in_progress, or DEFER:worker_too_recent
    """
    content = _shared.read_file("audit/SESSION-REGISTRY.md")
    if content is None:
        print("CONTINUE reason=no_session_registry")
        return

    # Find all worker entries — look for session=worker or session:nightclaw-worker
    worker_entries = []
    for line in content.splitlines():
        if "worker" in line.lower():
            # Try to extract timestamp and outcome
            ts_m = re.search(r'(\d{4}-\d{2}-\d{2}T[\d:]+Z?)', line)
            outcome_m = re.search(r'outcome[=:]\s*(\S+)', line, re.IGNORECASE)
            if ts_m:
                dt = _shared.parse_iso(ts_m.group(1))
                outcome = outcome_m.group(1) if outcome_m else ""
                if dt:
                    worker_entries.append((dt, outcome, line.strip()))

    if not worker_entries:
        print("CONTINUE reason=no_worker_sessions_found")
        return

    # Sort by timestamp descending — most recent first
    worker_entries.sort(key=lambda x: x[0], reverse=True)
    most_recent_dt, most_recent_outcome, most_recent_line = worker_entries[0]

    now = _shared.now_utc()
    age_seconds = (now - most_recent_dt).total_seconds()

    # Check if outcome is empty (worker still writing)
    if not most_recent_outcome or most_recent_outcome in ("", "—", "-"):
        print(f"DEFER:worker_in_progress age={age_seconds:.0f}s")
        sys.exit(1)

    # Check if < 5 minutes ago
    if age_seconds < 300:
        print(f"DEFER:worker_too_recent age={age_seconds:.0f}s")
        sys.exit(1)

    print(f"CONTINUE last_worker={most_recent_dt.isoformat()} age={age_seconds:.0f}s")
    sys.exit(0)

def cmd_crash_detect():
    """Cross-reference SESSION-REGISTRY and AUDIT-LOG for crashed sessions.
    A crash = AUDIT-LOG has T4.CHECKPOINT for a run_id but SESSION-REGISTRY
    has no matching entry (T9 never ran).
    Output: CRASH:<run_id>:<slug> or CLEAN
    """
    registry = _shared.read_file("audit/SESSION-REGISTRY.md")
    audit_log = _shared.read_file("audit/AUDIT-LOG.md")

    if registry is None or audit_log is None:
        print("CLEAN reason=files_not_found")
        return

    # Extract all run_ids from SESSION-REGISTRY
    registered_runs = set()
    for m in re.finditer(r'(RUN-\d{8}-\d{3})', registry):
        registered_runs.add(m.group(1))

    # Extract run_ids that have T4 CHECKPOINT entries in AUDIT-LOG
    # Format: TASK:RUN-YYYYMMDD-NNN.T4 | TYPE:CHECKPOINT | ...
    checkpoint_runs = {}
    for line in audit_log.splitlines():
        m = re.search(r'TASK:(RUN-\d{8}-\d{3})\.T4\s*\|.*TYPE:CHECKPOINT', line)
        if m:
            run_id = m.group(1)
            # Try to extract PROJECT slug
            slug_m = re.search(r'PROJECT:(\S+)', line)
            slug = slug_m.group(1) if slug_m else "unknown"
            checkpoint_runs[run_id] = slug

    # Also find runs that have T0 but no T4 (routing halt — expected, not a crash)
    t0_runs = set()
    for line in audit_log.splitlines():
        m = re.search(r'TASK:(RUN-\d{8}-\d{3})\.(T0|STARTUP)', line)
        if m:
            t0_runs.add(m.group(1))

    # Find crashes: has T4 CHECKPOINT but not in SESSION-REGISTRY
    crashes = []
    for run_id, slug in checkpoint_runs.items():
        if run_id not in registered_runs:
            crashes.append((run_id, slug))

    # Find routing halts: has T0 but no T4 and not in registry
    routing_halts = []
    for run_id in t0_runs:
        if run_id not in registered_runs and run_id not in checkpoint_runs:
            routing_halts.append(run_id)

    if crashes:
        for run_id, slug in crashes:
            print(f"CRASH:{run_id}:project={slug}")
        print(f"TOTAL_CRASHES:{len(crashes)}")
    else:
        print("CLEAN")

    if routing_halts:
        for run_id in routing_halts:
            print(f"ROUTING_HALT:{run_id}")

def cmd_transition_expiry():
    """Check TRANSITION-HOLD projects for expiry.
    Reads ACTIVE-PROJECTS.md for TRANSITION-HOLD rows,
    then reads each LONGRUNNER for transition_expires.
    Output: EXPIRED:<slug>:reescalation_count=<n> or ALL_CURRENT
    """
    rows = _shared.parse_dispatch_table()
    if not rows:
        print("ALL_CURRENT reason=file_not_found")
        return

    now = _shared.now_utc()
    found_any = False

    for row in rows:
        status = row.get("status", "").strip().upper()
        if status != "TRANSITION-HOLD":
            continue

        slug = row.get("project_slug", row.get("slug", "")).strip()
        # Read LONGRUNNER for transition data
        lr = _shared.parse_longrunner(slug)
        if lr is None:
            print(f"MISSING_LONGRUNNER:{slug}")
            continue

        expires_str = lr.get("transition_expires")
        triggered_str = lr.get("transition_triggered_at")
        reesc_count = int(lr.get("transition_reescalation_count", "0") or "0")

        expires_dt = _shared.parse_iso(expires_str)
        triggered_dt = _shared.parse_iso(triggered_str)

        # Fallback per spec: if expires is blank, use triggered + 3 days
        if expires_dt is None and triggered_dt is not None:
            expires_dt = triggered_dt + timedelta(days=3)

        if expires_dt is None:
            print(f"SKIP:{slug} reason=no_transition_dates")
            continue

        if now > expires_dt:
            found_any = True
            print(f"EXPIRED:{slug} reescalation_count={reesc_count} expires={expires_str} triggered={triggered_str}")
            if reesc_count >= 3:
                print(f"  ACTION:AUTO_PAUSE {slug}")
            else:
                print(f"  ACTION:REESCALATE {slug} next_count={reesc_count + 1}")
        else:
            remaining = (expires_dt - now).total_seconds() / 3600
            print(f"CURRENT:{slug} expires_in={remaining:.1f}h")

    if not found_any:
        print("ALL_CURRENT")

def cmd_change_detect():
    """Compare ACTIVE-PROJECTS last_worker_pass vs MANAGER-REVIEW-REGISTRY last_review_date.
    Output: NEW_ACTIVITY:<slug> or NO_CHANGES
    """
    rows = _shared.parse_dispatch_table()
    mrr_content = _shared.read_file("PROJECTS/MANAGER-REVIEW-REGISTRY.md")

    if not rows:
        print("NO_CHANGES reason=ACTIVE-PROJECTS_not_found")
        return

    # Filter for active rows with last_worker_pass
    active_projects = {}
    for row in rows:
        status = row.get("status", "").strip().upper()
        if status == "ACTIVE":
            slug = row.get("project_slug", row.get("slug", "")).strip()
            lwp = row.get("last_worker_pass", "").strip()
            active_projects[slug] = _shared.parse_iso(lwp)

    if not active_projects:
        print("NO_ACTIVE_PROJECTS")
        return

    # Parse MANAGER-REVIEW-REGISTRY for last review dates per slug
    last_reviews = {}
    if mrr_content:
        for line in mrr_content.splitlines():
            # Typical row: | date | slug | decision | ...
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2:
                date_str = cells[0]
                slug = cells[1]
                dt = _shared.parse_iso(date_str)
                if dt and slug:
                    if slug not in last_reviews or dt > last_reviews[slug]:
                        last_reviews[slug] = dt

    new_activity = []
    for slug, worker_dt in active_projects.items():
        review_dt = last_reviews.get(slug)
        if worker_dt is None:
            print(f"SKIP:{slug} reason=no_worker_pass_timestamp")
            continue
        if review_dt is None or worker_dt > review_dt:
            new_activity.append(slug)
            print(f"NEW_ACTIVITY:{slug} worker_pass={worker_dt} last_review={review_dt}")
        else:
            print(f"CURRENT:{slug} worker_pass={worker_dt} last_review={review_dt}")

    if not new_activity:
        print("NO_CHANGES")

def cmd_audit_spine():
    """Validate T0→T4→T9 sequence for each worker session since last manager review.
    Output: CLEAN_PASS:<run_id> | ROUTING_HALT:<run_id> | CRASH:<run_id>:<slug>
    """
    audit_log = _shared.read_file("audit/AUDIT-LOG.md")
    if audit_log is None:
        print("SKIP reason=AUDIT-LOG_not_found")
        return

    # Optional: read last manager review date
    last_review_arg = sys.argv[3] if len(sys.argv) > 3 else None
    last_review_dt = _shared.parse_iso(last_review_arg) if last_review_arg else None

    # Collect events per run_id for worker sessions
    run_events = defaultdict(set)
    run_slugs = {}
    for line in audit_log.splitlines():
        # Match TASK:RUN-YYYYMMDD-NNN.Tstep
        m = re.search(r'TASK:(RUN-\d{8}-\d{3})\.(T\d+\S*)', line)
        if not m:
            continue
        run_id = m.group(1)
        step = m.group(2)

        # Determine if worker session
        if "session=worker" in line.lower() or "session:nightclaw-worker" in line.lower():
            run_events[run_id].add(step)
        elif not any(tag in line.lower() for tag in ["session=manager", "session:nightclaw-manager"]):
            # Default: assume worker if not explicitly manager
            run_events[run_id].add(step)

        # Extract project slug from T4 CHECKPOINT
        if "T4" in step and "CHECKPOINT" in line:
            slug_m = re.search(r'PROJECT:(\S+)', line)
            if slug_m:
                run_slugs[run_id] = slug_m.group(1).rstrip("|")

    if not run_events:
        print("NO_SESSIONS_FOUND")
        return

    crashes = 0
    clean = 0
    halts = 0
    for run_id in sorted(run_events.keys()):
        events = run_events[run_id]
        has_t0 = any(e.startswith("T0") or e == "STARTUP" for e in events)
        has_t4 = any(e.startswith("T4") for e in events)
        has_t9 = any(e.startswith("T9") for e in events)
        slug = run_slugs.get(run_id, "none")

        if has_t0 and has_t4 and has_t9:
            print(f"CLEAN_PASS:{run_id}")
            clean += 1
        elif has_t0 and has_t4 and not has_t9:
            print(f"CRASH:{run_id}:project={slug}")
            crashes += 1
        elif has_t0 and not has_t4:
            print(f"ROUTING_HALT:{run_id}")
            halts += 1
        else:
            print(f"UNKNOWN:{run_id} events={sorted(events)}")

    print(f"SUMMARY: clean={clean} crashes={crashes} routing_halts={halts}")
    if crashes > 0:
        sys.exit(1)

def cmd_audit_anomalies():
    """Scan AUDIT-LOG for anomaly patterns.
    Output: ANOMALY:<severity>:<type>:<details> or CLEAN
    """
    audit_log = _shared.read_file("audit/AUDIT-LOG.md")
    if audit_log is None:
        print("CLEAN reason=AUDIT-LOG_not_found")
        return

    # Define protected files from R3
    protected_prefixes = [
        "SOUL.md", "USER.md", "IDENTITY.md", "MEMORY.md", "AGENTS-CORE.md",
        "orchestration-os/CRON-WORKER-PROMPT.md", "orchestration-os/CRON-MANAGER-PROMPT.md",
        "orchestration-os/OPS-PREAPPROVAL.md", "orchestration-os/OPS-AUTONOMOUS-SAFETY.md",
        "orchestration-os/CRON-HARDLINES.md", "orchestration-os/REGISTRY.md"
    ]

    anomalies = []

    for i, line in enumerate(audit_log.splitlines()):
        line_num = i + 1

        # 1. FILE_WRITE to PROTECTED without {OWNER} auth
        if "TYPE:FILE_WRITE" in line:
            for pf in protected_prefixes:
                if f"FILE:{pf}" in line or f"FILE: {pf}" in line:
                    if "{OWNER}" not in line and "owner" not in line.lower():
                        anomalies.append(f"ANOMALY:CRITICAL:PROTECTED_WRITE_NO_AUTH:line={line_num}:file={pf}")

        # 2. INTEGRITY_CHECK FAIL
        if "INTEGRITY_CHECK" in line and "RESULT:FAIL" in line:
            # Check if surfaced to NOTIFICATIONS
            anomalies.append(f"ANOMALY:CRITICAL:INTEGRITY_FAIL:line={line_num}:verify_notification_exists")

        # 3. PA_INVOKE without APPROVAL-CHAIN match
        if "pa_invoke" in line.lower() and "RESULT:SUCCESS" in line:
            # Extract PA-NNN
            pa_m = re.search(r'PA-(\d{3})', line)
            if pa_m:
                anomalies.append(f"ANOMALY:HIGH:PA_INVOKE_VERIFY:line={line_num}:pa=PA-{pa_m.group(1)}:check_approval_chain")

        # 4. Session tokens > 80,000
        token_m = re.search(r'tokens[=:]\s*(\d+)', line, re.IGNORECASE)
        if token_m:
            tokens = int(token_m.group(1))
            if tokens > 80000:
                run_m = re.search(r'(RUN-\d{8}-\d{3})', line)
                run_id = run_m.group(1) if run_m else "unknown"
                anomalies.append(f"ANOMALY:MEDIUM:HIGH_TOKEN_SESSION:line={line_num}:run={run_id}:tokens={tokens}")

        # 5. CONSTRAINT_VIOLATION
        if "CONSTRAINT_VIOLATION" in line:
            anomalies.append(f"ANOMALY:HIGH:CONSTRAINT_VIOLATION:line={line_num}")

    if anomalies:
        for a in anomalies:
            print(a)
        print(f"TOTAL_ANOMALIES:{len(anomalies)}")
        sys.exit(1)
    else:
        print("CLEAN")
        sys.exit(0)

def cmd_prune_candidates():
    """Identify NOTIFICATIONS.md entries eligible for pruning.
    Rules: [DONE]=immediate, INFO>7d, LOW>14d, MEDIUM/HIGH/CRITICAL>30d, any>90d
    Output: PRUNE:line=<n>:<reason> or NONE
    """
    content = _shared.read_file("NOTIFICATIONS.md")
    if content is None:
        print("NONE reason=file_not_found")
        return

    now = _shared.now_utc()
    candidates = []
    in_alerts = False

    for i, line in enumerate(content.splitlines()):
        line_stripped = line.strip()
        line_num = i + 1

        # Track section
        if "## Current Alerts" in line or "## current alerts" in line.lower():
            in_alerts = True
            continue
        if not in_alerts:
            continue
        if line_stripped.startswith("##"):
            break  # new section
        if not line_stripped or line_stripped.startswith("---"):
            continue

        # Check [DONE]
        if line_stripped.startswith("[DONE"):
            candidates.append((line_num, "done_marker", line_stripped[:80]))
            continue

        # Extract timestamp from entry
        ts_m = re.search(r'(\d{4}-\d{2}-\d{2}T[\d:]+Z?)', line_stripped)
        if not ts_m:
            # Try date-only format
            ts_m = re.search(r'(\d{4}-\d{2}-\d{2})', line_stripped)
        if not ts_m:
            continue

        entry_dt = _shared.parse_iso(ts_m.group(1))
        if entry_dt is None:
            continue

        age_days = (now - entry_dt).total_seconds() / 86400

        # Extract priority
        pri_m = re.search(r'Priority:\s*(INFO|LOW|MEDIUM|HIGH|CRITICAL)', line_stripped, re.IGNORECASE)
        priority = pri_m.group(1).upper() if pri_m else "UNKNOWN"

        # Apply rules
        reason = None
        if age_days > 90:
            reason = f"age>90d ({age_days:.0f}d)"
        elif priority == "INFO" and age_days > 7:
            reason = f"INFO>7d ({age_days:.0f}d)"
        elif priority == "LOW" and age_days > 14:
            reason = f"LOW>14d ({age_days:.0f}d)"
        elif priority in ("MEDIUM", "HIGH", "CRITICAL") and age_days > 30:
            reason = f"{priority}>30d ({age_days:.0f}d)"

        if reason:
            candidates.append((line_num, reason, line_stripped[:80]))

    if candidates:
        for line_num, reason, preview in candidates:
            print(f"PRUNE:line={line_num}:reason={reason}:{preview}")
        print(f"TOTAL_CANDIDATES:{len(candidates)}")
    else:
        print("NONE")

def cmd_t7_dedup():
    """Check if a T7 signal is already documented in the target file.
    Usage: nightclaw-ops.py t7-dedup <target-file> <signal-text>
    Performs fuzzy substring matching against existing entries.
    Output: DUPLICATE:<entry_id>:<match_preview> or NOVEL
    """
    if len(sys.argv) < 4:
        print("ERROR: usage: t7-dedup <target-file> <signal-text>", file=sys.stderr)
        sys.exit(2)

    target_file = sys.argv[2]
    signal_text = " ".join(sys.argv[3:])  # Allow multi-word signal text

    content = _shared.read_file(target_file)
    if content is None:
        # File doesn't exist yet — signal is novel by definition
        print(f"NOVEL reason=target_file_not_found:{target_file}")
        return

    # Normalize signal for matching
    signal_lower = signal_text.lower().strip()
    signal_words = set(re.findall(r'\b\w{4,}\b', signal_lower))  # words 4+ chars

    if not signal_words:
        print("NOVEL reason=signal_too_short_for_matching")
        return

    # Scan the file for matching entries
    best_match = None
    best_score = 0
    best_preview = ""
    best_id = "unknown"

    lines = content.splitlines()
    current_entry_id = None
    current_entry_text = []

    for line in lines:
        # Detect entry boundaries
        # OPS-FAILURE-MODES: ### FM-NNN
        fm_m = re.match(r'^### (FM-\d+)', line)
        if fm_m:
            # Score previous entry if it exists
            if current_entry_id and current_entry_text:
                entry_text = " ".join(current_entry_text).lower()
                entry_words = set(re.findall(r'\b\w{4,}\b', entry_text))
                if signal_words and entry_words:
                    overlap = len(signal_words & entry_words)
                    score = overlap / len(signal_words)
                    if score > best_score:
                        best_score = score
                        best_match = current_entry_id
                        best_preview = entry_text[:120]
            current_entry_id = fm_m.group(1)
            current_entry_text = []
            continue

        # AGENTS-LESSONS: date-prefixed lines
        lesson_m = re.match(r'^(\d{4}-\d{2}-\d{2}):', line)
        if lesson_m:
            # Score previous entry
            if current_entry_id and current_entry_text:
                entry_text = " ".join(current_entry_text).lower()
                entry_words = set(re.findall(r'\b\w{4,}\b', entry_text))
                if signal_words and entry_words:
                    overlap = len(signal_words & entry_words)
                    score = overlap / len(signal_words)
                    if score > best_score:
                        best_score = score
                        best_match = current_entry_id
                        best_preview = entry_text[:120]
            current_entry_id = f"lesson-{lesson_m.group(1)}"
            current_entry_text = [line]
            continue

        # OPS-TOOL-REGISTRY: table rows with dates
        tool_m = re.match(r'^\|\s*(\d{4}-\d{2}-\d{2})\s*\|', line)
        if tool_m:
            if current_entry_id and current_entry_text:
                entry_text = " ".join(current_entry_text).lower()
                entry_words = set(re.findall(r'\b\w{4,}\b', entry_text))
                if signal_words and entry_words:
                    overlap = len(signal_words & entry_words)
                    score = overlap / len(signal_words)
                    if score > best_score:
                        best_score = score
                        best_match = current_entry_id
                        best_preview = entry_text[:120]
            current_entry_id = f"tool-{tool_m.group(1)}"
            current_entry_text = [line]
            continue

        # Accumulate text for current entry
        if current_entry_id:
            current_entry_text.append(line)

    # Score the last entry
    if current_entry_id and current_entry_text:
        entry_text = " ".join(current_entry_text).lower()
        entry_words = set(re.findall(r'\b\w{4,}\b', entry_text))
        if signal_words and entry_words:
            overlap = len(signal_words & entry_words)
            score = overlap / len(signal_words)
            if score > best_score:
                best_score = score
                best_match = current_entry_id
                best_preview = entry_text[:120]

    # Threshold: 50% word overlap = duplicate
    if best_score >= 0.5 and best_match:
        print(f"DUPLICATE:{best_match}:score={best_score:.2f}:{best_preview}")
    else:
        if best_match:
            print(f"NOVEL closest={best_match}:score={best_score:.2f}")
        else:
            print("NOVEL reason=no_entries_in_file")

def cmd_crash_context():
    """Retrieve context from a crashed session for recovery.
    Usage: nightclaw-ops.py crash-context <run_id>
    Returns the project, objective, and last known state of a crashed session.
    Helps the next pass avoid repeating the same crash-inducing objective.
    """
    if len(sys.argv) < 3:
        print("ERROR: usage: crash-context <run_id>", file=sys.stderr)
        sys.exit(2)

    target_run = sys.argv[2]

    audit_log = _shared.read_file("audit/AUDIT-LOG.md")
    if audit_log is None:
        print(f"ERROR: audit/AUDIT-LOG.md not found")
        sys.exit(1)

    # Collect all entries for the target run
    run_entries = []
    project_slug = "unknown"
    last_objective = "unknown"
    last_step = "unknown"
    last_type = "unknown"
    last_result = "unknown"

    for line in audit_log.splitlines():
        if target_run not in line:
            continue
        run_entries.append(line.strip())

        # Extract project slug
        slug_m = re.search(r'PROJECT:(\S+)', line)
        if slug_m:
            project_slug = slug_m.group(1).rstrip("|")

        # Extract objective
        obj_m = re.search(r'OBJECTIVE:(.+?)(?:\||$)', line)
        if obj_m:
            last_objective = obj_m.group(1).strip()

        # Extract step info
        step_m = re.search(rf'TASK:{re.escape(target_run)}\.(T\S+)', line)
        if step_m:
            last_step = step_m.group(1)

        # Extract type and result
        type_m = re.search(r'TYPE:(\S+)', line)
        if type_m:
            last_type = type_m.group(1)
        result_m = re.search(r'RESULT:(\S+)', line)
        if result_m:
            last_result = result_m.group(1)

    if not run_entries:
        print(f"NOT_FOUND:{target_run}")
        sys.exit(1)

    print(f"RUN_ID:{target_run}")
    print(f"PROJECT:{project_slug}")
    print(f"LAST_OBJECTIVE:{last_objective}")
    print(f"LAST_STEP:{last_step}")
    print(f"LAST_TYPE:{last_type}")
    print(f"LAST_RESULT:{last_result}")
    print(f"TOTAL_ENTRIES:{len(run_entries)}")

    # Check if the same project+objective combination has crashed before
    crash_count = 0
    for line in audit_log.splitlines():
        if "LOCK_STALE" in line and project_slug in line:
            crash_count += 1
    if crash_count > 1:
        print(f"REPEAT_CRASH:project={project_slug}:prior_crashes={crash_count}")
        print("RECOMMENDATION:ESCALATE — same project has crashed multiple times")
    elif crash_count == 1:
        print(f"FIRST_CRASH:project={project_slug}")
        print("RECOMMENDATION:RETRY_WITH_MODIFIED_OBJECTIVE")
    else:
        print(f"NO_PRIOR_CRASHES:project={project_slug}")
        print("RECOMMENDATION:RETRY")

    # Check memory for crash context
    memory_dir = _shared.ROOT / "memory"
    if memory_dir.exists():
        # Check most recent memory file for notes about this run
        recent_memory = sorted(memory_dir.glob("????-??-??.md"), reverse=True)
        for mf in recent_memory[:3]:
            mcontent = mf.read_text(encoding="utf-8", errors="replace")
            if target_run in mcontent:
                # Extract the relevant line(s)
                for mline in mcontent.splitlines():
                    if target_run in mline:
                        print(f"MEMORY_NOTE:{mf.name}:{mline.strip()[:200]}")
                break


def cmd_os_file_sizes():
    """Report line counts for OS compounding files against bloat thresholds.

    Output per file: SIZE:<name>:<lines>:<status>  where status is OK or THRESHOLD_EXCEEDED.
    Thresholds: OPS-FAILURE-MODES.md >1500, OPS-KNOWLEDGE-EXECUTION.md >600,
    AGENTS-LESSONS.md >400, OPS-TOOL-REGISTRY.md >400.
    Final line: RESULT:OK or RESULT:THRESHOLD_EXCEEDED:<filenames>
    """
    import pathlib

    targets = [
        ("orchestration-os/OPS-FAILURE-MODES.md",     1500),
        ("orchestration-os/OPS-KNOWLEDGE-EXECUTION.md", 600),
        ("orchestration-os/OPS-TOOL-REGISTRY.md",       400),
        ("AGENTS-LESSONS.md",                            400),
    ]

    root = _shared.ROOT
    exceeded = []

    for rel, threshold in targets:
        p = pathlib.Path(root) / rel
        if not p.exists():
            print(f"SIZE:{rel}:MISSING:MISSING")
            continue
        lines = len(p.read_text(encoding="utf-8").splitlines())
        status = "OK" if lines <= threshold else "THRESHOLD_EXCEEDED"
        print(f"SIZE:{rel}:{lines}:{status}")
        if status == "THRESHOLD_EXCEEDED":
            exceeded.append(rel)

    if exceeded:
        print(f"RESULT:THRESHOLD_EXCEEDED:{'|'.join(exceeded)}")
    else:
        print("RESULT:OK")


__all__ = ["cmd_timing_check", "cmd_crash_detect", "cmd_transition_expiry", "cmd_change_detect", "cmd_audit_spine", "cmd_audit_anomalies", "cmd_prune_candidates", "cmd_t7_dedup", "cmd_crash_context", "cmd_os_file_sizes"]
