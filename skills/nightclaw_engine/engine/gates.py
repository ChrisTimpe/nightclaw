"""nightclaw_engine.engine.gates — pure-function validators over SchemaModel.

These are the Merge-2 gap closures. Every mutator in :mod:`nightclaw_engine`
routes through these gates before it writes, so any violation of R2 / R3 / R4
/ CL5 is rejected by code rather than left as LLM discipline.

All gate functions are:
  * pure: take a ``SchemaModel`` + inputs, return a typed result, no I/O.
  * deterministic: same inputs -> same output, byte-identical.
  * cheap: O(objects + fields + routes) and cache-friendly because the loader
    memoises ``SchemaModel`` by mtime.

Nothing here mutates workspace state. The mutators in ``nightclaw_engine.mutators``
are the only files that write; they call these gates first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from ..schema.loader import Edge, FieldSpec, RouteRule, SchemaModel


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateResult:
    """Outcome of a single gate call.

    ``ok`` is True on pass. ``code`` is a stable machine token (e.g.
    ``"R2_ENUM"``) suitable for audit row emission. ``detail`` is a short
    human hint. ``details`` carries structured key=value pairs for logging.
    """
    ok: bool
    code: str
    detail: str = ""
    details: Tuple[Tuple[str, str], ...] = ()

    def as_line(self) -> str:
        """Machine-parseable single-line form: ``OK:CODE`` or ``VIOLATION:CODE:detail``."""
        head = "OK" if self.ok else "VIOLATION"
        bits = [head, self.code]
        if self.detail:
            bits.append(self.detail)
        return ":".join(bits)


_OK = GateResult(True, "OK")


# ---------------------------------------------------------------------------
# R2 — field contract validation
# ---------------------------------------------------------------------------

# Canonical type predicates. Keyed by the ``type`` column in fields.yaml.
# Returning True means the raw string value *could* represent the declared
# type. These are intentionally permissive about whitespace/case handling
# that the markdown files already accept.
_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# YYYY-MM-DD[ HH:MM[:SS] [tz]]
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?(\s+\S+|[+-]\d{2}:?\d{2}|Z)?$")
_ISO8601Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_PATH_RE = re.compile(r"^[A-Za-z0-9_./{}\[\]-]+$")


def _is_int(v: str) -> bool:
    try:
        int(v.strip())
        return True
    except Exception:
        return False


def _type_ok(kind: str, value: str) -> bool:
    k = kind.strip().upper()
    v = (value or "").strip()
    if not v:
        # Emptiness is handled by REQ gate, not TYPE gate.
        return True
    if k == "INT":
        return _is_int(v)
    if k == "HASH":
        return bool(_HASH_RE.match(v))
    if k == "DATE":
        return bool(_DATE_RE.match(v))
    if k == "DATETIME":
        return bool(_DATETIME_RE.match(v))
    if k == "ISO8601Z":
        return bool(_ISO8601Z_RE.match(v))
    if k == "TOKEN":
        return bool(_TOKEN_RE.match(v))
    if k == "PATH":
        return bool(_PATH_RE.match(v))
    if k in ("TEXT", "STRING", "ENUM"):
        return True
    # Unknown type labels default to permissive; manifest check catches drift.
    return True


_ENUM_SPLIT = re.compile(r"\s*\|\s*")

# Canonical null markers accepted for nullable (req=n) typed fields.
# Markdown tables across the codebase use these to denote "no value yet":
#   em-dash (U+2014), hyphen, ASCII dash, the literal word "none", "n/a".
# We treat them as equivalent to an empty cell for TYPE-gate purposes.
# REQ gate still enforces required-ness on its own.
_NULL_MARKERS = frozenset({"\u2014", "-", "--", "none", "n/a", "na"})


def _is_null_marker(value: str) -> bool:
    """True if ``value`` is a recognized null-marker token (case-insensitive)."""
    return (value or "").strip().lower() in _NULL_MARKERS


def _parse_enum(constraint: str) -> Optional[List[str]]:
    """Pull ``A|B|C`` tokens out of an R2 constraint string if they look enum-shaped.

    We accept the first ``A|B|C`` run containing 2+ all-caps tokens. This
    covers every enum in the current ``fields.yaml`` without false-positives
    on prose like ``"none OR surfaced-YYYY-MM-DD"``.
    """
    if not constraint:
        return None
    for chunk in re.findall(r"[A-Z][A-Z0-9_-]+(?:\|[A-Z][A-Z0-9_-]+)+", constraint):
        toks = _ENUM_SPLIT.split(chunk)
        toks = [t.strip() for t in toks if t.strip()]
        if len(toks) >= 2:
            return toks
    return None


def find_field(model: SchemaModel, obj: str, field: str) -> Optional[FieldSpec]:
    """Locate an R2 FieldSpec by (OBJ, field name). Case-sensitive on obj."""
    for f in model.fields:
        if f.obj == obj and f.field == field:
            return f
    return None


def validate_field(
    model: SchemaModel,
    obj: str,
    field: str,
    value: str,
) -> GateResult:
    """Validate a single field value against its R2 contract.

    Returns a :class:`GateResult` with one of:
      * ``OK``                 — value passes REQ + TYPE + ENUM checks.
      * ``R2_UNKNOWN_FIELD``   — (obj, field) pair not in R2.
      * ``R2_REQUIRED_EMPTY``  — REQ=y and value is empty.
      * ``R2_TYPE``            — value shape doesn't match declared type.
      * ``R2_ENUM``            — value not in parsed enum set.
    """
    spec = find_field(model, obj, field)
    if spec is None:
        return GateResult(False, "R2_UNKNOWN_FIELD", f"{obj}.{field}")

    raw = (value or "").strip()
    required = spec.req.lower() == "y"

    if required and not raw:
        return GateResult(False, "R2_REQUIRED_EMPTY", f"{obj}.{field}")

    # Null-marker tolerance: for OPTIONAL (req=n) typed fields, the markdown
    # surfaces across the codebase use em-dash / "none" / "-" as the "no
    # value yet" marker (see ACTIVE-PROJECTS.md, new-project.sh, etc.). These
    # are conventions, not schema. Treat them as equivalent to empty so the
    # TYPE gate does not flag legitimate placeholder cells. Required fields
    # still go through their own constraint path.
    if not required and raw and _is_null_marker(raw):
        return GateResult(True, "OK")

    if raw and not _type_ok(spec.type, raw):
        return GateResult(False, "R2_TYPE",
                          f"{obj}.{field} type={spec.type} value={raw[:40]}")

    if spec.type.strip().upper() == "ENUM":
        enum = _parse_enum(spec.constraint)
        if enum is not None and raw:
            # ENUM comparison is case-insensitive. The schema declares
            # canonical UPPERCASE tokens for documentation, but runtime
            # markdown surfaces use lowercase (active, blocked, ...) across
            # the codebase. Accept both; the schema value is still the
            # source of truth for allowed tokens, only case is relaxed.
            enum_norm = {e.upper() for e in enum}
            if raw.upper() not in enum_norm:
                return GateResult(False, "R2_ENUM",
                                  f"{obj}.{field} value={raw} expected={'|'.join(enum)}")

    return GateResult(True, "OK")


# ---------------------------------------------------------------------------
# R3 — routing + CL5 protection
# ---------------------------------------------------------------------------

# --- Endpoint identity helpers (shared by R3 route + R4 cascade lookups) ---
# Edge/route endpoint strings in the schema YAML sometimes carry a trailing
# free-text parenthetical note (e.g. "audit/CHANGE-LOG.md (via T4)"). The note
# is useful for rendering REGISTRY.md but poisons exact-match lookups. These
# helpers strip the note for comparison only; the original string is kept in
# the returned Edge/RouteRule so callers can still display it.
#
# Likewise, schema endpoints use "*" as a single-segment glob (e.g.
# "PROJECTS/*/LONGRUNNER.md"). A concrete query path like
# "PROJECTS/example/LONGRUNNER.md" must match that glob for forward and
# reverse cascade queries to return complete answers.
_NOTE_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _strip_note(s: str) -> str:
    """Remove a single trailing parenthetical note from a path-like string."""
    return _NOTE_RE.sub("", s)


def _norm(s: str) -> str:
    """Filesystem-style normalization used by every matcher."""
    return _strip_note(s).replace("\\", "/").strip().lstrip("./")


def _glob_to_regex(pattern: str) -> "re.Pattern[str]":
    """Translate a schema glob into an anchored regex.

    ``*`` matches one or more non-slash characters; all other characters are
    escaped literally. Anchored so ``PROJECTS/*/LONGRUNNER.md`` does not match
    ``PROJECTS/a/b/LONGRUNNER.md`` or a prefix substring.
    """
    parts = re.split(r"(\*)", pattern)
    rx = "".join(r"[^/]+" if p == "*" else re.escape(p) for p in parts)
    return re.compile("^" + rx + "$")


def _path_matches(schema_path: str, query_path: str) -> bool:
    """Match a schema endpoint string against a concrete query path.

    Both sides are note-stripped and normalized. If the schema side contains
    a ``*``, it is treated as a single-segment glob.
    """
    s = _norm(schema_path)
    q = _norm(query_path)
    if "*" not in s:
        return s == q
    return bool(_glob_to_regex(s).match(q))


def route_for(model: SchemaModel, rel_path: str) -> Optional[RouteRule]:
    """Return the R3 RouteRule for a relative path, or ``None`` if unknown.

    Note-stripping and glob expansion are applied to the schema side, so a
    concrete path like ``PROJECTS/example-research/LONGRUNNER.md`` will find
    the R3 row whose file is ``PROJECTS/*/LONGRUNNER.md``.
    """
    if not rel_path:
        return None
    for r in model.routes:
        if _path_matches(r.file, rel_path):
            return r
    return None


def is_protected(model: SchemaModel, rel_path: str) -> bool:
    """CL5 + R3 tier=PROTECTED check. Either source rejects writes."""
    norm = _norm(rel_path)
    if model.is_protected(norm):
        return True
    r = route_for(model, norm)
    if r is not None and r.tier.upper() == "PROTECTED":
        return True
    return False


def route_check(model: SchemaModel, rel_path: str, bundle: str) -> GateResult:
    """Confirm a (file, bundle) pair agrees with R3.

    ``OK`` if the file's R3 row declares the given bundle *or* R3 has no
    bundle column for that file (write-by-tier-only).
    ``R3_PROTECTED`` if the file is in CL5 or the route says PROTECTED.
    ``R3_ROUTE_UNKNOWN`` if the file has no row in R3.
    ``R3_BUNDLE_MISMATCH`` if the R3 bundle column doesn't match.
    """
    if is_protected(model, rel_path):
        return GateResult(False, "R3_PROTECTED", rel_path)

    r = route_for(model, rel_path)
    if r is None:
        # Not in R3 -> unknown target. Safer to reject than to let arbitrary
        # writes sneak through a typo. Bundles should declare their targets.
        return GateResult(False, "R3_ROUTE_UNKNOWN", rel_path)

    declared = (r.bundle or "").strip()
    if declared and bundle and declared != bundle:
        return GateResult(
            False, "R3_BUNDLE_MISMATCH",
            f"{rel_path} r3_bundle={declared} caller_bundle={bundle}",
        )
    return GateResult(True, "OK")


# ---------------------------------------------------------------------------
# R4 — cascade reads
# ---------------------------------------------------------------------------

def cascade_for(model: SchemaModel, rel_path: str) -> Tuple[Edge, ...]:
    """Return every R4 edge where ``rel_path`` is the SOURCE.

    Caller (a mutator) uses these to emit CASCADE_CHECK rows and to decide
    whether downstream rendered views need regeneration (e.g.
    ``longrunner_update`` on LONGRUNNER.md cascades to re-rendering).

    The schema side of the compare is note-stripped and glob-expanded, so a
    concrete slug path like ``PROJECTS/example/LONGRUNNER.md`` resolves to
    edges whose source is ``PROJECTS/*/LONGRUNNER.md``.
    """
    out: List[Edge] = []
    for e in model.edges:
        if _path_matches(e.source, rel_path):
            out.append(e)
    return tuple(out)


def cascade_upstream(model: SchemaModel, rel_path: str) -> Tuple[Edge, ...]:
    """Return every R4 edge where ``rel_path`` is the TARGET.

    Used by manager-side reads to surface the files that *cause* a given
    file's state (audit review direction). Note-stripping and glob expansion
    on the schema side mirror ``cascade_for``.
    """
    out: List[Edge] = []
    for e in model.edges:
        if _path_matches(e.target, rel_path):
            out.append(e)
    return tuple(out)


# ---------------------------------------------------------------------------
# Tooling policy (Tier C support — consumed by phase machines)
# ---------------------------------------------------------------------------

def allowed_tool(allowed: Iterable[str], tool: str) -> GateResult:
    """Check whether ``tool`` is in the current phase's allow-list.

    The allow-list is carried on a PhaseMachine (Tier C). The gate lives here
    so the bundle executor can consult it without importing the phase module.
    """
    allowed_set = {t.strip().lower() for t in allowed if t and t.strip()}
    t = tool.strip().lower()
    if not allowed_set:
        # Empty allow-list means "no restriction declared" — not a violation.
        return GateResult(True, "OK")
    if t in allowed_set:
        return GateResult(True, "OK")
    return GateResult(False, "C_TOOL_DENIED", f"tool={tool}")


# ---------------------------------------------------------------------------
# Convenience: render a batch of results as audit lines
# ---------------------------------------------------------------------------

def summarise(results: Iterable[GateResult]) -> Tuple[bool, List[str]]:
    """Fold a sequence of GateResults into (all_ok, machine_lines)."""
    lines: List[str] = []
    all_ok = True
    for r in results:
        if not r.ok:
            all_ok = False
        lines.append(r.as_line())
    return all_ok, lines


__all__ = [
    "GateResult",
    "allowed_tool",
    "cascade_for",
    "cascade_upstream",
    "find_field",
    "is_protected",
    "route_check",
    "route_for",
    "summarise",
    "validate_field",
]
