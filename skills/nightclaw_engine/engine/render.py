"""nightclaw_engine.engine.render — deterministic markdown renderer for REGISTRY.md.

Reads the Tier-A machine schema (``orchestration-os/schema/*.yaml``) and
emits a clean, deterministic Markdown document representing sections R1-R6
plus CL5 PROTECTED-PATHS. The output is byte-stable for a given input: no
timestamps in the body, no map-order variance (we iterate YAML-declared
order directly).

Merge 1 scope:
  * Produces a standalone ``REGISTRY.generated.md`` alongside the canonical
    ``REGISTRY.md`` so the {OWNER} can review the diff before any rewrite.
  * Emits a header signature that ``schema-lint`` uses to detect drift.

Merge 2 scope (not done here):
  * Replace the rendered sections of REGISTRY.md in place, keeping doctrine
    sections (R7 / CL1-CL4 / CL6) hand-authored.
  * Hard-fail on lint mismatch rather than report.
"""
from __future__ import annotations

from typing import Iterable, List

from ..schema.loader import (
    BundleSpec,
    Edge,
    FieldSpec,
    ObjectSpec,
    RouteRule,
    SCRRule,
    SchemaModel,
)

RENDER_HEADER_MARK = "<!-- nightclaw:render "
RENDER_FOOTER_MARK = "<!-- /nightclaw:render -->"


def _line(lines: List[str], text: str = "") -> None:
    lines.append(text)


def _render_r1(model: SchemaModel) -> List[str]:
    out: List[str] = []
    _line(out, "## R1 — OBJECT REGISTRY")
    _line(out, "# Every object type: what it is, where it lives, who reads it, who writes it.")
    _line(out, "# Format: OBJ | FILE | PK | READER | WRITER | APPEND-ONLY")
    _line(out)
    for o in model.objects:
        _line(out,
              f"{o.obj:15s} | {o.file:43s} | {o.pk:17s} | "
              f"{o.reader} | {o.writer} | {'YES' if o.append_only else 'NO'}")
    return out


def _render_r2(model: SchemaModel) -> List[str]:
    out: List[str] = []
    _line(out, "## R2 — FIELD CONTRACTS")
    _line(out, "# Per-object field definitions. Format: OBJ | FIELD | TYPE | REQ | ENUM/FORMAT | FK/CONSTRAINT")
    _line(out, "# REQ: Y=required N=nullable. Enum values UPPERCASE for attention efficiency.")
    _line(out)
    current_obj = None
    for f in model.fields:
        if f.obj != current_obj and current_obj is not None:
            _line(out)  # blank line between object groups
        current_obj = f.obj
        req = f.req.upper() if f.req else ""
        _line(out,
              f"{f.obj:12s} | {f.field:35s} | {f.type:9s} | {req:1s} | "
              f"{f.constraint} | {f.fk or '-'}")
    return out


def _render_r3(model: SchemaModel) -> List[str]:
    out: List[str] = []
    _line(out, "## R3 — WRITE ROUTING")
    _line(out, "# File → tier → bundle. The complete routing table for all write decisions.")
    _line(out, "# Format: FILE-PATTERN | TIER | BUNDLE | NOTE")
    _line(out, "# TIER: APPEND=write immediately | STANDARD=scope+gate | PROTECTED={OWNER}-auth | "
               "MANIFEST-VERIFY=manager-timestamp-only")
    _line(out)
    for r in model.routes:
        _line(out, f"{r.file:45s} | {r.tier:16s} | {r.bundle:28s} | {r.note}")
    return out


def _render_r4(model: SchemaModel) -> List[str]:
    out: List[str] = []
    _line(out, "## R4 — DEPENDENCY EDGES")
    _line(out, "# Typed edges for impact traversal. Format: SOURCE → TYPE → TARGET")
    _line(out, "# Types: READS|WRITES|VALIDATES|TRIGGERS|REFERENCES|AUTHORIZES")
    _line(out, "# Read forward (grep SOURCE) to find what a change affects.")
    _line(out, "# Read reverse (grep TARGET) to find what depends on a file.")
    _line(out)
    for e in model.edges:
        _line(out, f"{e.source:55s} → {e.type:11s} → {e.target}")
    return out


