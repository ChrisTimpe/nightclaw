"""nightclaw_engine.commands.bundle — R5 bundle executor + schema render/lint.

Hosts the generic R5 transition executor (``bundle-exec``), bundle spec
validator (``validate-bundles``), and the deterministic REGISTRY rendering
/ linting commands (``schema-render`` / ``schema-lint``).

Per-target mutators (longrunner/dispatch/manifest/lock) and the shared
append primitive live in the sibling module ``bundle_mutators`` (split out
in Pass 6 to honor the ≤700 LOC per-module ceiling). External callers
should go through ``cmd_bundle_exec``.

Pass 9 migration — single source of truth
-----------------------------------------
``parse_r5_bundle()`` used to regex-parse ``orchestration-os/REGISTRY.md``
(rendered prose) to reconstruct the R5 bundle spec at runtime. Pass 9
routed this through ``spec_from_model()``, which projects the typed
``SchemaModel.bundles`` tuple (loaded from ``orchestration-os/schema/bundles.yaml``)
into the exact dict shape ``cmd_bundle_exec`` consumes.

The regex path is kept as a deprecated fallback, reachable only when the
schema model is unavailable (should be unreachable in production) or when
the env var ``NIGHTCLAW_BUNDLE_LEGACY_PARSER=1`` is set for drift-audit
runs. Framework consequence: any bundle declared in ``bundles.yaml`` is
immediately executable — no Python changes required.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import _shared
from .append import _is_allowed_append_target
from .bundle_mutators import (
    mutate_longrunner_field,
    mutate_dispatch_field,
    mutate_manifest_field,
    mutate_lock_field,
    do_append,
)


def _load_schema_model():
    """Load the typed SchemaModel for bundle spec lookup. Returns None if
    unavailable — caller must be prepared to fall back to the legacy
    regex parser. Isolated so ``cmd_bundle_exec`` + ``spec_from_model``
    share the same cache-friendly loader."""
    try:
        from nightclaw_engine.schema.loader import load as _load
        if _shared.ROOT is None:
            return None
        return _load(_shared.ROOT / "orchestration-os" / "schema")
    except Exception:
        return None


def spec_from_model(model, bundle_name: str) -> Optional[Dict[str, Any]]:
    """Project a ``SchemaModel`` BundleSpec into the dict shape that
    ``cmd_bundle_exec`` consumes.

    Framework contract: the keys emitted here define the runtime bundle
    protocol. Any bundle added to ``bundles.yaml`` flows through this
    function with zero Python changes. Returns ``None`` if the bundle is
    not declared.

    Output shape (stable — validate-bundles + cmd_bundle_exec depend on it):
        {
          "args":          list[str],                  # declared arg order preserved
          "validates":     list[str],                  # guard expressions
          "writes":        list[{"target": str,
                                  "fields": dict[str, str]}],  # order preserved
          "appends":       list[{"file": str, "line": str}],
          "notify":        None | dict[str, Any],
          "returns":       str,                        # first whitespace-delim
                                                        #   token of YAML returns
          "write_targets": list[str],                  # parallel to writes[].target
        }
    """
    spec_src = model.bundle(bundle_name) if model is not None else None
    if spec_src is None:
        return None

    writes: List[Dict[str, Any]] = []
    write_targets: List[str] = []
    # BundleSpec.writes is Dict[str, Dict[str, Any]] — Python 3.7+ preserves
    # dict insertion order, and PyYAML safe_load yields ordered dicts, so
    # iterating .items() preserves the YAML WRITES order (which governs
    # CHANGE-LOG row ordering).
    for target, fields in (spec_src.writes or {}).items():
        writes.append({
            "target": target,
            "fields": {str(k): str(v) for k, v in (fields or {}).items()},
        })
        write_targets.append(target)

    appends: List[Dict[str, str]] = []
    for file_path, line_template in (spec_src.append or {}).items():
        appends.append({"file": str(file_path), "line": str(line_template)})

    # Match parse_r5_bundle's ``returns`` semantics exactly: regex was
    # ``RETURNS:\s*(\S+)`` — the first whitespace-delimited token. This
    # matters for pa_invoke whose YAML value is ``AUTHORIZED | BLOCKED``
    # but whose stdout must stay ``RETURNS:AUTHORIZED``.
    returns_raw = (spec_src.returns or "").strip()
    returns = returns_raw.split()[0] if returns_raw else "SUCCESS"

    return {
        "args": list(spec_src.args),
        "validates": list(spec_src.validates),
        "writes": writes,
        "appends": appends,
        "notify": dict(spec_src.notify) if isinstance(spec_src.notify, dict) else None,
        "returns": returns,
        "write_targets": write_targets,
    }


def parse_r5_bundle(bundle_name):
    """Return a bundle spec dict, or ``None`` if the bundle is not declared.

    Pass 9: prefers the typed ``SchemaModel`` (from ``bundles.yaml``). If
    the model cannot be loaded — or the deprecated env var
    ``NIGHTCLAW_BUNDLE_LEGACY_PARSER=1`` forces it — the historical regex
    path over ``REGISTRY.md`` is used instead. The regex path is retained
    solely as a drift-detection fallback; production reads the model.
    """
    force_legacy = os.environ.get("NIGHTCLAW_BUNDLE_LEGACY_PARSER") == "1"
    if not force_legacy:
        model = _load_schema_model()
        if model is not None:
            spec = spec_from_model(model, bundle_name)
            if spec is not None:
                return spec
            # Model loaded but bundle not declared → authoritative None.
            # (Do NOT fall through to regex; the YAML is the source of truth.)
            return None
        # Model unavailable (e.g. _shared.ROOT not yet bound, PyYAML missing,
        # or schema dir absent) — fall through to legacy parser.

    return _parse_r5_bundle_legacy(bundle_name)


def _parse_r5_bundle_legacy(bundle_name):
    """Deprecated — regex parser over rendered REGISTRY.md prose.

    Retained for:
      1. ``NIGHTCLAW_BUNDLE_LEGACY_PARSER=1`` drift audits (compares model
         output to regex output on the same repo state).
      2. Emergency fallback if the schema loader is wedged.

    Do not extend. Any new bundle semantics belong in ``bundles.yaml`` +
    ``spec_from_model``.
    """
    content = _shared.read_file("orchestration-os/REGISTRY.md")
    if content is None:
        return None

    # Find the bundle section — R5 DEFINITIONS are bare "BUNDLE:<name>" on their own line.
    # R4 REFERENCES look like "BUNDLE:<name> → WRITES → ..." — skip those.
    # R3 REFERENCES look like "... | BUNDLE:<name> | ..." — also skip.
    # R5 definition: line.strip() == "BUNDLE:<name>" exactly (no → or | after)
    pattern = rf'^BUNDLE:{re.escape(bundle_name)}$'
    lines = content.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(pattern, line.strip()):
            start = i
            break
    if start is None:
        return None

    # Find end of bundle (next bare BUNDLE: definition or ## or ---)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        # Only stop on bare BUNDLE definitions (no → arrows), section headers, or dividers
        if (stripped.startswith("BUNDLE:") and "→" not in stripped and "|" not in stripped) or stripped.startswith("## ") or stripped == "---":
            end = i
            break

    block = "\n".join(lines[start:end])
    spec = {"args": [], "validates": [], "writes": [], "appends": [], "notify": None, "returns": "SUCCESS", "write_targets": []}

    # Parse TRIGGER (documentation only)
    # Parse ARGS
    args_m = re.search(r'ARGS:\s*(.+)', block)
    if args_m:
        args_str = args_m.group(1).strip()
        spec["args"] = [a.strip().strip(",") for a in args_str.split(",") if a.strip()]

    # Parse VALIDATES
    for m in re.finditer(r'VALIDATES:\s*\n((?:\s+-\s+.+\n?)+)', block):
        for v_line in m.group(1).strip().splitlines():
            v_line = v_line.strip().lstrip("- ").strip()
            if v_line:
                spec["validates"].append(v_line)
    # Simpler single-line validates
    for m in re.finditer(r'VALIDATES:\s*(.+)', block):
        vals = m.group(1).strip()
        if vals and not vals.startswith("\n"):
            for v in vals.split("|"):
                v = v.strip()
                if v:
                    spec["validates"].append(v)

    # Parse WRITES sections
    # Format: WRITES: LONGRUNNER:{slug}: or WRITES: PROJECTS/[slug]/LONGRUNNER.md →
    writes_section = False
    current_target = None
    current_fields = {}
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("WRITES:"):
            writes_section = True
            # Check if target is on same line
            rest = stripped[7:].strip()
            if rest:
                target_m = re.match(r'([\w{}\[\]/.*-]+(?::\{?\w+\}?)?)(\s*[→:])?\s*(.*)?', rest)
                if target_m:
                    if current_target and current_fields:
                        spec["writes"].append({"target": current_target, "fields": dict(current_fields)})
                        spec["write_targets"].append(current_target)
                    current_target = target_m.group(1).strip().rstrip(":")
                    current_fields = {}
                    if target_m.group(3):
                        # Inline field=value pairs
                        for pair in target_m.group(3).split(","):
                            pair = pair.strip()
                            if "=" in pair:
                                k, v = pair.split("=", 1)
                                current_fields[k.strip()] = v.strip()
            continue

        if writes_section:
            # New target (match against raw line to check indentation)
            target_m = re.match(r'(LONGRUNNER|DISPATCH|LOCK|NOTIFY|MEMORY|MANIFEST)(?::(\{?\w+\}?))?\s*:', stripped)
            if target_m:
                if current_target and current_fields:
                    spec["writes"].append({"target": current_target, "fields": dict(current_fields)})
                    spec["write_targets"].append(current_target)
                current_target = stripped.rstrip(":").strip()
                current_fields = {}
                continue

            # Field = value within current target
            field_m = re.match(r'([\w.]+)\s*=\s*(.+)', stripped)
            if field_m and current_target:
                current_fields[field_m.group(1).strip()] = field_m.group(2).strip()
                continue

            # End of WRITES
            if stripped.startswith("APPEND:") or stripped.startswith("NOTIFY:") or stripped.startswith("RETURNS:") or stripped == "" or stripped.startswith("VALIDATES:"):
                if current_target and current_fields:
                    spec["writes"].append({"target": current_target, "fields": dict(current_fields)})
                    spec["write_targets"].append(current_target)
                    current_target = None
                    current_fields = {}
                writes_section = False

    # Catch last write group
    if current_target and current_fields:
        spec["writes"].append({"target": current_target, "fields": dict(current_fields)})
        spec["write_targets"].append(current_target)

    # Parse APPEND section — multi-line: file: line_template entries
    append_section = False
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("APPEND:") and not stripped.startswith("APPEND-"):
            append_section = True
            # Check for inline content after APPEND:
            rest = stripped[7:].strip()
            if rest:
                # Single-line APPEND: file: template
                colon_idx = rest.find(":")
                if colon_idx > 0:
                    spec["appends"].append({
                        "file": rest[:colon_idx].strip(),
                        "line": rest[colon_idx + 1:].strip()
                    })
                append_section = False
            continue
        if append_section:
            if not stripped or stripped.startswith("NOTIFY:") or stripped.startswith("RETURNS:") or stripped.startswith("NEVER") or stripped.startswith("#") or stripped.startswith("AUTHORITY:"):
                append_section = False
                continue
            # Parse "file: line_template" entries (indented under APPEND:)
            colon_idx = stripped.find(":")
            if colon_idx > 0:
                file_path = stripped[:colon_idx].strip()
                line_template = stripped[colon_idx + 1:].strip()
                if file_path and line_template:
                    spec["appends"].append({"file": file_path, "line": line_template})

    # Parse NOTIFY section — multi-line key: value pairs
    notify_section = False
    notify_data = {}
    for line in block.splitlines():
        stripped = line.strip()
        if stripped == "NOTIFY:" or (stripped.startswith("NOTIFY:") and not stripped.startswith("NOTIFY: ")):
            notify_section = True
            continue
        if notify_section:
            # Stop on section boundaries
            if stripped.startswith("RETURNS:") or stripped.startswith("NEVER") or stripped.startswith("AUTHORITY:") or stripped.startswith("APPEND:") or stripped.startswith("WRITES:"):
                notify_section = False
                continue
            kv = re.match(r'(\w[\w_]*)\s*:\s*(.+)', stripped)
            if kv:
                notify_data[kv.group(1).strip()] = kv.group(2).strip()
            elif stripped and not stripped.startswith("#"):
                # End of NOTIFY section (hit unrecognized content)
                notify_section = False
    if notify_data:
        spec["notify"] = notify_data

    # Parse RETURNS
    returns_m = re.search(r'RETURNS:\s*(\S+)', block)
    if returns_m:
        spec["returns"] = returns_m.group(1).strip()

    return spec

def resolve_expression(expr, args, mode="strict"):
    """Resolve an R5 expression to a concrete value.

    mode='strict' (default, for MUTATE fields) — exactly 4 types:
    - LITERAL: bare value written verbatim
    - ARG: {name} → substitute from args
    - COMPUTED: {NOW}, {TODAY}, {NOW+field}
    - NULL: ~ → clear marker

    mode='template' (for APPEND lines, NOTIFY fields):
    - Also allows embedded references: "text {arg} more text"
    """
    if expr is None:
        return ""
    expr = str(expr).strip()

    if expr == "~":
        return "~"  # NULL marker

    # Check for pure ARG / COMPUTED reference: {name}, {NOW}, {TODAY},
    # or {NOW+field}. The ``NOW+`` form is matched explicitly because
    # ``\w`` excludes ``+``; without the alternation the pattern would
    # reject e.g. ``{NOW+transition_timeout_days}`` and silently fall
    # through to the LITERAL branch, writing the placeholder verbatim
    # into state files. See tests/engine_e2e/test_bundle_positive_path.py::
    # test_phase_transition_resolves_... for the regression coverage.
    arg_m = re.match(r'^\{(NOW\+\w+|\w+)\}$', expr)
    if arg_m:
        key = arg_m.group(1)
        if key == "NOW":
            return _shared.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        if key == "TODAY":
            return _shared.now_utc().strftime("%Y-%m-%d")
        if key.startswith("NOW+"):
            field = key[4:]
            # Read timeout (in days) from the LONGRUNNER field named
            # after the ``+`` — e.g. ``{NOW+transition_timeout_days}``
            # reads ``transition_timeout_days``. Defaults to 3 days if
            # the LONGRUNNER cannot be read or the field is missing /
            # non-numeric; this matches the audit.cmd_transition_expiry
            # fallback so the two codepaths agree on the same number.
            slug = args.get("slug", "")
            lr = _shared.parse_longrunner(slug) if slug else None
            raw = (lr or {}).get(field, "3")
            try:
                timeout_days = int(str(raw).strip())
            except (TypeError, ValueError):
                timeout_days = 3
            future = _shared.now_utc() + timedelta(days=timeout_days)
            return future.strftime("%Y-%m-%dT%H:%M:%SZ")
        return args.get(key, f"UNRESOLVED:{key}")

    # Embedded references: "text {arg} more text"
    # Only allowed in template mode (APPEND lines, NOTIFY fields).
    # MUTATE fields must use the 4 strict types above.
    if mode == "template":
        def replace_ref(m):
            key = m.group(1)
            if key == "NOW":
                return _shared.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
            if key == "TODAY":
                return _shared.now_utc().strftime("%Y-%m-%d")
            return args.get(key, f"UNRESOLVED:{key}")
        return re.sub(r'\{(\w+)\}', replace_ref, expr)

    # Strict mode: expression didn't match any of the 4 types.
    # Return as LITERAL (bare values like 'ACTIVE', '0', 'none').
    return expr

def evaluate_guard(guard_str, args):
    """Evaluate a VALIDATES guard condition.
    Supports: field NOT_EMPTY, field EQUALS value, field IN enum_list
    """
    slug = args.get("slug", "")

    # Parse guard: "LONGRUNNER:{slug}.field NOT_EMPTY" or "field == value"
    parts = guard_str.split()
    if len(parts) < 2:
        return True  # Can't parse, pass by default

    field_ref = parts[0]
    condition = parts[1] if len(parts) > 1 else "NOT_EMPTY"
    expected = parts[2] if len(parts) > 2 else None

    # Resolve field value
    if "LONGRUNNER" in field_ref:
        # Extract field name after the last dot that follows the slug reference
        field_name = re.sub(r'LONGRUNNER:\{?\w+\}?\.', '', field_ref)
        lr = _shared.parse_longrunner(slug)
        if lr is None:
            print(f"ERROR:LONGRUNNER_NOT_FOUND:{slug}")
            return False
        actual = lr.get(field_name, "")
    elif "DISPATCH" in field_ref:
        field_name = re.sub(r'DISPATCH:\{?\w+\}?\.', '', field_ref)
        rows = _shared.parse_dispatch_table()
        actual = ""
        for row in rows:
            row_slug = row.get("project_slug", row.get("slug", ""))
            if row_slug.strip() == slug:
                actual = row.get(field_name, "")
                break
    else:
        actual = args.get(field_ref, "")

    actual = str(actual).strip()

    if condition == "NOT_EMPTY":
        return bool(actual) and actual not in ("~", "null", "None", "none", "", '""')
    elif condition in ("==", "EQUALS"):
        return actual.upper() == str(expected).upper()
    elif condition == "IN":
        return actual.upper() in [v.strip().upper() for v in str(expected).split(",")]

    return True  # Unknown condition — pass by default

def apply_mutate(target, field, value, args):
    """Apply a field mutation to a target file. Returns the old value, or None if append-only."""
    slug = args.get("slug", "")

    if "LONGRUNNER" in target:
        return mutate_longrunner_field(slug, field, value)
    elif "DISPATCH" in target:
        return mutate_dispatch_field(slug, field, value)
    elif "LOCK" in target:
        return mutate_lock_field(field, value)
    elif "MANIFEST" in target:
        return mutate_manifest_field(field, value)
    else:
        print(f"WARNING: unknown mutate target {target}", file=sys.stderr)
        return None

def _list_bundle_names() -> List[str]:
    """Return bundle names from the schema model. Used by ``--help``.

    Sources from ``SchemaModel.bundles`` (the authoritative YAML) — not
    REGISTRY.md — matching the Pass 9 convention in ``cmd_validate_bundles``.
    Returns an empty list on any schema-load error so ``--help`` degrades
    gracefully in a broken tree.
    """
    try:
        model = _load_schema_model()
    except Exception:
        return []
    if model is None:
        return []
    return [b.name for b in model.bundles]


def cmd_bundle_exec():
    """Generic transition executor. Reads R5 bundle spec, resolves values, validates, writes.
    Usage: bundle-exec <bundle_name> [key=value ...] [--stdin]
    With --stdin: reads JSON args from stdin.
    """
    # --help / -h handling. Intentionally prints to stdout and returns 0 so
    # shell pipelines can discover bundle contracts without triggering the
    # error-exit path. Output goes to stdout (advisory surface) — does NOT
    # affect any deterministic gate tool string (Lock 1).
    _help_flags = {"--help", "-h"}
    if len(sys.argv) < 3 or (len(sys.argv) >= 3 and sys.argv[2] in _help_flags):
        try:
            names = sorted(_list_bundle_names())
        except Exception:
            names = []
        print("Usage: bundle-exec <bundle_name> [key=value ...] [--stdin] [--file=PATH]")
        print("       bundle-exec <bundle_name> --help      # show that bundle's args/writes")
        print("       bundle-exec --help                    # this message + list bundles")
        if names:
            print("")
            print("Available bundles:")
            for n in names:
                print(f"  - {n}")
        # Return 0 for the explicit --help form, 2 for the bare missing-arg form.
        sys.exit(0 if (len(sys.argv) >= 3 and sys.argv[2] in _help_flags) else 2)

    bundle_name = sys.argv[2]

    # Per-bundle help: ``bundle-exec <name> --help``. Prints the declared
    # ARGS + WRITES + GUARDS for the named bundle to stdout, exit 0.
    if len(sys.argv) >= 4 and sys.argv[3] in _help_flags:
        spec = parse_r5_bundle(bundle_name)
        if spec is None:
            print(f"ERROR:BUNDLE_NOT_FOUND:{bundle_name}")
            sys.exit(1)
        print(f"Bundle: {bundle_name}")
        decl_args = spec.get("args", []) or []
        print(f"  args:    {', '.join(decl_args) if decl_args else '(none)'}")
        guards = spec.get("guards", []) or []
        if guards:
            print("  guards:")
            for g in guards:
                print(f"    - {g}")
        writes = spec.get("write_targets", []) or []
        if writes:
            print("  writes:")
            for w in writes:
                print(f"    - {w}")
        appends = spec.get("append_targets", []) or []
        if appends:
            print("  appends:")
            for a in appends:
                print(f"    - {a}")
        sys.exit(0)

    use_stdin = "--stdin" in sys.argv
    file_arg = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--file=")), None)

    # Parse args
    args = {}
    if use_stdin:
        import json
        args = json.loads(sys.stdin.read())
    elif file_arg:
        import json
        with open(file_arg) as f:
            args = json.loads(f.read())
    else:
        for arg in sys.argv[3:]:
            if arg == "--stdin" or arg.startswith("--file="):
                continue
            if "=" not in arg:
                print(f"ERROR: malformed arg (no =): {arg}", file=sys.stderr)
                sys.exit(2)
            k, v = arg.split("=", 1)
            args[k] = v

    # Parse R5 bundle spec from REGISTRY.md
    bundle_spec = parse_r5_bundle(bundle_name)
    if bundle_spec is None:
        print(f"ERROR:BUNDLE_NOT_FOUND:{bundle_name}")
        sys.exit(1)

    # Validate required args
    declared_args = bundle_spec.get("args", [])
    for a in declared_args:
        if a not in args:
            print(f"ERROR:MISSING_ARG:{a} for BUNDLE:{bundle_name}")
            sys.exit(1)

    # Check PROTECTED paths — consult the schema-driven gate first, then
    # the legacy hardcoded set as defense-in-depth. Either source
    # rejecting the write stops the bundle before any file is touched.
    try:
        from nightclaw_engine.schema.loader import load as _load_schema_gate
        from nightclaw_engine.engine import gates as _gates_mod
        _gate_model = _load_schema_gate(_shared.ROOT / "orchestration-os" / "schema")
    except Exception:
        _gate_model = None
        _gates_mod = None

    # H-SEC-02: if the bundle's write targets reference ``{slug}``, the
    # slug will be substituted directly into a filesystem path. Enforce the
    # canonical slug format *before* substitution so the later path never
    # contains traversal sequences. Bundles whose targets do not reference
    # ``{slug}`` (e.g. append-only bundles writing to audit/ logs) are not
    # subject to this check — their targets are static.
    _needs_slug = any(
        "{slug}" in (t.split(":", 1)[-1] if ":" in t else t)
        for t in bundle_spec.get("write_targets", [])
    )
    if _needs_slug:
        _slug = args.get("slug", "")
        if not _shared.is_valid_slug(_slug):
            print(f"ERROR:INVALID_SLUG:{_slug!r} for BUNDLE:{bundle_name}")
            sys.exit(1)

    for target in bundle_spec.get("write_targets", []):
        rel = target.split(":", 1)[-1] if ":" in target else target
        # Resolve slug-based paths
        slug = args.get("slug", "")
        if "{slug}" in rel:
            rel = rel.replace("{slug}", slug)
        # Schema-driven protection (CL5 + R3 tier=PROTECTED).
        if _gate_model is not None and _gates_mod is not None:
            if _gates_mod.is_protected(_gate_model, rel):
                print(f"ERROR:PROTECTED_WRITE_BLOCKED:{rel}")
                sys.exit(1)
        # Legacy hardcoded set — retained as belt-and-suspenders.
        for pp in _shared.PROTECTED_PATHS:
            if rel == pp or rel.endswith(pp):
                print(f"ERROR:PROTECTED_WRITE_BLOCKED:{rel}")
                sys.exit(1)

    # Execute validates
    for v in bundle_spec.get("validates", []):
        if not evaluate_guard(v, args):
            print(f"ERROR:GUARD_FAILED:{v}")
            sys.exit(1)

    # Resolve and apply writes
    changes = []  # Track (field_path, old, new) for CHANGE-LOG

    for write_group in bundle_spec.get("writes", []):
        target = write_group["target"]
        for field, expr in write_group["fields"].items():
            resolved = resolve_expression(expr, args)
            old_val = apply_mutate(target, field, resolved, args)
            if old_val is not None and old_val != resolved:
                changes.append((target, field, old_val, resolved))

    # Emit CHANGE-LOG for mutations
    # CL3 SCOPE:EXCLUDE: timestamp-only updates to INTEGRITY-MANIFEST.md are excluded.
    run_id = args.get("run_id", "UNKNOWN")
    now_str = _shared.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Emit CASCADE_CHECK audit rows for every R4 edge whose SOURCE is a
    # file this bundle just mutated. Downstream readers (manager T8,
    # auditors) use these to detect when a rendered view is stale relative
    # to its source. One row per (source_file, edge_type, target_file).
    if _gate_model is not None and _gates_mod is not None:
        cascade_sources = set()
        for target, field, old_val, new_val in changes:
            rel_src = target
            slug = args.get("slug", "")
            if "{slug}" in rel_src:
                rel_src = rel_src.replace("{slug}", slug)
            cascade_sources.add(rel_src)
        for rel_src in sorted(cascade_sources):
            for edge in _gates_mod.cascade_for(_gate_model, rel_src):
                cc_line = (
                    f"FILE:{rel_src}#CASCADE_CHECK|{edge.type}|{edge.target}|worker|"
                    f"{run_id}|{now_str}|{now_str}|bundle-{bundle_name}|BUNDLE:{bundle_name}"
                )
                do_append("audit/CHANGE-LOG.md", cc_line)

    for target, field, old_val, new_val in changes:
        # Skip MANIFEST — CL1 SCOPE:EXCLUDE for timestamp-only integrity manifest updates
        if "MANIFEST" in target:
            continue
        # Build field_path
        slug = args.get("slug", "")
        if "LONGRUNNER" in target:
            fp = f"FILE:PROJECTS/{slug}/LONGRUNNER.md#{field}"
        elif "DISPATCH" in target:
            fp = f"FILE:ACTIVE-PROJECTS.md#{slug}.{field}"
        elif "LOCK" in target:
            fp = f"FILE:LOCK.md#{field}"
        else:
            fp = f"FILE:{target}#{field}"
        cl_line = f"{fp}|{old_val}|{new_val}|worker|{run_id}|{now_str}|{now_str}|bundle-{bundle_name}|BUNDLE:{bundle_name}"
        do_append("audit/CHANGE-LOG.md", cl_line)

    # Execute appends
    for append_entry in bundle_spec.get("appends", []):
        target_file = resolve_expression(append_entry["file"], args, mode="template")
        line_template = append_entry["line"]
        resolved_line = resolve_expression(line_template, args, mode="template")
        do_append(target_file, resolved_line)

    # Execute notify
    notify = bundle_spec.get("notify")
    if notify:
        priority = resolve_expression(notify.get("priority", "MEDIUM"), args, mode="template")
        action_text = resolve_expression(notify.get("action_text", ""), args, mode="template")
        context = resolve_expression(notify.get("context", ""), args, mode="template")
        slug = args.get("slug", "system")
        status = resolve_expression(notify.get("status", "ESCALATION"), args, mode="template")
        notify_line = f"{now_str} | Priority: {priority} | Project: {slug} | Status: {status}"
        if context:
            notify_line += f"\n{context}"
        if action_text:
            notify_line += f"\nAction required: {action_text}"
        do_append("NOTIFICATIONS.md", notify_line)

    # Print returns
    returns = bundle_spec.get("returns", "SUCCESS")
    print(f"RETURNS:{returns}")
    print(f"BUNDLE:{bundle_name} completed. {len(changes)} field(s) changed.")

def cmd_validate_bundles():
    """Parse all R5 bundles and verify syntax, ARG consistency, and PROTECTED paths.

    Pass 9: bundle name discovery sources from ``SchemaModel.bundles``
    rather than regex-scanning REGISTRY.md. The rendered markdown is a
    projection of the YAML; the YAML is authoritative.
    """
    model = _load_schema_model()
    if model is None:
        print("ERROR: cannot load schema model")
        sys.exit(1)

    bundle_names = [b.name for b in model.bundles]

    errors = []
    for name in bundle_names:
        spec = parse_r5_bundle(name)
        if spec is None:
            errors.append(f"BUNDLE:{name} — failed to parse")
            continue

        # Check for PROTECTED paths in write targets
        for target in spec.get("write_targets", []):
            for pp in _shared.PROTECTED_PATHS:
                if pp in target:
                    errors.append(f"BUNDLE:{name} — writes to PROTECTED path: {target}")

        # Check that VALIDATES guard conditions use a known operator.
        # evaluate_guard() returns True for unknown conditions (fail-open),
        # so a typo here silently disables the guard at runtime.
        _KNOWN_CONDITIONS = {"NOT_EMPTY", "EQUALS", "==", "IN"}
        for guard_str in spec.get("validates", []):
            parts = guard_str.split()
            if len(parts) >= 2 and parts[1] not in _KNOWN_CONDITIONS:
                errors.append(
                    f"BUNDLE:{name} — validates predicate has unknown condition: "
                    f"{parts[1]!r} in {guard_str!r}"
                )

        # Check that ARGS referenced in writes/appends are declared
        declared = set(spec.get("args", []))
        # Scan all expression values for {arg} references
        for wg in spec.get("writes", []):
            for field, expr in wg.get("fields", {}).items():
                for ref in re.findall(r'\{(\w+)\}', str(expr)):
                    if ref not in declared and ref not in ("NOW", "TODAY"):
                        if not ref.startswith("NOW+"):
                            errors.append(f"BUNDLE:{name} — WRITES references undeclared arg {{{ref}}} in {field}")

        for ae in spec.get("appends", []):
            for ref in re.findall(r'\{(\w+)\}', ae.get("line", "")):
                if ref not in declared and ref not in ("NOW", "TODAY"):
                    if not ref.startswith("NOW+"):
                        errors.append(f"BUNDLE:{name} — APPEND references undeclared arg {{{ref}}}")

        if not errors or not any(name in e for e in errors):
            print(f"BUNDLE:{name} — OK (args={declared})")

    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        print(f"\nRESULT:FAIL ({len(errors)} errors)")
        sys.exit(1)
    else:
        print(f"\nRESULT:PASS ({len(bundle_names)} bundles validated)")

def cmd_schema_render():
    """Render Tier A schema YAML to a deterministic REGISTRY.generated.md.

    Output contract (machine-parseable):
        SCHEMA-RENDER:OK:<fingerprint>:BYTES=<n>:PATH=<rel_path>
    On error:
        SCHEMA-RENDER:ERROR:<message>
    """
    from nightclaw_engine.schema.loader import SchemaError, load
    from nightclaw_engine.engine.render import render_markdown

    schema_dir = _shared.ROOT / "orchestration-os" / "schema"
    try:
        model = load(schema_dir)
    except SchemaError as exc:
        print(f"SCHEMA-RENDER:ERROR:{exc}")
        sys.exit(1)

    body = render_markdown(model)
    out_rel = "REGISTRY.generated.md"
    out_path = _shared.ROOT / out_rel
    out_path.write_text(body, encoding="utf-8")
    print(f"SCHEMA-RENDER:OK:{model.fingerprint}:BYTES={len(body.encode('utf-8'))}:PATH={out_rel}")

# ---------------------------------------------------------------------------
# schema-sync — in-place reconcile of REGISTRY.md rendered sections
# ---------------------------------------------------------------------------

# Section ID → renderer function name. Order matches render._render_sections().
_RENDER_SECTIONS = ("R1", "R2", "R3", "R4", "R5", "R6", "CL5")


def _generated_section_bodies(model):
    """Return dict {section_id: canonical_body_between_markers}.

    The canonical body is the full rendered section body with its leading
    ``## heading`` line stripped. The heading remains in REGISTRY.md as
    hand-authored navigation outside the marker pair. This makes the
    byte-equality invariant well-defined and section-local.
    """
    from nightclaw_engine.engine.render import (
        _render_r1, _render_r2, _render_r3, _render_r4,
        _render_r5, _render_r6, _render_cl5,
    )
    renderers = {
        "R1": _render_r1, "R2": _render_r2, "R3": _render_r3,
        "R4": _render_r4, "R5": _render_r5, "R6": _render_r6,
        "CL5": _render_cl5,
    }
    bodies = {}
    for sid in _RENDER_SECTIONS:
        lines = renderers[sid](model)
        # First line is the "## <title>" heading. Drop it, keep the rest verbatim.
        body_lines = lines[1:]
        # Canonical body representation: leading \n + joined lines + trailing \n
        # Matches the whitespace shape currently used (marker on its own line,
        # then a newline, then body, then newline, then closing marker).
        body = "\n" + "\n".join(body_lines) + "\n"
        bodies[sid] = body
    return bodies


_MARKER_OPEN_RE_FMT = (
    r'<!-- nightclaw:render section="{sid}"'
    r' source="orchestration-os/schema"'
    r' schema_fingerprint="[0-9a-f]{{64}}" -->'
)
_MARKER_CLOSE = "<!-- /nightclaw:render -->"


def _splice_section(text, sid, body):
    """Replace the body between the open and close markers for ``sid``.

    Returns (new_text, bytes_before, bytes_after) or raises ValueError if the
    marker pair cannot be located.
    """
    open_re = re.compile(_MARKER_OPEN_RE_FMT.format(sid=sid))
    m = open_re.search(text)
    if m is None:
        raise ValueError(f"schema-sync: open marker for section {sid} not found")
    after_open = m.end()
    close_idx = text.find(_MARKER_CLOSE, after_open)
    if close_idx == -1:
        raise ValueError(f"schema-sync: close marker for section {sid} not found")
    # Body currently occupies [after_open:close_idx].
    prior_body = text[after_open:close_idx]
    new_text = text[:after_open] + body + text[close_idx:]
    return new_text, len(prior_body.encode("utf-8")), len(body.encode("utf-8"))


def cmd_schema_sync():
    """Replace the bodies of REGISTRY.md rendered sections with generated content.

    Output contract:
        SCHEMA-SYNC:OK:<fingerprint>:SECTIONS=<n>:CHANGED=<m>
        SCHEMA-SYNC:NOOP:<fingerprint>:SECTIONS=<n>   (already byte-equal)
        SCHEMA-SYNC:ERROR:<message>

    The command is idempotent. Doctrine sections (R7 / CL1-CL4 / CL6) remain
    untouched — only the bytes between ``<!-- nightclaw:render section="X" -->``
    and the following ``<!-- /nightclaw:render -->`` are rewritten.
    """
    from nightclaw_engine.schema.loader import SchemaError, load

    schema_dir = _shared.ROOT / "orchestration-os" / "schema"
    try:
        model = load(schema_dir)
    except SchemaError as exc:
        print(f"SCHEMA-SYNC:ERROR:{exc}")
        sys.exit(1)

    registry_path = _shared.ROOT / "orchestration-os" / "REGISTRY.md"
    text = registry_path.read_text(encoding="utf-8")

    bodies = _generated_section_bodies(model)
    new_text = text
    changed = 0
    for sid in _RENDER_SECTIONS:
        try:
            new_text, prior_bytes, new_bytes = _splice_section(new_text, sid, bodies[sid])
        except ValueError as exc:
            print(f"SCHEMA-SYNC:ERROR:{exc}")
            sys.exit(1)
        # Track whether this section's body changed (prior != new body bytes)
        # We compare before/after by re-locating and reading.
        # Simpler: compare the body region; but prior_bytes/new_bytes only give sizes.
        # Track via pre-splice text lookup.
    # Determine changed sections by comparing splice-by-splice from original.
    changed = 0
    trial = text
    for sid in _RENDER_SECTIONS:
        open_re = re.compile(_MARKER_OPEN_RE_FMT.format(sid=sid))
        m = open_re.search(trial)
        after_open = m.end()
        close_idx = trial.find(_MARKER_CLOSE, after_open)
        prior_body = trial[after_open:close_idx]
        if prior_body != bodies[sid]:
            changed += 1
        trial = trial[:after_open] + bodies[sid] + trial[close_idx:]

    if new_text == text:
        print(f"SCHEMA-SYNC:NOOP:{model.fingerprint}:SECTIONS={len(_RENDER_SECTIONS)}")
        return

    registry_path.write_text(new_text, encoding="utf-8")
    print(f"SCHEMA-SYNC:OK:{model.fingerprint}:SECTIONS={len(_RENDER_SECTIONS)}:CHANGED={changed}")


def cmd_schema_lint():
    """Lint Tier A schema: load YAML, re-render, compare to previous render.

    Output:
        SCHEMA-LINT:OK:<fingerprint>          (schema loads, render is stable)
        SCHEMA-LINT:DRIFT:<fingerprint>:<n>   (render differs from REGISTRY.generated.md by n bytes)
        SCHEMA-LINT:ERROR:<message>
    """
    from nightclaw_engine.schema.loader import SchemaError, load
    from nightclaw_engine.engine.render import render_markdown

    schema_dir = _shared.ROOT / "orchestration-os" / "schema"
    try:
        model = load(schema_dir)
    except SchemaError as exc:
        print(f"SCHEMA-LINT:ERROR:{exc}")
        sys.exit(1)

    fresh = render_markdown(model)
    generated_path = _shared.ROOT / "REGISTRY.generated.md"
    if not generated_path.exists():
        print(f"SCHEMA-LINT:OK:{model.fingerprint}:NOTE=no_prior_render")
        return

    prior = generated_path.read_text(encoding="utf-8")
    if prior == fresh:
        print(f"SCHEMA-LINT:OK:{model.fingerprint}")
    else:
        delta = abs(len(fresh.encode("utf-8")) - len(prior.encode("utf-8")))
        print(f"SCHEMA-LINT:DRIFT:{model.fingerprint}:DELTA_BYTES={delta}")
        sys.exit(1)


__all__ = ["parse_r5_bundle", "resolve_expression", "evaluate_guard", "apply_mutate", "mutate_longrunner_field", "mutate_dispatch_field", "mutate_manifest_field", "mutate_lock_field", "do_append", "cmd_bundle_exec", "cmd_validate_bundles", "cmd_schema_render", "cmd_schema_sync", "cmd_schema_lint"]
