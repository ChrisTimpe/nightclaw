"""nightclaw_engine.commands._shared — shared state and helpers for command modules.

This module owns the mutable singletons that every ``cmd_*`` function reads:

* :data:`ROOT` — workspace root :class:`pathlib.Path`. Set once by
  :func:`nightclaw_engine.commands.main` and read via attribute access
  (``_shared.ROOT``) so the late-binding pattern survives module boundaries.
* :data:`PROTECTED_PATHS` — files the bundle executor must never write to.
* :data:`APPEND_ALLOWED` — files the ``append``/``append-batch`` commands may
  target. Moved here from _legacy so :mod:`commands.append` can import it.

Pure helpers that multiple command families use (YAML parsing, timestamp
handling, pre-approval checks) also live here to avoid circular imports.

Pass 6 note (2026-04-18): extracted verbatim from ``_legacy.py`` lines 45-332.
Bodies are byte-identical; only the ``ROOT`` references switch from module
globals to ``_shared.ROOT`` attribute access — that is the one intentional
change required to cross the module boundary safely.
"""
from __future__ import annotations

import os
import re
import sys
import pathlib
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Telemetry (optional monitor — silent no-op if bridge not running)
# G1 FIX: route through the real nightclaw_ops.telemetry module that already
# ships with the repo, not the non-existent nightclaw_telemetry_patch.
# ---------------------------------------------------------------------------
try:
    from nightclaw_ops.telemetry import emit_step  # type: ignore
except Exception:  # pragma: no cover — stays exception-safe
    def emit_step(*a, **kw):  # type: ignore
        pass

try:
    from nightclaw_ops.lifecycle import step as lifecycle_step  # type: ignore
except Exception:  # pragma: no cover — stays exception-safe
    import contextlib as _contextlib
    @_contextlib.contextmanager  # type: ignore
    def lifecycle_step(*a, **kw):
        yield


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Files that the executor must NEVER write to, regardless of R5 spec content.
# These are PROTECTED tier in R3 — only {OWNER} may modify them.
PROTECTED_PATHS = frozenset({
    "SOUL.md", "USER.md", "IDENTITY.md", "MEMORY.md", "AGENTS-CORE.md",
    "orchestration-os/CRON-WORKER-PROMPT.md", "orchestration-os/CRON-MANAGER-PROMPT.md",
    "orchestration-os/OPS-PREAPPROVAL.md", "orchestration-os/OPS-AUTONOMOUS-SAFETY.md",
    "orchestration-os/CRON-HARDLINES.md", "orchestration-os/REGISTRY.md",
})

# Allowed targets for the generic append command. Centralised here so tests
# and multiple command modules agree. memory/YYYY-MM-DD.md is allowed
# dynamically via regex (see :func:`commands.append._is_allowed_append_target`).
APPEND_ALLOWED = frozenset({
    "audit/AUDIT-LOG.md",
    "audit/SESSION-REGISTRY.md",
    "audit/CHANGE-LOG.md",
    "audit/APPROVAL-CHAIN.md",
    "NOTIFICATIONS.md",
    "NOTIFICATIONS-ARCHIVE.md",
    "AGENTS-LESSONS.md",
    # OS compounding file archives — manager T8 archival only
    "orchestration-os/OPS-FAILURE-MODES-ARCHIVE.md",
    "AGENTS-LESSONS-ARCHIVE.md",
    "orchestration-os/OPS-TOOL-REGISTRY-ARCHIVE.md",
})

# Workspace root — set once by commands.main() before dispatch.
# Readers must use ``_shared.ROOT`` (attribute access) — not ``from _shared import ROOT``
# — so they pick up the bound value at call time.
ROOT: pathlib.Path | None = None

# Canonical project-slug format. Must match the regex enforced by
# ``scripts/nightclaw-admin.sh:validate_slug`` so that every owner-facing
# admin command and every internal write path agree on what a legal slug
# looks like. Lowercase letters, digits, and internal hyphens only; no
# leading/trailing hyphens; no `.`, `/`, or traversal characters. This is
# the defense that turns
#
#   f"PROJECTS/{slug}/LONGRUNNER.md"
#
# into a safe path: any slug that matches SLUG_RE cannot contain ``..``,
# ``/``, or absolute-path leaders, so the result is always confined to
# ``PROJECTS/<legal-name>/LONGRUNNER.md`` under ROOT.
#
# Keep this regex identical to scripts/nightclaw-admin.sh:validate_slug
# (Pass 13 — H-SEC-02 reconciliation).
SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def is_valid_slug(slug) -> bool:
    """Return True iff ``slug`` is a legal project slug.

    Rejects non-strings, empty strings, and anything containing path
    separators, dots, uppercase letters, or traversal characters. Callers
    that accept a slug from an external source (bundle ARGS, CLI argv,
    resolved dispatch table) must call this before substituting the slug
    into a write path. Returning False is always safe; callers decide the
    error string to emit so each call site stays Lock-1 friendly.
    """
    return isinstance(slug, str) and bool(SLUG_RE.match(slug))


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def workspace_root():
    """Return workspace root (cwd or detect from script location)."""
    if os.path.isfile("LOCK.md") or os.path.isfile("SOUL.md"):
        return pathlib.Path(".")
    # Try parent of scripts/
    p = pathlib.Path(__file__).resolve().parent.parent.parent
    if (p / "LOCK.md").exists() or (p / "SOUL.md").exists():
        return p
    print("ERROR: Run from workspace root or place script in scripts/", file=sys.stderr)
    sys.exit(2)


