#!/usr/bin/env python3
"""
nightclaw-ops.py — Deterministic operations toolkit for NightClaw.
Replaces LLM reasoning with code for all structured checks.

Usage: python3 scripts/nightclaw-ops.py <command> [options]
Run from workspace root.

Commands:
  integrity-check     T0/T1: SHA256 verification against manifest
  next-run-id         STARTUP.3: Compute next RUN-YYYYMMDD-NNN
  dispatch            T1: Select highest-priority dispatchable project
  scan-notifications  T1.5: Find actionable notification entries
  timing-check        T0-manager: Check if worker session is too recent
  crash-detect        T0-manager: Cross-ref SESSION-REGISTRY vs AUDIT-LOG
  transition-expiry   T2-manager: Check TRANSITION-HOLD expiry dates
  change-detect       T3-manager: Compare worker passes vs manager reviews
  audit-spine         T8: Validate T0→T4→T9 sequence per session
  audit-anomalies     T8: Scan AUDIT-LOG for anomaly patterns
  prune-candidates    T8.3: Identify NOTIFICATIONS entries eligible for pruning
  scr-verify          T8: R6 self-consistency rules (SCR-01 through SCR-08)
  dispatch-validate   Field contract validation (R2 enums, NOT EMPTY, FK)

All output is machine-parseable. LLM reads output and acts on it.
LLM never does the computation itself.
"""

import sys
import os
import re
import hashlib
import pathlib
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def workspace_root():
    """Return workspace root (cwd or detect from script location)."""
    if os.path.isfile("LOCK.md") or os.path.isfile("SOUL.md"):
        return pathlib.Path(".")
    # Try parent of scripts/
    p = pathlib.Path(__file__).resolve().parent.parent
    if (p / "LOCK.md").exists() or (p / "SOUL.md").exists():
        return p
    print("ERROR: Run from workspace root or place script in scripts/", file=sys.stderr)
    sys.exit(2)

ROOT = None  # set in main()

def read_file(rel_path):
    """Read file relative to workspace root. Returns content or None."""
    fp = ROOT / rel_path
    if fp.exists():
        return fp.read_text(encoding="utf-8", errors="replace")
    return None

def parse_iso(s):
    """Parse ISO8601 timestamp string to datetime. Returns None on failure."""
    if not s or s.strip() in ("—", "-", "~", "null", "None", "none", ""):
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

def now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# integrity-check: T0/T1 SHA256 verification
# ---------------------------------------------------------------------------

def cmd_integrity_check():
    """Compare SHA256 hashes of all protected files against manifest.
    Output: one line per file: PASS|FAIL|MISSING <filepath> [computed] [expected]
    Final line: RESULT:PASS or RESULT:FAIL count=N
    """
    manifest = read_file("audit/INTEGRITY-MANIFEST.md")
    if manifest is None:
        print("ERROR: audit/INTEGRITY-MANIFEST.md not found")
        sys.exit(1)

    # Parse manifest: extract filepath → hash pairs
    # Format: | `filepath` | hash | ... OR | `filepath` | `hash` | ...
    manifest_hashes = {}
    for line in manifest.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= 2:
            fpath = cells[0].strip("`").strip()
            h = cells[1].strip("`").strip()
            if len(h) == 64 and all(c in "0123456789abcdef" for c in h):
                manifest_hashes[fpath] = h

    if not manifest_hashes:
        print("ERROR: No hash entries found in manifest")
        sys.exit(1)

    fail_count = 0
    pass_count = 0
    for fpath, expected_hash in sorted(manifest_hashes.items()):
        full = ROOT / fpath
        if not full.exists():
            print(f"MISSING {fpath}")
            fail_count += 1
            continue
        computed = hashlib.sha256(full.read_bytes()).hexdigest()
        if computed == expected_hash:
            print(f"PASS {fpath}")
            pass_count += 1
        else:
            print(f"FAIL {fpath} computed={computed} expected={expected_hash}")
            fail_count += 1

    if fail_count > 0:
        print(f"RESULT:FAIL pass={pass_count} fail={fail_count}")
        sys.exit(1)
    else:
        print(f"RESULT:PASS files={pass_count}")
        sys.exit(0)


# ---------------------------------------------------------------------------
# next-run-id: STARTUP.3
# ---------------------------------------------------------------------------

