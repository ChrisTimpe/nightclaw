"""nightclaw_engine.commands.dispatch — dispatch + triage + notifications.

Four commands that drive T1 / T1.5 / T2 flow:

* ``dispatch``               — pick highest-priority project
* ``scan-notifications``     — find actionable notification entries
* ``dispatch-validate``      — R2 contract check on ACTIVE-PROJECTS.md
* ``idle-triage``            — first actionable idle cycle tier
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import _shared


def cmd_dispatch():
    """Parse ACTIVE-PROJECTS.md, return highest-priority dispatchable project.
    Output: DISPATCH:<slug> or IDLE (no dispatchable project)
    Also outputs the full parsed table for context.
    """
    rows = _shared.parse_dispatch_table()
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

        # Path B: PA-003 (phase-auto-advance) is active
        elif esc.startswith("phase-complete-"):
            if _shared.check_pa_active("phase-auto-advance"):
                eligible = True

        if not eligible:
            continue

        # Verify successor exists in LONGRUNNER
        successor = _shared.read_longrunner_successor(slug)
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

def cmd_scan_notifications():
    """Scan NOTIFICATIONS.md for worker-actionable entries.
    Uses structural matching: any notification entry that is not [DONE],
    not LOW/INFO priority, and not a lock-defer or manager-deferred message
    is considered actionable. Also matches explicit actionable tags.
    Output: FOUND:line=<n>:<priority>:<summary> or NONE
    """
    content = _shared.read_file("NOTIFICATIONS.md")
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

def cmd_dispatch_validate():
    """Validate ACTIVE-PROJECTS.md against R2 field contracts.

    Per-field enum/type/required checks are delegated to
    :func:`nightclaw_engine.engine.gates.validate_field`, so the R2 contract
    is enforced deterministically from the schema rather than hardcoded here.
    Priority uniqueness and slug FK→PROJECTS/<slug>/ are cross-row constraints
    that stay in this command (they are not single-field invariants).
    Output format is preserved byte-for-byte: ``VALID`` or
    ``VIOLATION:<field>:<details>`` lines followed by ``TOTAL_VIOLATIONS:N``.
    """
    from nightclaw_engine.schema.loader import SchemaError, load as _load_schema
    from nightclaw_engine.engine import gates as _gates

    rows = _shared.parse_dispatch_table()
    if not rows:
        print("SKIP reason=file_not_found")
        return

    schema_dir = _shared.ROOT / "orchestration-os" / "schema"
    try:
        model = _load_schema(schema_dir)
    except SchemaError as exc:
        print(f"ERROR: schema_load_failed: {exc}")
        sys.exit(1)

    # R2 declares ACTIVE-PROJECTS.md columns under OBJ:DISPATCH_ROW — find
    # the actual obj name by scanning fields whose route hints at the
    # dispatch table. Fall back to the most common name.
    dispatch_objs = {
        f.obj for f in model.fields
        if "ACTIVE-PROJECTS" in (f.constraint or "") or f.obj in ("DISPATCH_ROW", "DISPATCH")
    }
    # Heuristic: pick the obj whose declared fields most overlap with the
    # columns we actually have in the table.
    table_keys = set().union(*[set(r.keys()) for r in rows]) if rows else set()
    def _score(obj: str) -> int:
        return sum(1 for f in model.fields if f.obj == obj and f.field in table_keys)
    dispatch_obj = None
    if dispatch_objs:
        dispatch_obj = max(dispatch_objs, key=_score)
    else:
        # Pick any obj with highest field overlap to the table shape.
        objs = {f.obj for f in model.fields}
        if objs:
            dispatch_obj = max(objs, key=_score)

    violations = []
    priorities_seen = {}

    for row in rows:
        slug = row.get("project_slug", row.get("slug", "")).strip()
        status = row.get("status", "").strip()
        priority = row.get("priority", "").strip()

        # Skip placeholder/example rows
        if not slug or slug.startswith("_(") or slug == "\u2014" or status == "\u2014":
            continue

        # R2 gate: validate each column that R2 declares for this object.
        if dispatch_obj is not None:
            for col, val in row.items():
                if _gates.find_field(model, dispatch_obj, col) is None:
                    continue
                gr = _gates.validate_field(model, dispatch_obj, col, val)
                if not gr.ok:
                    # Preserve legacy shape: VIOLATION:<column>:slug=...:...
                    violations.append(
                        f"VIOLATION:{col}:slug={slug}:code={gr.code}:{gr.detail}"
                    )

        # Priority uniqueness (among ACTIVE rows) — cross-row constraint.
        if status.upper() == "ACTIVE" and priority:
            if priority in priorities_seen:
                violations.append(
                    f"VIOLATION:priority_unique:slug={slug}:priority={priority}:conflicts_with={priorities_seen[priority]}"
                )
            priorities_seen[priority] = slug

        # Slug FK → PROJECTS/<slug>/ — cross-file FK.
        if slug:
            proj_dir = _shared.ROOT / "PROJECTS" / slug
            if not proj_dir.exists():
                violations.append(
                    f"VIOLATION:slug_fk:slug={slug}:PROJECTS/{slug}/_not_found"
                )

    if violations:
        for v in violations:
            print(v)
        print(f"TOTAL_VIOLATIONS:{len(violations)}")
        sys.exit(1)
    else:
        print("VALID")
        sys.exit(0)

def cmd_idle_triage():
    """Check idle cycle tier prerequisites deterministically.
    Returns the first tier with actionable work, so the LLM
    skips reading OPS-IDLE-CYCLE.md tiers it won't reach.
    Output: IDLE:TIER=<tier>:ACTION=<action> or IDLE:NONE
    """
    # Tier 1 prereq: [knowledge-repo] directory exists
    # Check USER.md for knowledge-repo path, or look for common paths
    user_content = _shared.read_file("USER.md")
    knowledge_repo = None
    if user_content:
        m = re.search(r'knowledge.repo.*?:\s*(.+)', user_content, re.IGNORECASE)
        if m:
            repo_path = m.group(1).strip().strip('"').strip("'")
            if repo_path and repo_path not in ("~", "null", "None", "", "—"):
                knowledge_repo = repo_path

    tier1_available = False
    if knowledge_repo:
        # H-SEC-06: ``knowledge-repo`` comes from USER.md which is operator-
        # editable. The previous ``_shared.ROOT / path.lstrip("/")`` join
        # happily followed ``../..`` segments and would let idle-triage
        # probe (and emit path output for) files outside the workspace.
        # Resolve both sides and require the knowledge-repo to sit under
        # ROOT; otherwise treat tier-1 as unavailable and fall through to
        # the non-knowledge-repo tiers.
        kr_path = _shared.ROOT / knowledge_repo.lstrip("/")
        try:
            kr_resolved = kr_path.resolve()
            root_resolved = _shared.ROOT.resolve()
            confined = (
                kr_resolved == root_resolved
                or root_resolved in kr_resolved.parents
            )
        except (OSError, RuntimeError):
            confined = False
        if confined and kr_path.exists() and kr_path.is_dir():
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
        # ``tier1_available`` already implies the confinement check above
        # passed, so it is safe to re-derive the path the same way.
        index_path = _shared.ROOT / knowledge_repo.lstrip("/") / "07-index" / "index.md"
        if index_path.exists():
            print("IDLE:TIER=2a:ACTION=source_freshness_check")
            return

    # Tier 2b: OPS-FAILURE-MODES open entries
    fm_content = _shared.read_file("orchestration-os/OPS-FAILURE-MODES.md")
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
    tool_status = _shared.read_file("orchestration-os/TOOL-STATUS.md")
    tool_registry = _shared.read_file("orchestration-os/OPS-TOOL-REGISTRY.md")
    if tool_status and tool_registry:
        # Count registry entries vs status entries — quick heuristic for desync
        reg_entries = len(re.findall(r'^\|\s*\d{4}-', tool_registry, re.MULTILINE))
        stat_entries = len(re.findall(r'^\|\s*\w+', tool_status, re.MULTILINE))
        # If registry has grown significantly beyond status table, needs sync
        if reg_entries > stat_entries + 2:
            print(f"IDLE:TIER=2c:ACTION=tool_status_sync:registry_entries={reg_entries}:status_entries={stat_entries}")
            return

    # Tier 3a: Memory dream pass trigger (5+ dated memory files)
    memory_dir = _shared.ROOT / "memory"
    if memory_dir.exists():
        dated_files = list(memory_dir.glob("????-??-??.md"))
        if len(dated_files) >= 5:
            print(f"IDLE:TIER=3a:ACTION=memory_dream_pass:files={len(dated_files)}")
            return

    # Tier 3b: AGENTS lesson encoding
    lessons = _shared.read_file("AGENTS-LESSONS.md")
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
    mrr = _shared.read_file("PROJECTS/MANAGER-REVIEW-REGISTRY.md")
    if mrr:
        # Check for stale rows (projects marked complete/abandoned > 30 days)
        now = _shared.now_utc()
        for line in mrr.splitlines():
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2:
                dt = _shared.parse_iso(cells[0])
                if dt and (now - dt).days > 30:
                    print(f"IDLE:TIER=3c:ACTION=mrr_housekeeping")
                    return

    # Tier 4: New project identification
    # Check prerequisites: no existing LONGRUNNER-DRAFT anywhere
    drafts = list((_shared.ROOT / "PROJECTS").rglob("LONGRUNNER-DRAFT.md"))
    if drafts:
        print(f"IDLE:TIER=4:ACTION=draft_exists:slug={drafts[0].parent.name}:no_new_proposal_needed")
        return

    # Check conditions A, B, C for Tier 4
    ap_rows = _shared.parse_dispatch_table()
    has_active = False
    has_recent_complete = False
    has_transition_hold = False

    for row in ap_rows:
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


__all__ = ["cmd_dispatch", "cmd_scan_notifications", "cmd_dispatch_validate", "cmd_idle_triage"]
