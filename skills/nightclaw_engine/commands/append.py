"""nightclaw_engine.commands.append — append + append-batch.

Safe alternative to the generic Edit tool for APPEND-ONLY files. The R3 routing
model declares which tiers/files accept appends; this module enforces that
policy with a defense-in-depth allow-list in :data:`_shared.APPEND_ALLOWED`.

Bodies migrated from ``_legacy.py`` (Pass 6). ``ROOT`` references resolve
through :mod:`._shared`.
"""
from __future__ import annotations

import re
import sys

from . import _shared


def _is_allowed_append_target(rel_path):
    """Check if a relative path is an allowed append target.

    Consults the schema-driven R3 route first (tier=APPEND or
    route-for-file policy). If the schema is unavailable, falls back to
    the legacy hardcoded allow-list which stays in place as
    defense-in-depth.
    """
    normalized = rel_path.replace("\\", "/").strip("/")
    # Legacy allow-list — always honored (belt-and-suspenders).
    if normalized in _shared.APPEND_ALLOWED:
        return True
    # memory/YYYY-MM-DD.md pattern
    if re.match(r"^memory/\d{4}-\d{2}-\d{2}\.md$", normalized):
        return True
    # Schema-driven R3 check: permit append if the route's tier marks it APPEND.
    try:
        from nightclaw_engine.schema.loader import load as _load_schema_gate
        from nightclaw_engine.engine import gates as _gates_mod
        _model = _load_schema_gate(_shared.ROOT / "orchestration-os" / "schema")
        route = _gates_mod.route_for(_model, normalized)
        if route is not None and route.tier.upper() in ("APPEND", "APPEND-ONLY"):
            return True
    except Exception:
        pass
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
        print(f"ALLOWED: {', '.join(sorted(_shared.APPEND_ALLOWED))} + memory/YYYY-MM-DD.md")
        sys.exit(1)

    target = _shared.ROOT / rel_path

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

    target = _shared.ROOT / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)

    with open(target, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    print(f"APPENDED:{rel_path}:LINES={len(lines)}")


__all__ = ["cmd_append", "cmd_append_batch", "_is_allowed_append_target"]