def cmd_next_run_id():
    """Compute next RUN-YYYYMMDD-NNN from SESSION-REGISTRY.
    Output: RUN-YYYYMMDD-NNN
    """
    session_arg = sys.argv[3] if len(sys.argv) > 3 else None
    content = read_file("audit/SESSION-REGISTRY.md")
    if content is None:
        # First run ever
        today = now_utc().strftime("%Y%m%d")
        print(f"RUN-{today}-001")
        return

    today = now_utc().strftime("%Y%m%d")
    # Count entries with today's date
    pattern = re.compile(rf'RUN-{today}-(\d{{3}})')
    max_n = 0
    for m in pattern.finditer(content):
        n = int(m.group(1))
        if n > max_n:
            max_n = n

    next_n = max_n + 1
    print(f"RUN-{today}-{next_n:03d}")


# ---------------------------------------------------------------------------
# dispatch: T1 project selection
# ---------------------------------------------------------------------------

def cmd_dispatch():
    """Parse ACTIVE-PROJECTS.md, return highest-priority dispatchable project.
    Output: DISPATCH:<slug> or IDLE (no dispatchable project)
    Also outputs the full parsed table for context.
    """
    content = read_file("ACTIVE-PROJECTS.md")
    if content is None:
        print("IDLE reason=ACTIVE-PROJECTS.md_not_found")
        return

    # Parse markdown table rows
    rows = []
    header_found = False
    headers = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]  # strip outer empty splits
        if not header_found:
            headers = [c.lower().replace(" ", "_") for c in cells]
            header_found = True
            continue
        # Skip separator row
        if cells and all(set(c.strip()) <= {"-", ":"} for c in cells):
            continue
        if len(cells) >= len(headers):
            row = dict(zip(headers, cells))
            rows.append(row)

    if not rows:
        print("IDLE reason=no_rows_in_table")
        return

    # Find dispatchable: status=ACTIVE (case-insensitive) AND
    # (escalation_pending=none OR escalation_pending starts with surfaced-)
    candidates = []
    for row in rows:
        status = row.get("status", "").strip().upper()
        esc = row.get("escalation_pending", "").strip().lower()
        slug = row.get("project_slug", row.get("slug", "")).strip()
        priority = row.get("priority", "999").strip()

        if status != "ACTIVE":
            print(f"SKIP {slug} status={status}")
            continue
        if esc not in ("none", "") and not esc.startswith("surfaced-"):
            print(f"SKIP {slug} escalation_pending={esc}")
            continue

        try:
            pri = int(priority)
        except ValueError:
            pri = 999

        candidates.append((pri, slug, row))

    if not candidates:
        print("IDLE reason=no_active_dispatchable_projects")
        return

    candidates.sort(key=lambda x: x[0])
    best = candidates[0]
    print(f"DISPATCH:{best[1]} priority={best[0]}")
    # Also list all candidates for context
    for pri, slug, _ in candidates:
        print(f"  candidate: {slug} priority={pri}")


# ---------------------------------------------------------------------------
# scan-notifications: T1.5
# ---------------------------------------------------------------------------

def cmd_scan_notifications():
    """Scan NOTIFICATIONS.md for worker-actionable entries.
    Output: FOUND:<index>:<priority>:<summary> or NONE
    """
    content = read_file("NOTIFICATIONS.md")
    if content is None:
        print("NONE reason=file_not_found")
        return

    actionable_tags = [
        "WORKER-ACTION-REQUIRED", "PENDING-LESSON",
        "AUDIT-FLAG", "SESSION-SUMMARY"
    ]

    entries = []
    for i, line in enumerate(content.splitlines()):
        line_stripped = line.strip()
        # Skip done entries
        if line_stripped.startswith("[DONE]"):
            continue
        # Skip headers, empty lines, HTML comments, and separators
        if not line_stripped or line_stripped.startswith("#") or line_stripped.startswith("---"):
            continue
        if line_stripped.startswith("<!--") or line_stripped.startswith("//"):
            continue
        # Check for actionable tags
        for tag in actionable_tags:
            if tag in line_stripped.upper():
                entries.append((i + 1, line_stripped[:120]))
                break

    if not entries:
        print("NONE reason=no_actionable_entries")
    else:
        for line_num, summary in entries:
            print(f"FOUND:line={line_num}:{summary}")
        print(f"TOTAL:{len(entries)}")


