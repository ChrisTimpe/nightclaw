"""nightclaw_engine.protocol.integrity — SCR predicate registry.

R6 Self-Consistency Rules are now declared in ``orchestration-os/schema/scr_rules.yaml``
by id, severity, predicate-name, and title. The predicate names are resolved
through this module's registry — each predicate is a pure function with the
signature::

    predicate(model: SchemaModel, root: Path) -> list[PredicateResult]

Predicates read whatever workspace state they need (REGISTRY.md,
SESSION-REGISTRY.md, LOCK.md, etc.) and return zero or more typed rows. The
driver in :func:`run_scr_verify` prints them in the same machine format
``cmd_scr_verify`` has always emitted, so prompt behavior is unchanged:
``SCR-NN:PASS|FAIL|SKIP|INFO <key=value>``.

SCR-09 (``prompt_bundle_args_match_r5``) was orphaned in Merge 1 — it is
wired in for real here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..schema.loader import SchemaModel


# ---------------------------------------------------------------------------
# Predicate result shape
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PredicateResult:
    """One output row for an SCR predicate.

    ``status`` is one of: PASS, FAIL, SKIP, INFO.
    ``detail`` is an optional short detail string appended after the status.
    ``extra_lines`` are optional indented continuation lines (used by
    reference-edge dumps that SCR-07 has always emitted).
    """
    status: str
    detail: str = ""
    extra_lines: Tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


_Predicate = Callable[[SchemaModel, Path], List[PredicateResult]]


# ---------------------------------------------------------------------------
# Helpers shared by predicates (read workspace state, parse sections)
# ---------------------------------------------------------------------------

def _read(root: Path, rel: str) -> Optional[str]:
    fp = root / rel
    if not fp.exists():
        return None
    try:
        return fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# Pass 8 note: the former ``_registry_sections()`` helper — which parsed
# rendered prose in REGISTRY.md — has been removed. SCR-01 and SCR-06 now
# query the typed ``SchemaModel`` directly (routes, bundles, edges). This is
# enforced as a CI invariant by ``tests/core/test_thesis_alignment.py``.


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

def pred_r3_bundles_exist_in_r5(model: SchemaModel, root: Path) -> List[PredicateResult]:
    """SCR-01: every BUNDLE: reference on an R3 route row resolves to an R5
    bundle definition.

    Derivation path (Pass 8 thesis alignment): read ``model.routes[].bundle``
    directly rather than regex over the rendered R3 section of REGISTRY.md.
    Byte-equality (Pass 7) already guarantees the render of R3 matches
    ``model.routes``, so querying the typed model is the honest form of the
    invariant. Output shape preserved: ``PASS count=<n>``.
    """
    r3_bundles: set = set()
    for r in model.routes:
        if r.bundle:
            for m in re.finditer(r"BUNDLE:(\w+)", r.bundle):
                r3_bundles.add(m.group(1))
    r5_defs = {b.name for b in model.bundles}
    missing = r3_bundles - r5_defs
    if missing:
        return [PredicateResult("FAIL", f"missing_from_R5={sorted(missing)}")]
    return [PredicateResult("PASS", f"count={len(r3_bundles)}")]


# Matches any OBJ:NAME token (uppercase letters, digits, underscore, hyphen).
# Stops at the first character that can't be part of the identifier so that
# trailing scope qualifiers like "OBJ:RUN (when locked)" extract cleanly.
_OBJ_TOKEN_RE = re.compile(r"OBJ:[A-Z][A-Z0-9_\-]*")


def pred_r2_fks_exist_in_r1(model: SchemaModel, root: Path) -> List[PredicateResult]:
    """SCR-02: every FK reference in R2 resolves to an OBJ: row in R1.

    R2 rows may qualify FKs with a scope note e.g. ``OBJ:RUN (when locked)``.
    The note is semantic metadata — the referenced object is still ``OBJ:RUN``.
    Extract OBJ:NAME tokens with a strict regex so scope qualifiers do not
    leak into the FK set and cause spurious SCR-02 failures.
    """
    r1_objs = {f"OBJ:{o.obj}" if not o.obj.startswith("OBJ:") else o.obj
               for o in model.objects}
    r2_fks: set = set()
    for f in model.fields:
        # Look for FK→OBJ:NAME in the constraint column and the fk column.
        for text in ((f.fk or ""), (f.constraint or "")):
            for m in _OBJ_TOKEN_RE.finditer(text):
                r2_fks.add(m.group(0))
    missing = r2_fks - r1_objs
    if missing:
        return [PredicateResult("FAIL", f"missing_from_R1={sorted(missing)}")]
    return [PredicateResult("PASS", f"count={len(r2_fks)}")]


# Strip trailing scope qualifier like "FILE.md(structural)" or "FILE.md(append)"
# from an R3 file column. The parenthesised suffix is a scope qualifier, not a
# different file, so it must not leak into set-comparisons with R4 edges.
_ROUTE_SUFFIX_RE = re.compile(r"\([^)]+\)\s*$")


def _route_file_canonical(file: str) -> str:
    return _ROUTE_SUFFIX_RE.sub("", file).strip()


def pred_protected_has_validates_edge(model: SchemaModel, root: Path) -> List[PredicateResult]:
    """SCR-03: every R3-PROTECTED file is the target of at least one VALIDATES edge.

    R3 rows may scope a single file into multiple entries via parenthesised
    qualifiers e.g. ``orchestration-os/REGISTRY.md(structural)``. The VALIDATES
    edge targets the bare path (``orchestration-os/REGISTRY.md``). Canonicalise
    both sides to the bare path before set-comparison so scope qualifiers do
    not cause spurious SCR-03 failures.
    """
    protected = {_route_file_canonical(r.file)
                 for r in model.routes if r.tier.upper() == "PROTECTED"}
    validates = {e.target for e in model.edges if e.type.upper() == "VALIDATES"}
    missing = protected - validates
    if missing:
        return [PredicateResult("FAIL", f"missing_validates_edge={sorted(missing)}")]
    return [PredicateResult("PASS", f"count={len(protected)}")]


def pred_change_log_exists(model: SchemaModel, root: Path) -> List[PredicateResult]:
    if (root / "audit/CHANGE-LOG.md").exists():
        return [PredicateResult("PASS")]
    return [PredicateResult("FAIL", "audit/CHANGE-LOG.md_not_found")]


# Matches a RUN-ID only when it appears as the first pipe-delimited column
# of a SESSION-REGISTRY.md table row (optionally preceded by whitespace or
# a leading pipe). This prevents false-positive duplicates when a later
# session's summary prose mentions an earlier run_id (e.g. "duplicate
# RUN-20260422-001 in SESSION-REGISTRY").
_RUN_ID_RE = re.compile(r"^\s*\|?\s*(RUN-\d{8}-\d{3})\s*\|", re.MULTILINE)


def pred_session_registry_unique_runs(model: SchemaModel, root: Path) -> List[PredicateResult]:
    content = _read(root, "audit/SESSION-REGISTRY.md")
    if content is None:
        return [PredicateResult("SKIP", "file_not_found")]
    run_ids = _RUN_ID_RE.findall(content)
    dupes = sorted({rid for rid in run_ids if run_ids.count(rid) > 1})
    if dupes:
        return [PredicateResult("FAIL", f"duplicate_run_ids={dupes}")]
    return [PredicateResult("PASS", f"unique_count={len(set(run_ids))}")]


def pred_r4_bundles_exist_in_r5(model: SchemaModel, root: Path) -> List[PredicateResult]:
    """SCR-06: every BUNDLE: reference on an R4 dependency edge row resolves
    to an R5 bundle definition.

    Derivation path (Pass 8 thesis alignment): scan ``model.edges`` fields for
    ``BUNDLE:`` tokens directly rather than regex over the rendered R4 section.
    Byte-equality (Pass 7) guarantees the set of BUNDLE references in the
    render equals the set in the typed model; querying the typed model is the
    honest form of the invariant. Output shape preserved: ``PASS count=<n>``.
    """
    r4_bundles: set = set()
    for e in model.edges:
        for field_val in (e.source, e.target, e.type):
            if field_val and "BUNDLE:" in field_val:
                for m in re.finditer(r"BUNDLE:(\w+)", field_val):
                    r4_bundles.add(m.group(1))
    r5_defs = {b.name for b in model.bundles}
    missing = r4_bundles - r5_defs
    if missing:
        return [PredicateResult("FAIL", f"missing_from_R5={sorted(missing)}")]
    return [PredicateResult("PASS", f"count={len(r4_bundles)}")]


def pred_reference_edges(model: SchemaModel, root: Path) -> List[PredicateResult]:
    """SCR-07: structural — enumerate REFERENCES edges for manual review.

    Preserves the historical ``INFO`` emission plus indented continuation
    lines that the prompts have been reading verbatim since Merge 1.
    """
    refs = [e for e in model.edges if e.type.upper() == "REFERENCES"]
    extras = tuple(f"  REF: {e.source} \u2192 {e.target}" for e in refs)
    return [PredicateResult("INFO", f"reference_edges={len(refs)}", extras)]


def pred_lock_structural(model: SchemaModel, root: Path) -> List[PredicateResult]:
    content = _read(root, "LOCK.md")
    if content is None:
        return [PredicateResult("SKIP", "LOCK.md_not_found")]
    has_status = "status:" in content
    has_expires = "expires_at:" in content
    if has_status and has_expires:
        return [PredicateResult("PASS")]
    return [PredicateResult("FAIL", f"status={has_status} expires_at={has_expires}")]


# SCR-09 invocation pattern. Requires the full CLI shape so prose references
# to ``bundle-exec <name>`` (e.g. ``After any bundle-exec route_block call``)
# are not mistaken for actual invocations. The trailing group captures args up
# to end-of-line / backtick / blank line.
_BUNDLE_INVOKE_RE = re.compile(
    r"python3\s+scripts/nightclaw-ops\.py\s+bundle-exec\s+([a-z_]+)([^\n`]*)"
)

# Matches ``--file=<path>`` in an invocation tail.
_FILE_ARG_RE = re.compile(r"--file=(\S+)")

# Match the key set in a ``containing {...}`` hint that prompts use to declare
# the JSON body of a --file payload. Example:
#   Write file: /tmp/foo.json containing {"run_id":"...", "session_entry":"..."}
_CONTAINING_RE = re.compile(r"containing\s*\{([^}]*)\}")
_JSON_KEY_RE = re.compile(r'"([a-z_][a-z0-9_]*)"\s*:')


def _declared_file_keys(text: str, invoke_start: int, file_path: str) -> set:
    """Return the set of JSON keys declared for a ``--file=<path>`` payload.

    Looks for a ``containing {...}`` hint in the 400 characters of prompt text
    immediately preceding the bundle-exec invocation. Prompts always declare
    the JSON payload keys inline right before the Execute: line. Returns an
    empty set if no hint is found — caller treats that as "no keys supplied",
    which will correctly fail the check and surface the gap.

    The ``file_path`` arg is informational only: the path is a template like
    ``/tmp/session_close_[run_id].json`` that cannot be resolved at lint time.
    """
    window_start = max(0, invoke_start - 400)
    preceding = text[window_start:invoke_start]
    # Take the last ``containing {...}`` before the invocation — closest wins.
    matches = list(_CONTAINING_RE.finditer(preceding))
    if not matches:
        return set()
    body = matches[-1].group(1)
    return set(_JSON_KEY_RE.findall(body))


def pred_prompt_bundle_args_match_r5(model: SchemaModel, root: Path) -> List[PredicateResult]:
    """SCR-09: every ``Execute: python3 scripts/nightclaw-ops.py bundle-exec <name>``
    call in the worker / manager / startup prompts must supply every ARG
    declared in R5 for that bundle.

    Args may be supplied two ways:
      * Inline: ``bundle-exec name key=val key=val``.
      * Via ``--file=<path>``: a JSON payload whose keys are declared inline
        on the preceding ``Write file: <path> containing {...}`` line.

    Missing args are a FAIL. Extra args are PASS (bundles may legitimately
    accept pass-through values the current prompt uses).

    Pre-Pass-7 this predicate used a loose ``bundle-exec <name>`` regex that
    matched prose references (``After any bundle-exec route_block call``) and
    did not understand ``--file=<json>`` invocations, producing three stable
    false-positive FAILs against the real prompts. Pass 7 fixes both.
    """
    prompt_files = (
        "orchestration-os/CRON-WORKER-PROMPT.md",
        "orchestration-os/CRON-MANAGER-PROMPT.md",
        "orchestration-os/START-HERE.md",
    )
    bundles_by_name = {b.name: b for b in model.bundles}

    failures: List[str] = []
    checked = 0
    for rel in sorted(set(prompt_files)):
        text = _read(root, rel)
        if text is None:
            continue
        for m in _BUNDLE_INVOKE_RE.finditer(text):
            bname = m.group(1)
            tail = m.group(2) or ""
            spec = bundles_by_name.get(bname)
            if spec is None:
                continue
            checked += 1
            provided = set(re.findall(r"([a-z_][a-z0-9_]*)=", tail))
            # If the invocation uses ``--file=<path>``, resolve declared keys
            # from the preceding ``containing {...}`` hint.
            file_m = _FILE_ARG_RE.search(tail)
            if file_m:
                provided |= _declared_file_keys(text, m.start(), file_m.group(1))
                provided.discard("file")  # pseudo-arg name from --file= itself
            required = set(spec.args)
            missing = required - provided
            if missing:
                failures.append(
                    f"{rel}:{bname}:missing={sorted(missing)}"
                )
    if failures:
        return [PredicateResult("FAIL", f"checked={checked} gaps={failures[:5]}"
                                         + (" +more" if len(failures) > 5 else ""))]
    return [PredicateResult("PASS", f"checked={checked}")]


# ---------------------------------------------------------------------------
# Registry (predicate_name -> callable)
# ---------------------------------------------------------------------------

def pred_r3_code_rows_exist_on_disk(model: SchemaModel, root: Path) -> List[PredicateResult]:
    """SCR-11 / INV-13: every R3 row at tier CODE names a file that actually
    exists on disk.

    SCR-10 (``code_files_have_r3_rows``) is a set-diff between R3 CODE rows
    and a hard-coded package glob; it catches drift in both directions but
    its scope is anchored to the four known packages. This predicate is the
    straight reading of the invariant: resolve every R3 CODE row path under
    ``root`` and verify the file is present. That protects against rename /
    delete drift for any CODE row regardless of whether its package is in
    SCR-10's scope list. Output shape preserved with other PASS/FAIL rules:
    ``PASS count=<n>`` on success, a FAIL row per missing file.
    """
    code_routes = [r for r in model.routes if r.tier.upper() == "CODE"]
    if not code_routes:
        return [PredicateResult("SKIP", "no_CODE_rows")]

    missing: List[str] = []
    present = 0
    for route in code_routes:
        # Canonicalise the same way SCR-03 does so a future scope-qualified
        # CODE row (``foo.py(structural)``) resolves to the bare path.
        rel = _route_file_canonical(route.file)
        if (root / rel).exists():
            present += 1
        else:
            missing.append(rel)

    if missing:
        return [PredicateResult("FAIL", f"missing_on_disk={sorted(missing)}")]
    return [PredicateResult("PASS", f"count={present}")]


def pred_code_files_have_r3_rows(model: SchemaModel, root: Path) -> List[PredicateResult]:
    """SCR-10: Every .py file under the four code packages and every .html
    file under apps/monitor/ must have a CODE-tier row in R3.

    Closes the governance gap documented as F2 and F3 in the alignment plan:
    previously the four Python packages (nightclaw_engine, nightclaw_bridge,
    nightclaw_monitor, nightclaw_ops) and the three monitor UIs had zero
    presence in R3, so ``registry-route`` returned UNKNOWN for all of them.
    """
    packages = (
        "nightclaw_engine",
        "nightclaw_bridge",
        "nightclaw_monitor",
        "nightclaw_ops",
    )
    # Collect expected files from disk.
    expected: set = set()
    for pkg in packages:
        pkg_dir = root / pkg
        if not pkg_dir.is_dir():
            continue
        for py in sorted(pkg_dir.rglob("*.py")):
            expected.add(py.relative_to(root).as_posix())
    ui_dir = root / "apps" / "monitor"
    if ui_dir.is_dir():
        for html in sorted(ui_dir.glob("*.html")):
            expected.add(html.relative_to(root).as_posix())

    # Collect files declared in R3 at CODE tier.
    declared_code: set = {
        r.file for r in model.routes if r.tier.upper() == "CODE"
    }

    missing_rows = expected - declared_code
    orphan_rows = declared_code - expected

    results: List[PredicateResult] = []
    if missing_rows:
        results.append(PredicateResult(
            "FAIL",
            f"missing_r3_rows={sorted(missing_rows)}"
        ))
    if orphan_rows:
        results.append(PredicateResult(
            "FAIL",
            f"r3_rows_without_files={sorted(orphan_rows)}"
        ))
    if not results:
        results.append(PredicateResult(
            "PASS",
            f"code_files={len(expected)}"
        ))
    return results


PREDICATE_REGISTRY: Dict[str, _Predicate] = {
    # Names here are the canonical ids declared in
    # orchestration-os/schema/scr_rules.yaml. Aliases below map legacy /
    # short-form names that appeared in design notes to the same callable,
    # so either can be used.
    "r3_bundles_exist_in_r5":                 pred_r3_bundles_exist_in_r5,
    "r2_foreign_keys_resolve_to_r1":          pred_r2_fks_exist_in_r1,
    "r2_fks_exist_in_r1":                     pred_r2_fks_exist_in_r1,
    "r3_protected_files_are_in_manifest":     pred_protected_has_validates_edge,
    "protected_has_validates_edge":           pred_protected_has_validates_edge,
    "changelog_file_exists":                  pred_change_log_exists,
    "change_log_exists":                      pred_change_log_exists,
    "session_registry_run_ids_unique":        pred_session_registry_unique_runs,
    "session_registry_unique_runs":           pred_session_registry_unique_runs,
    "r4_bundle_refs_resolve_to_r5":           pred_r4_bundles_exist_in_r5,
    "r4_bundles_exist_in_r5":                 pred_r4_bundles_exist_in_r5,
    "references_cross_doc_consistency":       pred_reference_edges,
    "reference_edges":                        pred_reference_edges,
    "session_close_releases_lock":            pred_lock_structural,
    "lock_structural":                        pred_lock_structural,
    "prompt_bundle_args_match_r5":            pred_prompt_bundle_args_match_r5,
    "code_files_have_r3_rows":                pred_code_files_have_r3_rows,
    "r3_code_rows_exist_on_disk":             pred_r3_code_rows_exist_on_disk,
}


# ---------------------------------------------------------------------------
# Driver — replaces the body of the old cmd_scr_verify
# ---------------------------------------------------------------------------

@dataclass
class ScrReport:
    passed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)


def run_scr_verify(model: SchemaModel, root: Path) -> ScrReport:
    """Run every SCR declared in scr_rules.yaml using the predicate registry.

    Output semantics match the legacy ``cmd_scr_verify`` so prompts still
    parse results the same way:
        SCR-NN:STATUS detail
        optional ``  `` indented continuation lines for INFO dumps
        CL5:STATUS detail
        RESULT:PASS | RESULT:FAIL rules=[...]
    """
    report = ScrReport()

    # Iterate SCR rules in declared order (SCR-01 first, SCR-09 last), to
    # match the legacy emission order that downstream prompts still parse.
    for rule in sorted(model.scr_rules, key=lambda r: r.id):
        pred = PREDICATE_REGISTRY.get(rule.predicate)
        if pred is None:
            report.failed.append(rule.id)
            report.lines.append(f"{rule.id}:FAIL predicate_unknown={rule.predicate}")
            continue
        try:
            outs = pred(model, root)
        except Exception as exc:  # predicate-local failure, still surface
            report.failed.append(rule.id)
            report.lines.append(f"{rule.id}:FAIL predicate_error={exc}")
            continue
        for r in outs:
            tail = f" {r.detail}" if r.detail else ""
            report.lines.append(f"{rule.id}:{r.status}{tail}")
            for extra in r.extra_lines:
                report.lines.append(extra)
            if r.status == "FAIL":
                report.failed.append(rule.id)
            elif r.status == "PASS":
                report.passed.append(rule.id)

    # CL5 cross-check — preserved from legacy, emitted after SCR rules.
    # Canonicalise R3 file paths (strip scope qualifiers like ``(structural)``)
    # before comparing to the bare paths declared in CL5 protected_paths.
    cl5_paths = set(model.protected_paths)
    protected_in_r3 = {_route_file_canonical(r.file)
                       for r in model.routes if r.tier.upper() == "PROTECTED"}
    cl5_missing = protected_in_r3 - cl5_paths
    if cl5_missing:
        report.failed.append("CL5")
        report.lines.append(f"CL5:FAIL missing_from_protected_paths={sorted(cl5_missing)}")
    else:
        report.lines.append(f"CL5:PASS count={len(cl5_paths)}")

    # Summary — preserves legacy trailing RESULT line.
    if report.failed:
        report.lines.append(f"RESULT:FAIL rules={report.failed}")
    else:
        report.lines.append("RESULT:PASS")
    return report


__all__ = [
    "PREDICATE_REGISTRY",
    "PredicateResult",
    "ScrReport",
    "run_scr_verify",
]