def read_file(rel_path):
    """Read file relative to workspace root. Returns content or None."""
    fp = ROOT / rel_path
    if fp.exists():
        return fp.read_text(encoding="utf-8", errors="replace")
    return None


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_iso(s):
    """Parse ISO8601 timestamp string to datetime. Returns None on failure.
    Coerces naive datetimes to UTC (assumes all NightClaw timestamps are UTC).
    """
    if not s or s.strip() in ("—", "-", "~", "null", "None", "none", ""):
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Pre-approval check
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# LONGRUNNER parsing helpers
# ---------------------------------------------------------------------------

def read_longrunner_successor(slug):
    """Read phase.successor from a project's LONGRUNNER. Returns empty string if not found."""
    fields = parse_longrunner(slug)
    if fields is None:
        return ""
    val = fields.get("phase.successor", "")
    if val and val not in ("~", "null", "None", "none", ""):
        return val
    return ""


def parse_dispatch_table():
    """Parse ACTIVE-PROJECTS.md table into list of dicts.
    Returns list of row dicts with lowercase_underscore keys, or empty list on failure.
    """
    content = read_file("ACTIVE-PROJECTS.md")
    if content is None:
        return []
    rows = []
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
            rows.append(row)
    return rows


def parse_longrunner(slug):
    """Parse ALL YAML fields from a LONGRUNNER file.
    Returns dict with dotted keys: {'phase.name': '...', 'next_pass.objective': '...', ...}
    Also returns 'slug', 'is_draft', 'has_blockers'.
    Generic — extracts any key:value pair from YAML blocks, not a fixed field list.
    """
    content = read_file(f"PROJECTS/{slug}/LONGRUNNER.md")
    is_draft = False
    if content is None:
        content = read_file(f"PROJECTS/{slug}/LONGRUNNER-DRAFT.md")
        is_draft = True
    if content is None:
        return None

    fields = {"slug": slug, "is_draft": str(is_draft).lower()}
    lines = content.splitlines()

    # Track which YAML block we're in based on markdown section headers
    section_map = {
        "## Current Phase": "phase",
        "## Last Pass": "last_pass",
        "## Next Pass": "next_pass",
    }
    # Also handle yaml blocks within phase that have sub-sections
    # like transition_* fields that are at phase level

    current_section = None
    in_yaml = False
    yaml_indent = 0

    for line in lines:
        stripped = line.strip()

        # Track section headers
        for header, section in section_map.items():
            if stripped.startswith(header):
                current_section = section
                in_yaml = False
                break

        # Other ## headers end the current section
        if stripped.startswith("## ") and not any(stripped.startswith(h) for h in section_map):
            current_section = None
            in_yaml = False
            continue

        # Detect YAML block boundaries
        if stripped == "```yaml":
            in_yaml = True
            continue
        if stripped == "```" and in_yaml:
            in_yaml = False
            continue

        if not in_yaml or not current_section:
            continue

        # Parse YAML key:value pairs
        # Handle nested keys like "phase:" or "last_pass:" (these are section markers in YAML)
        m = re.match(r'^(\s*)(\w[\w.]*) *: *(.*)', line)
        if not m:
            continue

        indent = len(m.group(1))
        key = m.group(2)
        val = m.group(3).strip()

        # Skip section-level keys (e.g., "phase:", "last_pass:", "next_pass:")
        # These have no value and just define nesting
        if not val or val == "":
            yaml_indent = indent
            continue

        # Strip quotes and comments
        if val.startswith('"') and '"' in val[1:]:
            val = val[1:val.index('"', 1)]
        elif val.startswith("'") and "'" in val[1:]:
            val = val[1:val.index("'", 1)]
        else:
            # Remove inline comments
            if "  #" in val:
                val = val[:val.index("  #")].strip()
            elif val.startswith("#"):
                continue

        # Handle arrays
        if val.startswith("["):
            # Keep as-is for array values
            pass

        # Build dotted key based on section
        # Phase-level fields: fields inside the phase: block use "phase." prefix
        # But transition_* fields are at the same level as phase: block
        if current_section == "phase":
            # Check if this is a top-level field in Current Phase (transition_*, etc.)
            # or a nested field inside phase: block
            if key.startswith("transition_") or key.startswith("phase."):
                dotted_key = key  # Already has prefix or is top-level
            elif indent > yaml_indent:
                dotted_key = f"phase.{key}"
            else:
                dotted_key = key
        else:
            if indent > yaml_indent:
                dotted_key = f"{current_section}.{key}"
            else:
                dotted_key = key

        # Don't overwrite — first match wins (avoids cross-section collision)
        if dotted_key not in fields and val not in ("~", "null", "None", "none", ""):
            fields[dotted_key] = val.strip('"').strip("'").strip()

    # Check for blockers
    has_blockers = False
    blocker_section = False
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

    return fields