# ---------------------------------------------------------------------------
# timing-check: Manager T0 — worker recency check
# ---------------------------------------------------------------------------

def cmd_timing_check():
    """Check if most recent worker session is still in progress or too recent.
    Output: CONTINUE, DEFER:worker_in_progress, or DEFER:worker_too_recent
    """
    content = read_file("audit/SESSION-REGISTRY.md")
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
                dt = parse_iso(ts_m.group(1))
                outcome = outcome_m.group(1) if outcome_m else ""
                if dt:
                    worker_entries.append((dt, outcome, line.strip()))

    if not worker_entries:
        print("CONTINUE reason=no_worker_sessions_found")
        return

    # Sort by timestamp descending — most recent first
    worker_entries.sort(key=lambda x: x[0], reverse=True)
    most_recent_dt, most_recent_outcome, most_recent_line = worker_entries[0]

    now = now_utc()
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


# ---------------------------------------------------------------------------
# crash-detect: Manager T0
# ---------------------------------------------------------------------------

def cmd_crash_detect():
    """Cross-reference SESSION-REGISTRY and AUDIT-LOG for crashed sessions.
    A crash = AUDIT-LOG has T4.CHECKPOINT for a run_id but SESSION-REGISTRY
    has no matching entry (T9 never ran).
    Output: CRASH:<run_id>:<slug> or CLEAN
    """
    registry = read_file("audit/SESSION-REGISTRY.md")
    audit_log = read_file("audit/AUDIT-LOG.md")

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


# ---------------------------------------------------------------------------
# transition-expiry: Manager T2
# ---------------------------------------------------------------------------

def cmd_transition_expiry():
    """Check TRANSITION-HOLD projects for expiry.
    Reads ACTIVE-PROJECTS.md for TRANSITION-HOLD rows,
    then reads each LONGRUNNER for transition_expires.
    Output: EXPIRED:<slug>:reescalation_count=<n> or ALL_CURRENT
    """
    content = read_file("ACTIVE-PROJECTS.md")
    if content is None:
        print("ALL_CURRENT reason=file_not_found")
        return

    now = now_utc()
    found_any = False

    # Parse table for TRANSITION-HOLD rows
    header_found = False
    headers = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not header_found:
            headers = [c.lower().replace(" ", "_") for c in cells]
            header_found = True
            continue
        if cells and all(set(c.strip()) <= {"-", ":"} for c in cells):
            continue
        if len(cells) >= len(headers):
            row = dict(zip(headers, cells))
        else:
            continue

        status = row.get("status", "").strip().upper()
        if status != "TRANSITION-HOLD":
            continue

        slug = row.get("project_slug", row.get("slug", "")).strip()
        # Read LONGRUNNER for transition data
        longrunner = read_file(f"PROJECTS/{slug}/LONGRUNNER.md")
        if longrunner is None:
            print(f"MISSING_LONGRUNNER:{slug}")
            continue

        # Parse transition fields
        expires_str = None
        triggered_str = None
        reesc_count = 0
        for lr_line in longrunner.splitlines():
            if "transition_expires" in lr_line.lower():
                m = re.search(r':\s*(.+)', lr_line)
                if m:
                    expires_str = m.group(1).strip()
            if "transition_triggered_at" in lr_line.lower():
                m = re.search(r':\s*(.+)', lr_line)
                if m:
                    triggered_str = m.group(1).strip()
            if "transition_reescalation_count" in lr_line.lower():
                m = re.search(r':\s*(\d+)', lr_line)
                if m:
                    reesc_count = int(m.group(1))

        expires_dt = parse_iso(expires_str)
        triggered_dt = parse_iso(triggered_str)

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


# ---------------------------------------------------------------------------
# change-detect: Manager T3
# ---------------------------------------------------------------------------

