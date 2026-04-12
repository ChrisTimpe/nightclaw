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
  longrunner-extract  T2: Extract machine-parseable fields from LONGRUNNER
  idle-triage         T1.5: Determine first actionable idle cycle tier
  strategic-context   T3.5-manager: Pre-digest strategic context for idle manager
  t7-dedup            T7: Check if a signal is already documented in target file
  crash-context       T0: Retrieve context from a crashed session for recovery
  append              Append a single line to an APPEND-ONLY file (safe exec-based alternative to Edit tool)
  append-batch        Append multiple lines to an APPEND-ONLY file in one call (||| delimited)

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


def check_pa_active(action_class):
    """Check if a pre-approval with the given action_class is ACTIVE and not expired.
    Returns True if a matching PA is active, False otherwise.
    Does NOT evaluate Boundary — that is the worker LLM's responsibility.
    """
    content = read_file("orchestration-os/OPS-PREAPPROVAL.md")
    if content is None:
        return False

    now = now_utc()
    # Parse PA entries: ## PA-NNN | Status: ACTIVE | Expires: YYYY-MM-DD
    pa_pattern = re.compile(
        r'^## (PA-\d+)\s*\|\s*Status:\s*(\S+)\s*\|\s*Expires:\s*(.+)',
        re.MULTILINE
    )
    action_pattern = re.compile(
        r'\*\*Action class:\*\*\s*(\S+)',
        re.MULTILINE
    )

    # Split into PA blocks
    blocks = re.split(r'(?=^## PA-\d+)', content, flags=re.MULTILINE)
    for block in blocks:
        header = pa_pattern.search(block)
        if not header:
            continue
        pa_id, status, expires_str = header.group(1), header.group(2).upper(), header.group(3).strip()
        if status != "ACTIVE":
            continue

        # Check action class
        action_match = action_pattern.search(block)
        if not action_match:
            continue
        if action_match.group(1).strip() != action_class:
            continue

        # Check expiry
        if expires_str in ("—", "-", "~", ""):
            continue  # No expiry set — treat as inactive
        try:
            # Parse date (YYYY-MM-DD) — expires at end of that day
            exp_date = datetime.strptime(expires_str.split()[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            exp_date = exp_date.replace(hour=23, minute=59, second=59)
            if now <= exp_date:
                return True
        except (ValueError, IndexError):
            continue  # Unparseable expiry — skip

    return False


def read_longrunner_successor(slug):
    """Read phase.successor from a project's LONGRUNNER. Returns empty string if not found."""
    content = read_file(f"PROJECTS/{slug}/LONGRUNNER.md")
    if content is None:
        return ""
    m = re.search(r'successor:\s*"([^"]+)"', content)
    if m:
        val = m.group(1).strip()
        if val and val != "~":
            return val
    return ""


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

    if candidates:
        candidates.sort(key=lambda x: x[0])
        best = candidates[0]
        print(f"DISPATCH:{best[1]} priority={best[0]}")
        # Also list all candidates for context
        for pri, slug, _ in candidates:
            print(f"  candidate: {slug} priority={pri}")
        return

    # No ACTIVE candidates. Check for TRANSITION-HOLD projects eligible for advance.
    advance_candidates = []
    for row in rows:
        status = row.get("status", "").strip().upper()
        esc = row.get("escalation_pending", "").strip().lower()
        slug = row.get("project_slug", row.get("slug", "")).strip()
        priority = row.get("priority", "999").strip()

        if status != "TRANSITION-HOLD":
            continue

        eligible = False

        # Path A: owner explicitly approved via nightclaw-admin done
        if esc == "transition-approved":
            eligible = True

        # Path B: PA-001 (phase-auto-transition) is active
        elif esc.startswith("phase-complete-"):
            if check_pa_active("phase-auto-transition"):
                eligible = True

        if not eligible:
            continue

        # Verify successor exists in LONGRUNNER
        successor = read_longrunner_successor(slug)
        if not successor:
            print(f"SKIP {slug} reason=no_successor_defined")
            continue

        try:
            pri = int(priority)
        except ValueError:
            pri = 999

        advance_candidates.append((pri, slug, row))

    if advance_candidates:
        advance_candidates.sort(key=lambda x: x[0])
        best = advance_candidates[0]
        print(f"ADVANCE:{best[1]} priority={best[0]}")
        for pri, slug, _ in advance_candidates:
            print(f"  candidate: {slug} priority={pri}")
        return

    print("IDLE reason=no_active_dispatchable_projects")


# ---------------------------------------------------------------------------
# scan-notifications: T1.5
# ---------------------------------------------------------------------------

def cmd_scan_notifications():
    """Scan NOTIFICATIONS.md for worker-actionable entries.
    Uses structural matching: any notification entry that is not [DONE],
    not LOW/INFO priority, and not a lock-defer or manager-deferred message
    is considered actionable. Also matches explicit actionable tags.
    Output: FOUND:line=<n>:<priority>:<summary> or NONE
    """
    content = read_file("NOTIFICATIONS.md")
    if content is None:
        print("NONE reason=file_not_found")
        return

    # Explicit actionable tags (original set)
    actionable_tags = [
        "WORKER-ACTION-REQUIRED", "PENDING-LESSON",
        "AUDIT-FLAG", "SESSION-SUMMARY"
    ]

    # Skip patterns — these are not actionable by the worker
    skip_patterns = [
        "[MANAGER DEFERRED]",
        "Worker startup deferred",
        "Manager startup deferred",
        "holds lock",
    ]

    # Non-actionable priorities for structural matching
    low_priorities = {"LOW", "INFO"}

    entries = []
    in_alerts = False
    in_code_block = False

    for i, line in enumerate(content.splitlines()):
        line_stripped = line.strip()
        line_num = i + 1

        # Track code blocks (skip template examples in Entry Formats section)
        if line_stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # Track section — only scan "## Current Alerts" and below
        if "## Current Alerts" in line or "## current alerts" in line.lower():
            in_alerts = True
            continue
        # Also accept "## Append new entries" as start of entries area
        if "append new entries" in line.lower():
            in_alerts = True
            continue
        if not in_alerts:
            continue

        # Skip done entries
        if line_stripped.startswith("[DONE"):
            continue
        # Skip headers, empty lines, HTML comments, and separators
        if not line_stripped or line_stripped.startswith("#") or line_stripped.startswith("---"):
            continue
        if line_stripped.startswith("<!--") or line_stripped.startswith("//"):
            continue
        # Skip lines with template placeholders
        if "[YYYY-MM-DD" in line_stripped or "[slug]" in line_stripped:
            continue
        # Skip table header and separator rows
        if line_stripped.startswith("| Priority") or line_stripped.startswith("| ---"):
            continue
        if all(c in "|- :" for c in line_stripped):
            continue

        # Skip known non-actionable patterns
        if any(skip in line_stripped for skip in skip_patterns):
            continue

        # Extract priority if present
        pri_m = re.search(r'Priority:\s*(INFO|LOW|MEDIUM|HIGH|CRITICAL)', line_stripped, re.IGNORECASE)
        priority = pri_m.group(1).upper() if pri_m else None

        # Method 1: Explicit actionable tags — always actionable regardless of priority
        has_tag = any(tag in line_stripped.upper() for tag in actionable_tags)
        if has_tag:
            entries.append((line_num, priority or "TAGGED", line_stripped[:120]))
            continue

        # Method 2: Structural matching — any entry with action_needed= or
        # MEDIUM/HIGH/CRITICAL priority is actionable
        if priority and priority not in low_priorities:
            entries.append((line_num, priority, line_stripped[:120]))
            continue

        # Method 3: Entries with explicit action_needed field
        if "action_needed" in line_stripped.lower():
            entries.append((line_num, priority or "ACTION", line_stripped[:120]))
            continue

        # Method 4: Entries that look like notification rows (have a timestamp
        # and pipe-delimited structure with substantive content)
        if "|" in line_stripped and re.search(r'\d{4}-\d{2}-\d{2}', line_stripped):
            # Has a date and pipes — likely a notification entry
            # Only skip if explicitly LOW/INFO
            if priority in low_priorities:
                continue
            # No priority extracted = unknown, treat as potentially actionable
            if priority is None:
                entries.append((line_num, "UNKNOWN", line_stripped[:120]))
                continue

    if not entries:
        print("NONE reason=no_actionable_entries")
    else:
        for line_num, priority, summary in entries:
            print(f"FOUND:line={line_num}:priority={priority}:{summary}")
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
# longrunner-extract: T2 — extract machine-parseable fields from LONGRUNNER
# ---------------------------------------------------------------------------

def cmd_longrunner_extract():
    """Extract routing-critical fields from a LONGRUNNER without requiring full file read.
    Usage: nightclaw-ops.py longrunner-extract <slug>
    Output: key=value pairs, one per line. LLM reads these instead of the full file.
    Only reads the full LONGRUNNER if T4 execution requires narrative context.
    """
    if len(sys.argv) < 3:
        print("ERROR: usage: longrunner-extract <slug>", file=sys.stderr)
        sys.exit(2)
    slug = sys.argv[2]

    # Try LONGRUNNER.md first, then LONGRUNNER-DRAFT.md
    content = read_file(f"PROJECTS/{slug}/LONGRUNNER.md")
    is_draft = False
    if content is None:
        content = read_file(f"PROJECTS/{slug}/LONGRUNNER-DRAFT.md")
        is_draft = True
    if content is None:
        print(f"ERROR: No LONGRUNNER found for slug={slug}")
        sys.exit(1)

    # Parse YAML blocks and key fields
    fields = {}
    fields["slug"] = slug
    fields["is_draft"] = str(is_draft).lower()

    # Extract from phase: block
    phase_patterns = {
        "phase.name": r'name:\s*"?([^"\n]+?)"?\s*$',
        "phase.status": r'status:\s*"?([^"\n]+?)"?\s*$',
        "phase.objective": r'objective:\s*"?([^"\n]+?)"?\s*$',
        "phase.stop_condition": r'stop_condition:\s*"?([^"\n]+?)"?\s*$',
        "phase.successor": r'successor:\s*"?([^"\n]+?)"?\s*$',
        "phase.started": r'started:\s*"?([^"\n]+?)"?\s*$',
        "transition_triggered_at": r'transition_triggered_at:\s*(.+?)\s*$',
        "transition_expires": r'transition_expires:\s*(.+?)\s*$',
        "transition_reescalation_count": r'transition_reescalation_count:\s*(\d+)',
    }

    # Extract from next_pass: block
    next_pass_patterns = {
        "next_pass.objective": r'objective:\s*"?([^"\n]+?)"?\s*$',
        "next_pass.model_tier": r'model_tier:\s*"?([^"\n]+?)"?\s*$',
        "next_pass.pass_type": r'pass_type:\s*"?([^"\n]+?)"?\s*$',
    }

    # Extract from last_pass: block
    last_pass_patterns = {
        "last_pass.date": r'date:\s*"?([^"\n]+?)"?\s*$',
        "last_pass.quality": r'quality:\s*"?([^"\n]+?)"?\s*$',
        "last_pass.validation_passed": r'validation_passed:\s*(.+?)\s*$',
    }

    # Parse in sections to avoid cross-section field name collisions
    lines = content.splitlines()
    in_section = None
    for line in lines:
        stripped = line.strip()
        # Track section headers
        if stripped.startswith("## Current Phase"):
            in_section = "phase"
            continue
        elif stripped.startswith("## Next Pass"):
            in_section = "next_pass"
            continue
        elif stripped.startswith("## Last Pass"):
            in_section = "last_pass"
            continue
        elif stripped.startswith("## "):
            in_section = None
            continue

        if in_section == "phase":
            for key, pattern in phase_patterns.items():
                m = re.search(pattern, stripped, re.MULTILINE)
                if m and key not in fields:
                    val = m.group(1).strip().strip('"').strip()
                    if val and val not in ("~", "null", "None", ""):
                        fields[key] = val
        elif in_section == "next_pass":
            for key, pattern in next_pass_patterns.items():
                m = re.search(pattern, stripped, re.MULTILINE)
                if m and key not in fields:
                    val = m.group(1).strip().strip('"').strip()
                    if val and val not in ("~", "null", "None", ""):
                        fields[key] = val
        elif in_section == "last_pass":
            for key, pattern in last_pass_patterns.items():
                m = re.search(pattern, stripped, re.MULTILINE)
                if m and key not in fields:
                    val = m.group(1).strip().strip('"').strip()
                    if val and val not in ("~", "null", "None", ""):
                        fields[key] = val

    # Extract tools_required (array field)
    tools_m = re.search(r'tools_required:\s*\[([^\]]+)\]', content)
    if tools_m:
        fields["next_pass.tools_required"] = tools_m.group(1).strip()

    # Extract context_budget from next_pass — check for field existence
    budget_m = re.search(r'context_budget:\s*"?([^"\n]+?)"?\s*$', content, re.MULTILINE)
    if budget_m:
        fields["next_pass.context_budget"] = budget_m.group(1).strip().strip('"')
    else:
        fields["next_pass.context_budget"] = "80K"  # default per spec

    # Extract blockers (check if any non-empty rows exist)
    blocker_section = False
    has_blockers = False
    for line in lines:
        if "## Blockers" in line:
            blocker_section = True
            continue
        if blocker_section:
            if line.strip().startswith("## "):
                break
            if line.strip().startswith("|") and not line.strip().startswith("| Blocker") \
               and not all(c in "|- :" for c in line.strip()):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if cells and cells[0] and cells[0] != "":
                    has_blockers = True
                    break
    fields["has_blockers"] = str(has_blockers).lower()

    # Determine routing decision
    status = fields.get("phase.status", "unknown").lower()
    objective = fields.get("next_pass.objective", "")

    if status == "complete":
        fields["routing"] = "COMPLETE"
    elif status == "blocked":
        fields["routing"] = "BLOCKED"
    elif not objective:
        fields["routing"] = "STALE_OBJECTIVE"
    elif status == "active":
        fields["routing"] = "ACTIVE"
    else:
        fields["routing"] = f"UNKNOWN_STATUS:{status}"

    # Output all fields
    for key, val in fields.items():
        print(f"{key}={val}")


# ---------------------------------------------------------------------------
# idle-triage: T1.5 — determine first actionable idle cycle tier
# ---------------------------------------------------------------------------

def cmd_idle_triage():
    """Check idle cycle tier prerequisites deterministically.
    Returns the first tier with actionable work, so the LLM
    skips reading OPS-IDLE-CYCLE.md tiers it won't reach.
    Output: IDLE:TIER=<tier>:ACTION=<action> or IDLE:NONE
    """
    # Tier 1 prereq: [knowledge-repo] directory exists
    # Check USER.md for knowledge-repo path, or look for common paths
    user_content = read_file("USER.md")
    knowledge_repo = None
    if user_content:
        m = re.search(r'knowledge.repo.*?:\s*(.+)', user_content, re.IGNORECASE)
        if m:
            repo_path = m.group(1).strip().strip('"').strip("'")
            if repo_path and repo_path not in ("~", "null", "None", "", "—"):
                knowledge_repo = repo_path

    tier1_available = False
    if knowledge_repo:
        kr_path = ROOT / knowledge_repo.lstrip("/")
        if kr_path.exists() and kr_path.is_dir():
            tier1_available = True

            # 1a: Check inbox
            inbox_path = kr_path / "00-inbox"
            if inbox_path.exists() and any(inbox_path.iterdir()):
                print(f"IDLE:TIER=1a:ACTION=inbox_scan:path={inbox_path}")
                return

            # 1b: Check staleness log
            stale_log = kr_path / "07-index" / "staleness-log.md"
            if stale_log.exists():
                stale_content = stale_log.read_text(encoding="utf-8", errors="replace")
                if ">90" in stale_content or "stale" in stale_content.lower():
                    print(f"IDLE:TIER=1b:ACTION=staleness_check:path={stale_log}")
                    return

            # 1c: Demand signal scan is always available if knowledge-repo configured
            print("IDLE:TIER=1c:ACTION=demand_signal_scan")
            return

    # Tier 2a: knowledge-repo freshness (skip if no repo)
    if knowledge_repo and tier1_available:
        index_path = ROOT / knowledge_repo.lstrip("/") / "07-index" / "index.md"
        if index_path.exists():
            print("IDLE:TIER=2a:ACTION=source_freshness_check")
            return

    # Tier 2b: OPS-FAILURE-MODES open entries
    fm_content = read_file("orchestration-os/OPS-FAILURE-MODES.md")
    if fm_content:
        # Count entries with Status: OPEN (or no RESOLVED/MITIGATED marker)
        open_entries = []
        in_entry = False
        current_fm = None
        for line in fm_content.splitlines():
            m = re.match(r'^### (FM-\d+)', line)
            if m:
                in_entry = True
                current_fm = m.group(1)
                continue
            if in_entry and "**Status:**" in line:
                status_text = line.split("**Status:**")[1].strip().upper()
                if "OPEN" in status_text:
                    open_entries.append(current_fm)
                in_entry = False
        if open_entries:
            print(f"IDLE:TIER=2b:ACTION=ops_failure_review:entries={','.join(open_entries)}")
            return

    # Tier 2c: TOOL-STATUS vs OPS-TOOL-REGISTRY sync
    tool_status = read_file("orchestration-os/TOOL-STATUS.md")
    tool_registry = read_file("orchestration-os/OPS-TOOL-REGISTRY.md")
    if tool_status and tool_registry:
        # Count registry entries vs status entries — quick heuristic for desync
        reg_entries = len(re.findall(r'^\|\s*\d{4}-', tool_registry, re.MULTILINE))
        stat_entries = len(re.findall(r'^\|\s*\w+', tool_status, re.MULTILINE))
        # If registry has grown significantly beyond status table, needs sync
        if reg_entries > stat_entries + 2:
            print(f"IDLE:TIER=2c:ACTION=tool_status_sync:registry_entries={reg_entries}:status_entries={stat_entries}")
            return

    # Tier 3a: Memory dream pass trigger (5+ dated memory files)
    memory_dir = ROOT / "memory"
    if memory_dir.exists():
        dated_files = list(memory_dir.glob("????-??-??.md"))
        if len(dated_files) >= 5:
            print(f"IDLE:TIER=3a:ACTION=memory_dream_pass:files={len(dated_files)}")
            return

    # Tier 3b: AGENTS lesson encoding
    lessons = read_file("AGENTS-LESSONS.md")
    memory_files = sorted(memory_dir.glob("????-??-??.md"), reverse=True) if memory_dir.exists() else []
    if memory_files:
        recent_3 = memory_files[:3]
        has_unencoded = False
        for mf in recent_3:
            content = mf.read_text(encoding="utf-8", errors="replace")
            # Check for lesson-like patterns not yet in AGENTS-LESSONS
            if "lesson" in content.lower() or "correction" in content.lower() or "T7" in content:
                has_unencoded = True
                break
        if has_unencoded:
            print(f"IDLE:TIER=3b:ACTION=agents_lesson_encoding:recent_memory={len(recent_3)}")
            return

    # Tier 3c: MANAGER-REVIEW-REGISTRY housekeeping
    mrr = read_file("PROJECTS/MANAGER-REVIEW-REGISTRY.md")
    if mrr:
        # Check for stale rows (projects marked complete/abandoned > 30 days)
        now = now_utc()
        for line in mrr.splitlines():
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2:
                dt = parse_iso(cells[0])
                if dt and (now - dt).days > 30:
                    print(f"IDLE:TIER=3c:ACTION=mrr_housekeeping")
                    return

    # Tier 4: New project identification
    # Check prerequisites: no existing LONGRUNNER-DRAFT anywhere
    drafts = list((ROOT / "PROJECTS").rglob("LONGRUNNER-DRAFT.md"))
    if drafts:
        print(f"IDLE:TIER=4:ACTION=draft_exists:slug={drafts[0].parent.name}:no_new_proposal_needed")
        return

    # Check conditions A, B, C for Tier 4
    ap_content = read_file("ACTIVE-PROJECTS.md")
    has_active = False
    has_recent_complete = False
    has_transition_hold = False

    if ap_content:
        header_found = False
        headers = []
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
                has_active = True
            if status == "COMPLETE":
                has_recent_complete = True  # Simplified; full check would parse dates
            if status == "TRANSITION-HOLD":
                has_transition_hold = True

    condition_a = not has_active
    condition_b = has_recent_complete
    condition_c = has_transition_hold

    if condition_a or condition_b or condition_c:
        reasons = []
        if condition_a:
            reasons.append("no_active_projects")
        if condition_b:
            reasons.append("recent_completion")
        if condition_c:
            reasons.append("transition_hold_exists")
        kr_note = "path_b_no_knowledge_repo" if not tier1_available else "path_a_knowledge_repo"
        print(f"IDLE:TIER=4a:ACTION=project_proposal:{kr_note}:reasons={','.join(reasons)}")
        return

    print("IDLE:NONE:all_tiers_checked")


# ---------------------------------------------------------------------------
# strategic-context: Manager T3.5 — pre-digest strategic context
# ---------------------------------------------------------------------------

def cmd_strategic_context():
    """Pre-digest strategic context for the manager's idle-state T3.5 pass.
    Checks for drafts, recent completions, memory entry count, and domain anchor age.
    Output reduces what the manager LLM needs to read on the expensive Sonnet model.
    """
    results = {}

    # Check for pending LONGRUNNER-DRAFT files
    drafts = []
    projects_dir = ROOT / "PROJECTS"
    if projects_dir.exists():
        for draft in projects_dir.rglob("LONGRUNNER-DRAFT.md"):
            slug = draft.parent.name
            if slug != "PROJECTS":
                drafts.append(slug)
    if drafts:
        print(f"DRAFTS:{','.join(drafts)}")
    else:
        print("DRAFTS:none")

    # Check for recent completions in ACTIVE-PROJECTS
    ap_content = read_file("ACTIVE-PROJECTS.md")
    completions = []
    if ap_content:
        header_found = False
        headers = []
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
            slug = row.get("project_slug", row.get("slug", "")).strip()
            if status == "COMPLETE" and slug:
                completions.append(slug)
    if completions:
        print(f"RECENT_COMPLETIONS:{','.join(completions)}")
    else:
        print("RECENT_COMPLETIONS:none")

    # Count and list recent memory entries
    memory_dir = ROOT / "memory"
    memory_entries = []
    if memory_dir.exists():
        memory_entries = sorted(memory_dir.glob("????-??-??.md"), reverse=True)
    entry_names = [f.stem for f in memory_entries[:5]]
    print(f"MEMORY_ENTRIES:{len(memory_entries)}:{','.join(entry_names) if entry_names else 'none'}")

    # Check domain anchor freshness (when was SOUL.md last modified?)
    soul_path = ROOT / "SOUL.md"
    if soul_path.exists():
        mtime = datetime.fromtimestamp(soul_path.stat().st_mtime, tz=timezone.utc)
        age_days = (now_utc() - mtime).days
        print(f"DOMAIN_ANCHOR_AGE:{age_days}d")
    else:
        print("DOMAIN_ANCHOR_AGE:unknown")

    # Check MANAGER-REVIEW-REGISTRY for last review date
    mrr = read_file("PROJECTS/MANAGER-REVIEW-REGISTRY.md")
    last_review = "never"
    if mrr:
        dates = re.findall(r'(\d{4}-\d{2}-\d{2})', mrr)
        if dates:
            last_review = sorted(dates)[-1]
    print(f"LAST_MANAGER_REVIEW:{last_review}")

    # Determine recommended T3.5 action
    if drafts:
        print(f"RECOMMENDED:T3.5-A:review_draft:{drafts[0]}")
    elif completions:
        print(f"RECOMMENDED:T3.5-B:review_completion:{completions[0]}")
    else:
        soul_age = 999
        if soul_path.exists():
            mtime = datetime.fromtimestamp(soul_path.stat().st_mtime, tz=timezone.utc)
            soul_age = (now_utc() - mtime).days
        if soul_age > 30:
            print("RECOMMENDED:T3.5-C:domain_anchor_review")
        else:
            print("RECOMMENDED:T3.5-D:no_action")


# ---------------------------------------------------------------------------
# t7-dedup: T7 — check if a signal is already documented
# ---------------------------------------------------------------------------

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

    content = read_file(target_file)
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


# ---------------------------------------------------------------------------
# crash-context: T0 — retrieve context from a crashed session
# ---------------------------------------------------------------------------

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

    audit_log = read_file("audit/AUDIT-LOG.md")
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
    memory_dir = ROOT / "memory"
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


# ---------------------------------------------------------------------------
# append: Safe file append for APPEND-ONLY files
# ---------------------------------------------------------------------------

# Allowed append targets — only files marked APPEND in REGISTRY.md R3.
# Agent cannot append to arbitrary files via this command.
APPEND_ALLOWED = {
    "audit/AUDIT-LOG.md",
    "audit/SESSION-REGISTRY.md",
    "audit/CHANGE-LOG.md",
    "audit/APPROVAL-CHAIN.md",
    "NOTIFICATIONS.md",
    "NOTIFICATIONS-ARCHIVE.md",
    "AGENTS-LESSONS.md",
}
# memory/YYYY-MM-DD.md is allowed dynamically (pattern match below).

def _is_allowed_append_target(rel_path):
    """Check if a relative path is an allowed append target."""
    normalized = rel_path.replace("\\", "/").strip("/")
    if normalized in APPEND_ALLOWED:
        return True
    # memory/YYYY-MM-DD.md pattern
    if re.match(r"^memory/\d{4}-\d{2}-\d{2}\.md$", normalized):
        return True
    return False

def cmd_append():
    """Append a line to an APPEND-ONLY file. Safe alternative to Edit tool.

    Usage: python3 scripts/nightclaw-ops.py append <file> <line>
    The line is appended with a trailing newline.
    File is created if it does not exist (parent directory must exist).
    Only files listed in APPEND_ALLOWED or matching memory/YYYY-MM-DD.md are accepted.
    """
    if len(sys.argv) < 4:
        print("ERROR:MISSING_ARGS — usage: append <file> <line>", file=sys.stderr)
        sys.exit(2)

    rel_path = sys.argv[2]
    line = " ".join(sys.argv[3:])

    if not _is_allowed_append_target(rel_path):
        print(f"ERROR:DENIED — {rel_path} is not an allowed append target")
        print(f"ALLOWED: {', '.join(sorted(APPEND_ALLOWED))} + memory/YYYY-MM-DD.md")
        sys.exit(1)

    target = ROOT / rel_path

    # Ensure parent directory exists (for memory/YYYY-MM-DD.md on first write)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Append with trailing newline
    with open(target, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    print(f"APPENDED:{rel_path}")


def cmd_append_batch():
    """Append multiple lines to an APPEND-ONLY file in one call.

    Usage: python3 scripts/nightclaw-ops.py append-batch <file> <line1> ||| <line2> ||| <line3>
    Lines are separated by ' ||| ' delimiter.
    Useful for BUNDLE writes that append multiple entries to the same file.
    """
    if len(sys.argv) < 4:
        print("ERROR:MISSING_ARGS — usage: append-batch <file> <line1> ||| <line2>", file=sys.stderr)
        sys.exit(2)

    rel_path = sys.argv[2]
    raw = " ".join(sys.argv[3:])
    lines = [l.strip() for l in raw.split("|||") if l.strip()]

    if not lines:
        print("ERROR:NO_LINES — no non-empty lines found after splitting on |||")
        sys.exit(1)

    if not _is_allowed_append_target(rel_path):
        print(f"ERROR:DENIED — {rel_path} is not an allowed append target")
        sys.exit(1)

    target = ROOT / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)

    with open(target, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    print(f"APPENDED:{rel_path}:LINES={len(lines)}")


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
    "longrunner-extract": cmd_longrunner_extract,
    "idle-triage": cmd_idle_triage,
    "strategic-context": cmd_strategic_context,
    "t7-dedup": cmd_t7_dedup,
    "crash-context": cmd_crash_context,
    "append": cmd_append,
    "append-batch": cmd_append_batch,
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