def _render_bundle(b: BundleSpec) -> List[str]:
    out: List[str] = []
    _line(out, f"BUNDLE:{b.name}")
    if b.inline:
        _line(out, "  # STAYS INLINE — requires LLM judgment for scope/boundary evaluation.")
        _line(out, "  # Not handled by bundle-exec. The LLM reads OPS-PREAPPROVAL.md and evaluates.")
    if b.trigger:
        _line(out, f"  TRIGGER: {b.trigger}")
    if b.args:
        _line(out, f"  ARGS: {', '.join(b.args)}")
    # Bundle-specific extras (pa_invoke has VALIDATES FIRST, IF VALID, IF INVALID)
    if "validates_first" in b.extras:
        _line(out, f"  VALIDATES FIRST: {b.extras['validates_first']}")
    if "if_valid" in b.extras:
        _line(out, "  IF VALID:")
        for entry in (b.extras["if_valid"].get("writes", []) if isinstance(b.extras["if_valid"], dict) else []):
            _line(out, f"    WRITES: {entry}")
    if "if_invalid" in b.extras:
        _line(out, "  IF INVALID: " + "; ".join(b.extras["if_invalid"]))
    if b.validates:
        _line(out, "  VALIDATES:")
        for v in b.validates:
            _line(out, f"    - {v}")
    if b.writes:
        _line(out, "  WRITES:")
        for target, fields in b.writes.items():
            _line(out, f"    {target}:")
            if isinstance(fields, dict):
                for k, v in fields.items():
                    _line(out, f"      {k} = {v}")
            else:
                _line(out, f"      {fields}")
    if b.append:
        _line(out, "  APPEND:")
        for k, v in b.append.items():
            _line(out, f"    {k}: {v}")
    if b.notify:
        _line(out, "  NOTIFY:")
        for k, v in b.notify.items():
            _line(out, f"    {k}: {v}")
    if "authority" in b.extras:
        _line(out, f"  AUTHORITY: {b.extras['authority']}")
    if b.returns:
        _line(out, f"  RETURNS: {b.returns}")
    return out


def _render_r5(model: SchemaModel) -> List[str]:
    out: List[str] = []
    _line(out, "## R5 — BUNDLE SPECIFICATIONS")
    _line(out, "# Named multi-file write operations. The executor (bundle-exec) reads these at runtime.")
    _line(out, "# Expression types (exactly four): LITERAL (bare), ARG ({name}), COMPUTED ({NOW}/{TODAY}/{NOW+field}), NULL (~).")
    _line(out, "# No TEMPLATE interpolation. LLM constructs full strings and passes as ARGs.")
    _line(out, "# CHANGE-LOG entries are emitted automatically by the executor for every MUTATE where old ≠ new.")
    _line(out, "# Format: BUNDLE:[name] → TRIGGER, ARGS, VALIDATES, WRITES (MUTATE), APPEND, NOTIFY, RETURNS.")
    _line(out)
    for i, b in enumerate(model.bundles):
        if i > 0:
            _line(out)
        out.extend(_render_bundle(b))
    return out


def _render_r6(model: SchemaModel) -> List[str]:
    out: List[str] = []
    _line(out, "## R6 — SELF-CONSISTENCY RULES (index)")
    _line(out, "# Rule IDs, severities and predicate names. Narrative bodies remain in REGISTRY.md doctrine.")
    _line(out, "# Format: ID | SEVERITY | PREDICATE | TITLE")
    _line(out)
    for r in model.scr_rules:
        _line(out, f"{r.id:6s} | {r.severity:8s} | {r.predicate:42s} | {r.title}")
    return out


def _render_cl5(model: SchemaModel) -> List[str]:
    out: List[str] = []
    _line(out, "## CL5 — PROTECTED PATHS (index)")
    _line(out, "# Files requiring {OWNER} authorization. Enforced by the route gate and audited by manager T8.")
    _line(out)
    for p in model.protected_paths:
        _line(out, f"FILE:{p}")
    return out


def _render_sections(model: SchemaModel) -> List[str]:
    out: List[str] = []
    for i, section in enumerate((_render_r1, _render_r2, _render_r3,
                                  _render_r4, _render_r5, _render_r6,
                                  _render_cl5)):
        if i > 0:
            _line(out)
            _line(out, "---")
            _line(out)
        out.extend(section(model))
    return out


def render_markdown(model: SchemaModel) -> str:
    """Return a Markdown document containing the rendered R1-R6 + CL5 sections.

    The output starts with a deterministic render header carrying the schema
    fingerprint so drift can be detected without re-reading the source YAML.
    """
    lines: List[str] = []
    _line(lines, "# REGISTRY.md — Rendered Sections (R1-R6 + CL5)")
    _line(lines, RENDER_HEADER_MARK + f"schema_fingerprint={model.fingerprint} -->")
    _line(lines, "<!-- Generated by nightclaw_engine.engine.render. DO NOT HAND-EDIT. -->")
    _line(lines, "<!-- Source of truth: orchestration-os/schema/*.yaml -->")
    _line(lines, "<!-- Regenerate with: python3 scripts/nightclaw-ops.py schema-render -->")
    _line(lines)
    lines.extend(_render_sections(model))
    _line(lines)
    _line(lines, RENDER_FOOTER_MARK)
    return "\n".join(lines) + "\n"


def iter_rendered_section_titles(model: SchemaModel) -> Iterable[str]:
    """Yield the top-level Markdown section titles this renderer produces.

    Useful for ``schema-lint`` to verify each is present in REGISTRY.md.
    """
    yield "## R1 — OBJECT REGISTRY"
    yield "## R2 — FIELD CONTRACTS"
    yield "## R3 — WRITE ROUTING"
    yield "## R4 — DEPENDENCY EDGES"
    yield "## R5 — BUNDLE SPECIFICATIONS"
    yield "## R6 — SELF-CONSISTENCY RULES (index)"
    yield "## CL5 — PROTECTED PATHS (index)"


__all__ = ["render_markdown", "iter_rendered_section_titles",
           "RENDER_HEADER_MARK", "RENDER_FOOTER_MARK"]