def cmd_change_detect():
    """Compare ACTIVE-PROJECTS last_worker_pass vs MANAGER-REVIEW-REGISTRY last_review_date.
    Output: NEW_ACTIVITY:<slug> or NO_CHANGES
    """
    ap_content = read_file("ACTIVE-PROJECTS.md")
    mrr_content = read_file("PROJECTS/MANAGER-REVIEW-REGISTRY.md")

    if ap_content is None:
        print("NO_CHANGES reason=ACTIVE-PROJECTS_not_found")
        return

    # Parse ACTIVE-PROJECTS for active rows with last_worker_pass
    header_found = False
    headers = []
    active_projects = {}
    for line in ap_content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not header_found:
            headers = [c.lower().replace(" ", "_") for c in cells]
            header_found = True
            continue
        if cells and all(set(c.strip()) <= {"-", ":"} for c in cells):
            continue
        if len(cells) >= len(headers):
            row = dict(zip(headers, cells))
        else:
            continue
        status = row.get("status", "").strip().upper()
        if status == "ACTIVE":
            slug = row.get("project_slug", row.get("slug", "")).strip()
            lwp = row.get("last_worker_pass", "").strip()
            active_projects[slug] = parse_iso(lwp)

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
                dt = parse_iso(date_str)
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


# ---------------------------------------------------------------------------
# audit-spine: Manager T8
# ---------------------------------------------------------------------------

def cmd_audit_spine():
    """Validate T0→T4→T9 sequence for each worker session since last manager review.
    Output: CLEAN_PASS:<run_id> | ROUTING_HALT:<run_id> | CRASH:<run_id>:<slug>
    """
    audit_log = read_file("audit/AUDIT-LOG.md")
    if audit_log is None:
        print("SKIP reason=AUDIT-LOG_not_found")
        return

    # Optional: read last manager review date
    last_review_arg = sys.argv[3] if len(sys.argv) > 3 else None
    last_review_dt = parse_iso(last_review_arg) if last_review_arg else None

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


# ---------------------------------------------------------------------------
# audit-anomalies: Manager T8
# ---------------------------------------------------------------------------

def cmd_audit_anomalies():
    """Scan AUDIT-LOG for anomaly patterns.
    Output: ANOMALY:<severity>:<type>:<details> or CLEAN
    """
    audit_log = read_file("audit/AUDIT-LOG.md")
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


# ---------------------------------------------------------------------------
# prune-candidates: Manager T8.3
# ---------------------------------------------------------------------------

def cmd_prune_candidates():
    """Identify NOTIFICATIONS.md entries eligible for pruning.
    Rules: [DONE]=immediate, INFO>7d, LOW>14d, MEDIUM/HIGH/CRITICAL>30d, any>90d
    Output: PRUNE:line=<n>:<reason> or NONE
    """
    content = read_file("NOTIFICATIONS.md")
    if content is None:
        print("NONE reason=file_not_found")
        return

    now = now_utc()
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
        if line_stripped.startswith("[DONE]"):
            candidates.append((line_num, "done_marker", line_stripped[:80]))
            continue

        # Extract timestamp from entry
        ts_m = re.search(r'(\d{4}-\d{2}-\d{2}T[\d:]+Z?)', line_stripped)
        if not ts_m:
            # Try date-only format
            ts_m = re.search(r'(\d{4}-\d{2}-\d{2})', line_stripped)
        if not ts_m:
            continue

        entry_dt = parse_iso(ts_m.group(1))
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


# ---------------------------------------------------------------------------
# scr-verify: Manager T8 registry self-consistency
# ---------------------------------------------------------------------------

