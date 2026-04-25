"""nightclaw_engine.commands.validate — R2/R3/R4 gate-exposing commands.

Thin CLI wrappers around :mod:`nightclaw_engine.engine.gates`:

* ``validate-field``      — single-field R2 check
* ``cascade-read``        — list R4 downstream edges
* ``registry-route``      — resolve R3 routing rule for a path
* ``strategic-context``   — T3.5 idle-manager pre-digest

Bodies migrated verbatim from ``_legacy.py`` (Pass 6).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

from . import _shared


def cmd_strategic_context():
    """Pre-digest strategic context for the manager's idle-state T3.5 pass.
    Checks for drafts, recent completions, memory entry count, and domain anchor age.
    Output reduces what the manager LLM needs to read on an expensive model.
    """
    results = {}

    # Check for pending LONGRUNNER-DRAFT files
    drafts = []
    projects_dir = _shared.ROOT / "PROJECTS"
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
    ap_rows = _shared.parse_dispatch_table()
    completions = []
    for row in ap_rows:
        status = row.get("status", "").strip().upper()
        slug = row.get("project_slug", row.get("slug", "")).strip()
        if status == "COMPLETE" and slug:
            completions.append(slug)
    if completions:
        print(f"RECENT_COMPLETIONS:{','.join(completions)}")
    else:
        print("RECENT_COMPLETIONS:none")

    # Count and list recent memory entries
    memory_dir = _shared.ROOT / "memory"
    memory_entries = []
    if memory_dir.exists():
        memory_entries = sorted(memory_dir.glob("????-??-??.md"), reverse=True)
    entry_names = [f.stem for f in memory_entries[:5]]
    print(f"MEMORY_ENTRIES:{len(memory_entries)}:{','.join(entry_names) if entry_names else 'none'}")

    # Check domain anchor freshness (when was SOUL.md last modified?)
    soul_path = _shared.ROOT / "SOUL.md"
    if soul_path.exists():
        mtime = datetime.fromtimestamp(soul_path.stat().st_mtime, tz=timezone.utc)
        age_days = (_shared.now_utc() - mtime).days
        print(f"DOMAIN_ANCHOR_AGE:{age_days}d")
    else:
        print("DOMAIN_ANCHOR_AGE:unknown")

    # Check MANAGER-REVIEW-REGISTRY for last review date
    mrr = _shared.read_file("PROJECTS/MANAGER-REVIEW-REGISTRY.md")
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
            soul_age = (_shared.now_utc() - mtime).days
        if soul_age > 30:
            print("RECOMMENDED:T3.5-C:domain_anchor_review")
        else:
            print("RECOMMENDED:T3.5-D:no_action")

def _load_gate_model():
    """Shared loader for Merge-2 CLI commands. Exits on schema error."""
    from nightclaw_engine.schema.loader import SchemaError, load as _load_schema
    schema_dir = _shared.ROOT / "orchestration-os" / "schema"
    try:
        return _load_schema(schema_dir)
    except SchemaError as exc:
        print(f"ERROR: schema_load_failed: {exc}")
        sys.exit(1)

def cmd_validate_field():
    """Run the R2 field gate for a single (obj, field, value).

    Usage: validate-field <OBJ> <field> <value>
    Output: OK:<obj>.<field>  |  VIOLATION:<code>:<detail>
    """
    from nightclaw_engine.engine import gates as _gates
    if len(sys.argv) < 5:
        print("ERROR:USAGE: validate-field <OBJ> <field> <value>", file=sys.stderr)
        sys.exit(2)
    obj = sys.argv[2]
    field = sys.argv[3]
    value = " ".join(sys.argv[4:])
    model = _load_gate_model()
    res = _gates.validate_field(model, obj, field, value)
    if res.ok:
        print(f"OK:{obj}.{field}")
        sys.exit(0)
    print(res.as_line())
    sys.exit(1)

def cmd_cascade_read():
    """List R4 downstream edges where the given file is SOURCE.

    Usage: cascade-read <rel_path>
    Output: CASCADE:<type>:<target>  (one per edge)
            CASCADE:NONE              (if no edges)
    """
    from nightclaw_engine.engine import gates as _gates
    if len(sys.argv) < 3:
        print("ERROR:USAGE: cascade-read <rel_path>", file=sys.stderr)
        sys.exit(2)
    rel = sys.argv[2]
    model = _load_gate_model()
    edges = _gates.cascade_for(model, rel)
    if not edges:
        print("CASCADE:NONE")
        return
    for e in edges:
        print(f"CASCADE:{e.type}:{e.target}")

def cmd_registry_route():
    """Print the R3 routing rule for a relative path.

    Usage: registry-route <rel_path>
    Output: ROUTE:<tier>:<bundle_or_->
            ROUTE:UNKNOWN            (if not in R3)
            ROUTE:PROTECTED          (if CL5 protects the path)
    """
    from nightclaw_engine.engine import gates as _gates
    if len(sys.argv) < 3:
        print("ERROR:USAGE: registry-route <rel_path>", file=sys.stderr)
        sys.exit(2)
    rel = sys.argv[2]
    model = _load_gate_model()
    if _gates.is_protected(model, rel):
        print("ROUTE:PROTECTED")
        return
    r = _gates.route_for(model, rel)
    if r is None:
        print("ROUTE:UNKNOWN")
        return
    bundle = (r.bundle or "-").strip() or "-"
    print(f"ROUTE:{r.tier}:{bundle}")


__all__ = ["cmd_strategic_context", "_load_gate_model", "cmd_validate_field", "cmd_cascade_read", "cmd_registry_route"]
