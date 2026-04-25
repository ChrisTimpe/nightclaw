"""nightclaw_engine.commands.bundle_mutators — per-target field mutators for R5.

Split out of ``bundle.py`` during Pass 6 to honor the ≤700 LOC per-module
architectural ceiling (plan §6). These functions are module-private to the
bundle package — external callers go through ``cmd_bundle_exec``.

Owns:
  * mutate_longrunner_field — LONGRUNNER.md YAML-block field writes
  * mutate_dispatch_field   — ACTIVE-PROJECTS.md row field writes
  * mutate_manifest_field   — INTEGRITY-MANIFEST.md top-matter writes
  * mutate_lock_field       — LOCK.md field writes
  * do_append               — shared append primitive (uses append allowlist)

All mutators return the old value (for R5 CHANGE-LOG emission) or ``None`` if
the target is append-only. All I/O is routed through ``_shared`` helpers so
the module honors the ROOT attribute-binding contract.
"""
from __future__ import annotations

import os
import re
import sys

from . import _shared
from .append import _is_allowed_append_target


def mutate_longrunner_field(slug, field, value):
    """Mutate a single field in a LONGRUNNER YAML block. Returns old value."""
    # H-SEC-02: slug is substituted into a write path. Reject anything that
    # does not match the canonical project-slug regex so a crafted bundle
    # cannot escape the workspace via ``../..``. This is the single defense
    # for the bundle-executor → mutate_longrunner_field write path; an
    # identical check lives in commands.longrunner.cmd_longrunner_render for
    # the parallel longrunner-render write path.
    if not _shared.is_valid_slug(slug):
        print(f"ERROR:INVALID_SLUG:{slug!r}", file=sys.stderr)
        return None
    path = f"PROJECTS/{slug}/LONGRUNNER.md"
    content = _shared.read_file(path)
    if content is None:
        print(f"ERROR: cannot read {path}", file=sys.stderr)
        return None

    # Find the field in YAML blocks and replace its value
    # field can be dotted: "phase.name", "next_pass.objective", "transition_triggered_at"
    # We need to find the right line and replace the value

    lines = content.splitlines()
    # Determine which section to look in
    section_map = {
        "phase.": "## Current Phase",
        "next_pass.": "## Next Pass",
        "last_pass.": "## Last Pass",
        "transition_": "## Current Phase",
    }

    target_section = None
    for prefix, section in section_map.items():
        if field.startswith(prefix):
            target_section = section
            break

    # The actual YAML key (strip section prefix)
    yaml_key = field
    for prefix in ["phase.", "next_pass.", "last_pass."]:
        if field.startswith(prefix):
            yaml_key = field[len(prefix):]
            break

    in_section = False
    in_yaml = False
    old_value = None

    for i, line in enumerate(lines):
        if target_section and line.strip().startswith(target_section):
            in_section = True
            continue
        if in_section and line.strip().startswith("## ") and not line.strip().startswith(target_section):
            in_section = False
            continue
        if line.strip() == "```yaml":
            if in_section or target_section is None:
                in_yaml = True
            continue
        if line.strip() == "```" and in_yaml:
            in_yaml = False
            continue

        if in_yaml and in_section:
            m = re.match(rf'^(\s*){re.escape(yaml_key)}\s*:\s*(.*)', line)
            if m:
                indent = m.group(1)
                old_raw = m.group(2).strip()
                # Extract old value (strip comments, quotes)
                old_value = old_raw
                if "  #" in old_value:
                    comment = old_value[old_value.index("  #"):]
                    old_value = old_value[:old_value.index("  #")].strip()
                else:
                    comment = ""
                old_value = old_value.strip('"').strip("'")

                # Write new value
                if value == "~":
                    new_line = f'{indent}{yaml_key}: ~{comment}'
                elif value == "" or value == '""':
                    new_line = f'{indent}{yaml_key}: ""{comment}'
                elif value.isdigit():
                    new_line = f'{indent}{yaml_key}: {value}{comment}'
                else:
                    # Quote strings that contain spaces or special chars
                    if " " in value or ":" in value or value.startswith("["):
                        new_line = f'{indent}{yaml_key}: "{value}"{comment}'
                    else:
                        new_line = f'{indent}{yaml_key}: {value}{comment}'

                lines[i] = new_line
                break

    # Write back
    ws = _shared.workspace_root()
    full_path = os.path.join(ws, path)
    with open(full_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return old_value if old_value else ""

def mutate_dispatch_field(slug, field, value):
    """Mutate a field in ACTIVE-PROJECTS.md for a given slug. Returns old value."""
    path = "ACTIVE-PROJECTS.md"
    content = _shared.read_file(path)
    if content is None:
        return None

    lines = content.splitlines()
    headers = []
    header_found = False
    header_line_idx = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if not header_found:
            headers = [c.lower().replace(" ", "_") for c in cells]
            header_found = True
            header_line_idx = i
            continue
        if cells and all(set(c.strip()) <= {"-", ":"} for c in cells):
            continue
        if len(cells) >= len(headers):
            row = dict(zip(headers, cells))
            row_slug = row.get("project_slug", row.get("slug", "")).strip()
            if row_slug == slug:
                # Find the column index for the field
                field_lower = field.lower().replace(" ", "_")
                if field_lower in headers:
                    col_idx = headers.index(field_lower)
                    old_value = cells[col_idx]
                    cells[col_idx] = value
                    # Rebuild the line
                    new_line = "| " + " | ".join(cells) + " |"
                    lines[i] = new_line

                    ws = _shared.workspace_root()
                    full_path = os.path.join(ws, path)
                    with open(full_path, "w") as f:
                        f.write("\n".join(lines) + "\n")
                    return old_value
    return None

def mutate_manifest_field(field, value):
    """Mutate a field across all rows in INTEGRITY-MANIFEST.md. Returns old value of first row."""
    path = "audit/INTEGRITY-MANIFEST.md"
    content = _shared.read_file(path)
    if content is None:
        return None

    # Map R5 field names to table column headers
    field_to_header = {
        "last_verified": "last verified",
        "verified_by": "verified by",
    }
    target_header = field_to_header.get(field.lower(), field.lower())

    lines = content.splitlines()
    headers = []
    header_found = False
    old_value = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if not header_found:
            headers = [c.lower().strip() for c in cells]
            header_found = True
            continue
        # Skip separator row
        if cells and all(set(c.strip()) <= {"-", ":"} for c in cells):
            continue
        # Data row — find and update the target column
        if target_header in headers and len(cells) >= len(headers):
            col_idx = headers.index(target_header)
            if old_value is None:
                old_value = cells[col_idx].strip()
            cells[col_idx] = f" {value} "
            lines[i] = "| " + " | ".join(c if c.startswith(" ") else f" {c} " for c in cells).replace("  ", " ") + " |"
            # Rebuild more carefully to preserve alignment
            lines[i] = "| " + " | ".join(c.strip() for c in cells) + " |"

    ws = _shared.workspace_root()
    full_path = os.path.join(ws, path)
    with open(full_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return old_value if old_value else ""

def mutate_lock_field(field, value):
    """Mutate a field in LOCK.md. Returns old value."""
    path = "LOCK.md"
    content = _shared.read_file(path)
    if content is None:
        return None

    lines = content.splitlines()
    old_value = None
    for i, line in enumerate(lines):
        m = re.match(rf'^(\s*){re.escape(field)}\s*:\s*(.*)', line)
        if m:
            old_value = m.group(2).strip()
            lines[i] = f'{m.group(1)}{field}: {value}'
            break

    ws = _shared.workspace_root()
    full_path = os.path.join(ws, path)
    with open(full_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return old_value

def do_append(rel_path, line):
    """Append a line to a file, using the same allowlist as cmd_append."""
    if not _is_allowed_append_target(rel_path):
        print(f"WARNING: {rel_path} not in append allowlist, skipping", file=sys.stderr)
        return
    ws = _shared.workspace_root()
    full_path = os.path.join(ws, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "a") as f:
        f.write(line.rstrip("\n") + "\n")


__all__ = [
    "mutate_longrunner_field",
    "mutate_dispatch_field",
    "mutate_manifest_field",
    "mutate_lock_field",
    "do_append",
]