def cmd_scr_verify():
    """R6 self-consistency rules SCR-01 through SCR-08.
    Output: SCR-NN:PASS|FAIL <details>
    """
    registry = read_file("orchestration-os/REGISTRY.md")
    if registry is None:
        print("ERROR: orchestration-os/REGISTRY.md not found")
        sys.exit(1)

    lines = registry.splitlines()

    # Parse sections
    sections = {}
    current_section = None
    for line in lines:
        m = re.match(r'^## (R\d+|CL\d+)', line)
        if m:
            current_section = m.group(1)
            sections[current_section] = []
        if current_section:
            sections[current_section].append(line)

    errors = []

    # SCR-01: R3 bundle refs → R5 defs
    r3_bundles = set()
    for line in sections.get("R3", []):
        for m in re.finditer(r'BUNDLE:(\w+)', line):
            r3_bundles.add(m.group(1))
    r5_defs = set()
    for line in sections.get("R5", []):
        m = re.match(r'^BUNDLE:(\w+)', line)
        if m:
            r5_defs.add(m.group(1))
    missing = r3_bundles - r5_defs
    if missing:
        print(f"SCR-01:FAIL missing_from_R5={missing}")
        errors.append("SCR-01")
    else:
        print(f"SCR-01:PASS count={len(r3_bundles)}")

    # SCR-02: FK→OBJ refs → R1 defs
    r1_objs = set()
    for line in sections.get("R1", []):
        m = re.match(r'^(OBJ:\w+)', line)
        if m:
            r1_objs.add(m.group(1))
    r2_fks = set()
    for line in sections.get("R2", []):
        for m in re.finditer(r'FK→(OBJ:\w+)', line):
            r2_fks.add(m.group(1))
    missing = r2_fks - r1_objs
    if missing:
        print(f"SCR-02:FAIL missing_from_R1={missing}")
        errors.append("SCR-02")
    else:
        print(f"SCR-02:PASS count={len(r2_fks)}")

    # SCR-03: PROTECTED files → VALIDATES edges
    r3_protected = set()
    for line in sections.get("R3", []):
        if "| PROTECTED" in line:
            parts = line.split("|")
            if parts:
                fname = re.sub(r'\(.*?\)', '', parts[0]).strip()
                if fname and not fname.startswith("#") and not fname.startswith("["):
                    r3_protected.add(fname)
    r4_validates = set()
    for line in sections.get("R4", []):
        m = re.search(r'→ VALIDATES → (.+)$', line)
        if m:
            r4_validates.add(m.group(1).strip())
    missing = r3_protected - r4_validates
    if missing:
        print(f"SCR-03:FAIL missing_validates_edge={missing}")
        errors.append("SCR-03")
    else:
        print(f"SCR-03:PASS count={len(r3_protected)}")

    # SCR-04: CHANGE-LOG exists (structural only — check file)
    if (ROOT / "audit/CHANGE-LOG.md").exists():
        print("SCR-04:PASS")
    else:
        print("SCR-04:FAIL audit/CHANGE-LOG.md_not_found")
        errors.append("SCR-04")

    # SCR-05: SESSION-REGISTRY unique run_ids
    sr_content = read_file("audit/SESSION-REGISTRY.md")
    if sr_content:
        run_ids = re.findall(r'(RUN-\d{8}-\d{3})', sr_content)
        dupes = [rid for rid in set(run_ids) if run_ids.count(rid) > 1]
        if dupes:
            print(f"SCR-05:FAIL duplicate_run_ids={dupes}")
            errors.append("SCR-05")
        else:
            print(f"SCR-05:PASS unique_count={len(set(run_ids))}")
    else:
        print("SCR-05:SKIP file_not_found")

    # SCR-06: R4 bundle refs → R5 defs
    r4_bundles = set()
    for line in sections.get("R4", []):
        for m in re.finditer(r'BUNDLE:(\w+)', line):
            r4_bundles.add(m.group(1))
    missing = r4_bundles - r5_defs
    if missing:
        print(f"SCR-06:FAIL missing_from_R5={missing}")
        errors.append("SCR-06")
    else:
        print(f"SCR-06:PASS count={len(r4_bundles)}")

    # SCR-07: REFERENCES consistency (structural — list edges for LLM to check content)
    ref_edges = []
    for line in sections.get("R4", []):
        m = re.search(r'(.+?)\s*→\s*REFERENCES\s*→\s*(.+)', line)
        if m:
            ref_edges.append((m.group(1).strip(), m.group(2).strip()))
    print(f"SCR-07:INFO reference_edges={len(ref_edges)}")
    for src, tgt in ref_edges:
        print(f"  REF: {src} → {tgt}")

    # SCR-08: LOCK.md structural
    lock_content = read_file("LOCK.md")
    if lock_content:
        has_status = "status:" in lock_content
        has_expires = "expires_at:" in lock_content
        if has_status and has_expires:
            print("SCR-08:PASS")
        else:
            print(f"SCR-08:FAIL status={has_status} expires_at={has_expires}")
            errors.append("SCR-08")
    else:
        print("SCR-08:SKIP LOCK.md_not_found")

    # CL5 cross-check
    cl5_paths = set()
    in_cl5 = False
    for line in lines:
        if 'PROTECTED-PATHS:' in line:
            in_cl5 = True
            continue
        if in_cl5:
            m = re.match(r'\s+FILE:(.+)', line.rstrip())
            if m:
                cl5_paths.add(m.group(1).strip())
            elif line.strip() and not line.strip().startswith('#'):
                break
    cl5_missing = r3_protected - cl5_paths
    if cl5_missing:
        print(f"CL5:FAIL missing_from_protected_paths={cl5_missing}")
        errors.append("CL5")
    else:
        print(f"CL5:PASS count={len(cl5_paths)}")

    # Summary
    if errors:
        print(f"RESULT:FAIL rules={errors}")
        sys.exit(1)
    else:
        print("RESULT:PASS")
        sys.exit(0)


# ---------------------------------------------------------------------------
# dispatch-validate: R2 field contract validation
# ---------------------------------------------------------------------------

def cmd_dispatch_validate():
    """Validate ACTIVE-PROJECTS.md against R2 field contracts.
    Checks: priority uniqueness, slug FK to PROJECTS dir, status enum, etc.
    Output: VALID or VIOLATION:<field>:<details>
    """
    content = read_file("ACTIVE-PROJECTS.md")
    if content is None:
        print("SKIP reason=file_not_found")
        return

    header_found = False
    headers = []
    rows = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not header_found:
            headers = [c.lower().replace(" ", "_") for c in cells]
            header_found = True
            continue
        if cells and all(set(c.strip()) <= {"-", ":"} for c in cells):
            continue
        if len(cells) >= len(headers):
            rows.append(dict(zip(headers, cells)))

    violations = []
    status_enum = {"ACTIVE", "BLOCKED", "PAUSED", "TRANSITION-HOLD", "COMPLETE", "ABANDONED"}
    priorities_seen = {}

    for row in rows:
        slug = row.get("project_slug", row.get("slug", "")).strip()
        status = row.get("status", "").strip().upper()
        priority = row.get("priority", "").strip()
        esc = row.get("escalation_pending", "").strip()

        # Skip placeholder/example rows
        if not slug or slug.startswith("_(") or slug == "\u2014" or status == "\u2014":
            continue

        # Status enum check
        if status and status not in status_enum:
            violations.append(f"VIOLATION:status:slug={slug}:value={status}:expected={status_enum}")

        # Priority uniqueness (among ACTIVE rows)
        if status == "ACTIVE" and priority:
            if priority in priorities_seen:
                violations.append(f"VIOLATION:priority_unique:slug={slug}:priority={priority}:conflicts_with={priorities_seen[priority]}")
            priorities_seen[priority] = slug

        # Slug FK → PROJECTS dir exists
        if slug:
            proj_dir = ROOT / "PROJECTS" / slug
            if not proj_dir.exists():
                violations.append(f"VIOLATION:slug_fk:slug={slug}:PROJECTS/{slug}/_not_found")

        # escalation_pending format
        if esc and esc.lower() not in ("none", ""):
            # Should be a string — just warn if empty when required
            pass

    if violations:
        for v in violations:
            print(v)
        print(f"TOTAL_VIOLATIONS:{len(violations)}")
        sys.exit(1)
    else:
        print("VALID")
        sys.exit(0)


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

COMMANDS = {
    "integrity-check": cmd_integrity_check,
    "next-run-id": cmd_next_run_id,
    "dispatch": cmd_dispatch,
    "scan-notifications": cmd_scan_notifications,
    "timing-check": cmd_timing_check,
    "crash-detect": cmd_crash_detect,
    "transition-expiry": cmd_transition_expiry,
    "change-detect": cmd_change_detect,
    "audit-spine": cmd_audit_spine,
    "audit-anomalies": cmd_audit_anomalies,
    "prune-candidates": cmd_prune_candidates,
    "scr-verify": cmd_scr_verify,
    "dispatch-validate": cmd_dispatch_validate,
}

def main():
    global ROOT
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        print("Commands:")
        for name, fn in COMMANDS.items():
            desc = (fn.__doc__ or "").strip().split("\n")[0]
            print(f"  {name:24s} {desc}")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(f"Available: {', '.join(COMMANDS.keys())}", file=sys.stderr)
        sys.exit(2)

    ROOT = workspace_root()
    COMMANDS[cmd]()

if __name__ == "__main__":
    main()
