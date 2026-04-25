"""nightclaw_engine.commands.bootstrap — LLM bootstrap projection (Pass 10).

Purpose
-------
A new LLM session (or a new engineer) arriving at this repo must be able to
reach a working mental model quickly without reading every doctrine file.
The ``bootstrap`` command composes a curated view of the repo by resolving
the sections declared in one of the tracks in
``internal_enhancement/LLM-BOOTSTRAP.yaml``.

Architecture
------------
* **Declarative tracks**: each task (general / add_bundle / edit_schema /
  fix_bug / review_pr / add_predicate) is a list of sections, each naming a
  resolver + args + a relative budget share. The manifest is authoritative;
  this module ships the resolver implementations.

* **Resolver registry**: the :data:`RESOLVERS` dict maps resolver names to
  callables of the form ``(ctx, args) -> (heading, body)``. A CI invariant
  keeps the manifest's ``resolvers:`` whitelist in lockstep with this dict.

* **Budget**: tokens are approximated as ``char_count / 4`` (tiktoken is
  not installed in the runtime). Each section's share of the budget is
  its ``budget_share`` over the track's sum-of-shares.

* **Provenance**: every resolution records the source paths read + byte
  count. The output footer lists every source consumed so an operator can
  audit what went into the bootstrap.

CLI
---
``python3 scripts/nightclaw-ops.py bootstrap [OPTS]``

Options (hand-parsed — repo convention is no argparse)::

    --track=<name>     Track to resolve. Default: "general".
    --budget=<tokens>  Token ceiling (approx). Default: manifest
                       ``defaults.budget_tokens``.
    --format=md|json   Output format. Default: manifest
                       ``defaults.format``.
    --list-tracks      Print available track names + one-line summaries.
    --manifest=<path>  Override manifest path (test hook).

Six non-negotiables honored
---------------------------
1. No existing tool output strings change (new command).
2. No cron prompts edited.
3. schema-sync stays NOOP (LLM-BOOTSTRAP.yaml is outside schema/).
4. No bundle protocol change.
5. No state-file format change.
6. SCR-09 stays tight.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import _shared


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_REL = "internal_enhancement/LLM-BOOTSTRAP.yaml"

# Token approximation: tiktoken is not installed. 1 token ≈ 4 chars is the
# widely-published tokenizer heuristic. The
# provenance footer reports uncut char counts so the approximation is
# transparent, not hidden.
CHARS_PER_TOKEN = 4


# ---------------------------------------------------------------------------
# Context + dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BootstrapContext:
    """Shared state for resolver calls. A single context is constructed per
    bootstrap invocation and threaded through every resolver."""
    root: Path
    model: Any = None  # SchemaModel | None — lazy-loaded by _load_model
    sources: List[Tuple[str, int]] = field(default_factory=list)
    # ``sources`` accumulates (relative_path, uncut_char_count) tuples so the
    # provenance footer can list every byte consumed.

    def record_source(self, rel: str, char_count: int) -> None:
        self.sources.append((rel, char_count))


@dataclass
class ResolvedSection:
    """A section after its resolver has run, before budget apportionment."""
    resolver: str
    heading: str
    body: str
    budget_share: int


# ---------------------------------------------------------------------------
# Manifest loader (minimal — only the shape the bootstrap command needs)
# ---------------------------------------------------------------------------

def _load_manifest(path: Path) -> Dict[str, Any]:
    """Load LLM-BOOTSTRAP.yaml. Uses PyYAML (verified installed: 6.0.3).

    Raises ``FileNotFoundError`` if the manifest is missing; the caller
    converts that to a user-facing error.
    """
    import yaml  # Local import — only needed for bootstrap, keeps cold start cheap.
    if not path.exists():
        raise FileNotFoundError(f"Bootstrap manifest not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Minimal structural validation — the tests exercise the edges.
    for key in ("version", "tracks", "resolvers"):
        if key not in data:
            raise ValueError(f"Bootstrap manifest missing top-level key: {key}")
    if not isinstance(data["tracks"], dict) or not data["tracks"]:
        raise ValueError("Bootstrap manifest 'tracks' must be a non-empty mapping.")
    return data


def _load_model(ctx: BootstrapContext):
    """Lazily load SchemaModel; cached on ctx. Returns None if unavailable
    (tests may run with no schema present)."""
    if ctx.model is not None:
        return ctx.model
    try:
        from nightclaw_engine.schema.loader import load as _load
        ctx.model = _load(ctx.root / "orchestration-os" / "schema")
    except Exception:
        ctx.model = None
    return ctx.model


# ---------------------------------------------------------------------------
# Resolvers — each returns (heading, body). Every resolver is pure wrt args
# and ctx, so they are trivial to test.
# ---------------------------------------------------------------------------

def _read_relative(ctx: BootstrapContext, rel: str) -> Optional[str]:
    """Best-effort file read relative to repo root. Returns None if missing."""
    p = ctx.root / rel
    if not p.exists() or not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return None
    ctx.record_source(rel, len(text))
    return text


def resolve_summary(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Project a one-screen summary of the repo: name, thesis, tiers, counts."""
    model = _load_model(ctx)
    lines = [
        "NightClaw is a deterministic AI-orchestration runtime. Architecture: ",
        '"prose for reasoning, tools for guarantees" — Markdown doctrine is what',
        "the LLM reads, the typed engine is what mutates state, YAML under",
        "``orchestration-os/schema/*.yaml`` is the single source of truth.",
        "",
        "Four-tier truth model:",
        "  * Tier A — orchestration-os/schema/*.yaml       (authoritative)",
        "  * Tier B — orchestration-os/REGISTRY.md         (rendered projection)",
        "  * Tier C — PROJECTS/<slug>/phases.yaml          (per-project state)",
        "  * Tier D — audit/*.md                           (deterministic record)",
        "",
        "Canonical read order for a maintainer: AGENTS-CORE.md →",
        "orchestration-os/REGISTRY.md → internal_enhancement/ARCHITECTURE.md →",
        "internal_enhancement/CURRENT-PASS.md.",
    ]
    if model is not None:
        try:
            lines += [
                "",
                f"Schema counts (live): objects={len(model.objects)}, "
                f"fields={len(model.fields)}, routes={len(model.routes)}, "
                f"edges={len(model.edges)}, bundles={len(model.bundles)}, "
                f"scr_rules={len(model.scr_rules)}.",
                f"Schema fingerprint: {model.fingerprint}",
            ]
            ctx.record_source(
                "orchestration-os/schema/ (SchemaModel)",
                sum(len(o.obj) + len(o.file) for o in model.objects) + len(model.fingerprint),
            )
        except Exception:
            pass
    return ("Repo summary", "\n".join(lines))


def resolve_topology(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Pull the 'Runtime topology' ASCII graph section out of internal architecture."""
    text = _read_relative(ctx, "internal_enhancement/ARCHITECTURE.md")
    if text is None:
        return ("Topology", "_(internal_enhancement/ARCHITECTURE.md not found — repo layout incomplete)_")
    # internal_enhancement/ARCHITECTURE.md §1 is runtime topology, §2 telemetry. Harvest §1 + §2 if
    # present, else fall back to the whole file head.
    body = _extract_sections(text, [r"^##?\s+(?:\d+\.\s+)?Runtime topology",
                                    r"^##?\s+(?:\d+\.\s+)?Telemetry topology"])
    if not body.strip():
        body = "\n".join(text.splitlines()[:60])
    return ("Topology (runtime + telemetry)", body)


def resolve_doctrine(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Load a named doctrine file (required=False tolerates missing)."""
    rel = args.get("path", "")
    if not rel:
        raise ValueError("doctrine resolver requires args.path")
    # Path sanity: no absolute, no parent escapes.
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise ValueError(f"doctrine resolver refuses unsafe path: {rel}")
    text = _read_relative(ctx, rel)
    if text is None:
        return (f"Doctrine: {rel}", f"_(not found at {rel})_")
    return (f"Doctrine: {rel}", text)


def resolve_cron_hardlines(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Inline orchestration-os/CRON-HARDLINES.md (the operating constraints)."""
    text = _read_relative(ctx, "orchestration-os/CRON-HARDLINES.md")
    if text is None:
        return ("Cron hardlines", "_(CRON-HARDLINES.md not found)_")
    return ("Cron hardlines", text)


def resolve_bundles(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Render SchemaModel.bundles as a compact human-readable block."""
    model = _load_model(ctx)
    if model is None:
        return ("Bundles", "_(schema model unavailable — cannot enumerate bundles)_")
    lines = ["Declared R5 bundles (source: orchestration-os/schema/bundles.yaml):", ""]
    for b in model.bundles:
        lines.append(f"  * {b.name}")
        lines.append(f"      trigger   : {b.trigger}")
        if b.args:
            lines.append(f"      args      : {', '.join(b.args)}")
        if b.validates:
            lines.append(f"      validates : {', '.join(b.validates)}")
        if b.writes:
            targets = ", ".join(b.writes.keys())
            lines.append(f"      writes    : {targets}")
        if b.append:
            lines.append(f"      append    : {', '.join(f'{k}={v}' for k, v in b.append.items())}")
        if b.returns:
            lines.append(f"      returns   : {b.returns}")
        lines.append("")
    return ("Bundles", "\n".join(lines))


def resolve_invariants(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Harvest invariants from two sources and render a combined catalog.

    Source 1 — test-backed invariants: each is declared via a structured
    comment line directly above a ``def test_...():`` function, in the form::

        # @invariant: ID=INV-NN | domain=<dom> | fails_on=<condition> | remediation=<fix>

    Source 2 — SCR-backed invariants (Pass 15+): each is declared implicitly
    by an ``scr_rules.yaml`` row whose ``title`` contains ``(INV-NN)``. The
    deterministic engine's ``scr-verify`` gate enforces them; they are not
    tied to any single pytest function, so they do not carry comment
    annotations. Example: SCR-11 with title ``"… (INV-13)"``.

    ``args.filter`` (optional) is a regex; only invariants whose combined
    text matches will be included.
    """
    filter_re = None
    flt = args.get("filter")
    if flt:
        filter_re = re.compile(flt, re.IGNORECASE)

    test_catalog = harvest_invariants(ctx.root)
    scr_catalog = harvest_scr_backed_invariants(ctx.root)
    catalog = test_catalog + scr_catalog
    ctx.record_source(
        "tests/ (@invariant: annotations) + scr_rules.yaml (INV-NN titles)",
        sum(len(c["raw"]) for c in catalog),
    )

    lines = [
        "Invariant catalog (harvested from tests/ and scr_rules.yaml):",
        "",
    ]
    n_shown = 0
    for item in catalog:
        joined = " ".join(
            str(item.get(k, "")) for k in ("id", "domain", "fails_on", "remediation", "test")
        )
        if filter_re and not filter_re.search(joined):
            continue
        lines.append(f"  * {item['id']} — {item['domain']}")
        lines.append(f"      test        : {item['test']}")
        lines.append(f"      fails_on    : {item['fails_on']}")
        lines.append(f"      remediation : {item['remediation']}")
        lines.append("")
        n_shown += 1
    if n_shown == 0:
        lines.append("  _(no invariants matched — either none annotated yet, or filter too strict)_")
    return ("Invariants", "\n".join(lines))


def resolve_gate_sequence(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Enumerate the 5 CI exit gates in canonical order."""
    body = (
        "The five exit gates (run in order; all must pass before a change ships):\n"
        "\n"
        "  1. ``python3 -m pytest tests/ -q`` — full test suite, all green.\n"
        "  2. ``python3 scripts/nightclaw-ops.py schema-lint`` — prints\n"
        "     ``SCHEMA-LINT:OK:<fingerprint>`` matching the canonical fingerprint.\n"
        "  3. ``python3 scripts/nightclaw-ops.py schema-sync`` — must print\n"
        "     ``SCHEMA-SYNC:NOOP:…`` (or ``:OK:…`` exactly once per schema edit).\n"
        "  4. ``python3 scripts/nightclaw-ops.py scr-verify`` — ``RESULT:PASS``\n"
        "     for every SCR rule (SCR-01..10 + CL5).\n"
        "  5. ``python3 scripts/nightclaw-ops.py validate-bundles`` — ``RESULT:PASS``\n"
        "     for every bundle declared in bundles.yaml.\n"
        "\n"
        "Plus: ``python3 scripts/skills-sync.py`` must be a no-op after any edit\n"
        "under ``nightclaw_engine/`` (Invariant 8 fails CI otherwise)."
    )
    return ("Gate sequence", body)


def resolve_known_issues(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Inline the "Known issues" section from internal_enhancement/CURRENT-PASS.md.

    Surfaces a curated, human-maintained list of live footguns to any fresh
    LLM session so it does not discover them by stepping on them. Gracefully
    degrades if the file or the section is missing — a fresh install may not
    have a CURRENT-PASS.md yet.
    """
    rel = "internal_enhancement/CURRENT-PASS.md"
    text = _read_relative(ctx, rel)
    if text is None:
        return ("Known issues", "_(internal_enhancement/CURRENT-PASS.md not found)_")
    # Extract the body under a top-level ``## Known issues`` heading, up to
    # (but not including) the next ``## `` heading. ``_extract_sections``
    # includes the matched heading line itself; we strip it so the output
    # composer's own heading is not duplicated.
    raw = _extract_sections(text, [r"^##\s+Known issues\s*$"])
    lines = raw.splitlines()
    if lines and re.match(r"^##\s+Known issues\s*$", lines[0]):
        lines = lines[1:]
    body = "\n".join(lines).strip("\n")
    if not body.strip():
        return ("Known issues", "_(no Known issues section found in CURRENT-PASS.md)_")
    ctx.record_source(rel, len(text))
    return ("Known issues", body)


def resolve_dependency_graph(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Project SchemaModel.edges as a compact DOT-like listing."""
    model = _load_model(ctx)
    if model is None:
        return ("Dependency graph", "_(schema model unavailable)_")
    lines = ["R4 edges (source → target, typed):", ""]
    for e in model.edges:
        lines.append(f"  {e.source}  --{e.type}-->  {e.target}")
    return ("Dependency graph (R4 edges)", "\n".join(lines))


def resolve_file(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Inline a specific file. Respects path sanity (no absolute/escape)."""
    rel = args.get("path", "")
    if not rel:
        raise ValueError("file resolver requires args.path")
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise ValueError(f"file resolver refuses unsafe path: {rel}")
    text = _read_relative(ctx, rel)
    if text is None:
        return (f"File: {rel}", f"_(not found at {rel})_")
    return (f"File: {rel}", text)


def resolve_prose(ctx: BootstrapContext, args: Dict[str, Any]) -> Tuple[str, str]:
    """Emit a literal prose block declared inline in the manifest."""
    heading = args.get("heading", "Prose")
    body = args.get("body", "")
    if not isinstance(body, str):
        body = str(body)
    return (heading, body)


# Resolver registry — names here MUST match the ``resolvers:`` whitelist in
# internal_enhancement/LLM-BOOTSTRAP.yaml. Invariant 9
# (test_bootstrap_resolvers_match_manifest) enforces the lockstep.
RESOLVERS: Dict[str, Callable[[BootstrapContext, Dict[str, Any]], Tuple[str, str]]] = {
    "summary":          resolve_summary,
    "topology":         resolve_topology,
    "doctrine":         resolve_doctrine,
    "cron_hardlines":   resolve_cron_hardlines,
    "bundles":          resolve_bundles,
    "invariants":       resolve_invariants,
    "gate_sequence":    resolve_gate_sequence,
    "known_issues":     resolve_known_issues,
    "dependency_graph": resolve_dependency_graph,
    "file":             resolve_file,
    "prose":            resolve_prose,
}


# ---------------------------------------------------------------------------
# Helpers — section extraction + invariant harvest
# ---------------------------------------------------------------------------

def _extract_sections(text: str, heading_patterns: List[str]) -> str:
    """Given a markdown body + a list of heading regex patterns, return the
    body(ies) under each match, up to (but not including) the next heading of
    equal-or-higher level. Best-effort; returns joined content."""
    lines = text.splitlines()
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        matched = False
        for pat in heading_patterns:
            if re.match(pat, line):
                # Determine level of this heading (count leading '#').
                level_match = re.match(r"^(#+)", line)
                level = len(level_match.group(1)) if level_match else 2
                out.append(line)
                i += 1
                # Collect until next heading of equal or shallower level.
                while i < len(lines):
                    nxt = lines[i]
                    nxt_match = re.match(r"^(#+)\s", nxt)
                    if nxt_match and len(nxt_match.group(1)) <= level:
                        break
                    out.append(nxt)
                    i += 1
                matched = True
                break
        if not matched:
            i += 1
    return "\n".join(out)


# Structured comment grammar — intentionally strict to keep the harvester
# robust to unrelated comments above test functions. A test that omits the
# annotation is simply absent from the catalog; it does not error.
_INVARIANT_LINE_RE = re.compile(
    r"^\s*#\s*@invariant:\s*(?P<body>.+)$"
)
_TEST_DEF_RE = re.compile(r"^\s*def\s+(test_\w+)\s*\(")


def harvest_invariants(root: Path) -> List[Dict[str, str]]:
    """Walk tests/ and collect every ``# @invariant: …`` annotation that
    sits directly above a ``def test_*():`` function. Returns a list of dicts
    with keys: id, domain, fails_on, remediation, test, file, raw.

    Public (not leading underscore) because test_bootstrap.py calls it.
    """
    tests_dir = root / "tests"
    catalog: List[Dict[str, str]] = []
    if not tests_dir.exists():
        return catalog
    for path in sorted(tests_dir.rglob("test_*.py")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        pending: Optional[Dict[str, str]] = None
        for line in lines:
            m = _INVARIANT_LINE_RE.match(line)
            if m:
                pending = _parse_invariant_body(m.group("body"))
                pending["raw"] = line.strip()
                continue
            if pending is not None:
                td = _TEST_DEF_RE.match(line)
                if td:
                    pending["test"] = td.group(1)
                    pending["file"] = str(path.relative_to(root))
                    catalog.append(pending)
                    pending = None
                elif line.strip() and not line.lstrip().startswith("#"):
                    # Non-comment, non-def line: annotation was orphaned.
                    pending = None
    return catalog


# Pattern used by harvest_scr_backed_invariants to recognize an SCR rule
# that closes an INV-NN governance invariant. The canonical form is that
# the rule's ``title`` contains ``(INV-NN)`` somewhere — e.g. SCR-11 title
# is "Every R3 row at tier CODE names a file that exists on disk (INV-13)".
_SCR_TITLE_INV_RE = re.compile(r"\(INV-(\d+)\)")


def harvest_scr_backed_invariants(root: Path) -> List[Dict[str, str]]:
    """Walk ``orchestration-os/schema/scr_rules.yaml`` (via SchemaModel) and
    collect every SCR rule whose ``title`` contains ``(INV-NN)``. These are
    invariants enforced by the deterministic engine (``scr-verify``) rather
    than by a pytest function, so they do not carry ``# @invariant:``
    comment annotations. Without this harvester they would be silently
    missing from the bootstrap Invariants catalog.

    Returns dicts with the same shape as ``harvest_invariants`` so the two
    catalogs can be concatenated without special-casing:

        { id, domain, fails_on, remediation, test, file, raw }

    The ``test`` field is set to ``"scr-verify:<SCR-ID>"`` so the provenance
    is visible at a glance. ``file`` points at ``scr_rules.yaml``.
    """
    # Local import avoids a circular dependency with commands/_shared during
    # bootstrap module import (loader already does heavy work at import).
    try:
        from ..schema.loader import load as _load_schema
    except Exception:
        return []
    schema_dir = root / "orchestration-os" / "schema"
    if not schema_dir.is_dir():
        return []
    try:
        model = _load_schema(schema_dir)
    except Exception:
        return []
    scr_file = "orchestration-os/schema/scr_rules.yaml"
    catalog: List[Dict[str, str]] = []
    for rule in model.scr_rules:
        title = rule.title or ""
        m = _SCR_TITLE_INV_RE.search(title)
        if not m:
            continue
        inv_id = f"INV-{m.group(1)}"
        # Strip the trailing ``(INV-NN)`` from the fails_on prose so it reads
        # cleanly — the id is already in its own field.
        fails_on = _SCR_TITLE_INV_RE.sub("", title).strip().rstrip(".")
        if not fails_on:
            fails_on = f"{rule.predicate} reports FAIL"
        catalog.append({
            "id": inv_id,
            "domain": f"scr-backed/{rule.id.lower()}",
            "fails_on": fails_on,
            "remediation": (
                f"Run ``python3 scripts/nightclaw-ops.py scr-verify`` and "
                f"inspect the {rule.id} FAIL rows; fix the underlying data "
                f"or update the predicate ``{rule.predicate}`` in "
                f"``nightclaw_engine/protocol/integrity.py``."
            ),
            "test": f"scr-verify:{rule.id}",
            "file": scr_file,
            "raw": f"{rule.id} | {rule.severity} | {rule.predicate} | {title}",
        })
    return catalog


def _parse_invariant_body(body: str) -> Dict[str, str]:
    """Parse ``ID=… | domain=… | fails_on=… | remediation=…`` into a dict.
    Missing keys default to ``(unspecified)`` so the catalog renders cleanly
    even when authors are terse."""
    fields = {"id": "(unspecified)", "domain": "(unspecified)",
              "fails_on": "(unspecified)", "remediation": "(unspecified)"}
    for part in body.split("|"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k in fields:
                fields[k] = v
    return fields


# ---------------------------------------------------------------------------
# Budget apportionment
# ---------------------------------------------------------------------------

def _apportion_budget(sections: List[ResolvedSection], total_tokens: int) -> List[ResolvedSection]:
    """Truncate each section's body to its share of the total budget (in chars).
    Adds a trailing ``… [truncated N chars]`` marker when truncation happens.
    Sections with empty bodies get their full allowance (useful for prose)."""
    total_budget_chars = total_tokens * CHARS_PER_TOKEN
    total_share = sum(max(1, s.budget_share) for s in sections) or 1
    out: List[ResolvedSection] = []
    for s in sections:
        share = max(1, s.budget_share)
        allowance = max(200, (total_budget_chars * share) // total_share)
        body = s.body
        if len(body) > allowance:
            cut = len(body) - allowance
            body = body[:allowance] + f"\n\n… [truncated {cut} chars — see source for full text]"
        out.append(ResolvedSection(resolver=s.resolver, heading=s.heading,
                                   body=body, budget_share=s.budget_share))
    return out


# ---------------------------------------------------------------------------
# Track resolution
# ---------------------------------------------------------------------------

def resolve_track(track_name: str, manifest: Dict[str, Any],
                  ctx: BootstrapContext) -> List[ResolvedSection]:
    """Run every section in the named track and collect the results.
    Raises ``KeyError`` if the track does not exist, ``ValueError`` if a
    section references an unknown resolver."""
    tracks = manifest.get("tracks", {})
    if track_name not in tracks:
        raise KeyError(
            f"Unknown track: {track_name!r}. Available: "
            f"{', '.join(sorted(tracks.keys()))}"
        )
    track = tracks[track_name]
    resolved: List[ResolvedSection] = []
    for section in track.get("sections", []):
        name = section.get("resolver")
        if name not in RESOLVERS:
            raise ValueError(
                f"Track {track_name!r} references unknown resolver: {name!r}"
            )
        args = section.get("args") or {}
        required = section.get("required", True)
        share = int(section.get("budget_share", 100))
        try:
            heading, body = RESOLVERS[name](ctx, args)
        except Exception as exc:
            if required:
                raise
            heading = f"{name} (optional — skipped)"
            body = f"_(resolver raised {exc.__class__.__name__}: {exc})_"
        resolved.append(ResolvedSection(resolver=name, heading=heading,
                                        body=body, budget_share=share))
    return resolved


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

def render_markdown(track_name: str, sections: List[ResolvedSection],
                    ctx: BootstrapContext, budget_tokens: int) -> str:
    """Deterministic markdown output. Sections rendered in declared order;
    provenance footer lists every source consumed with byte counts."""
    lines = [
        f"# NightClaw bootstrap — track: {track_name}",
        "",
        f"_Budget: ~{budget_tokens} tokens ({budget_tokens * CHARS_PER_TOKEN} chars approx)._",
        "",
    ]
    for s in sections:
        lines.append(f"## {s.heading}")
        lines.append("")
        lines.append(s.body.rstrip())
        lines.append("")
    lines.append("---")
    lines.append("## Provenance")
    lines.append("")
    if not ctx.sources:
        lines.append("_(no external sources consumed — track used only inline prose)_")
    else:
        for rel, nchars in ctx.sources:
            lines.append(f"- `{rel}` — {nchars} chars")
    lines.append("")
    return "\n".join(lines)


def render_json(track_name: str, sections: List[ResolvedSection],
                ctx: BootstrapContext, budget_tokens: int) -> str:
    """JSON output mirrors the markdown structure for machine consumers."""
    payload = {
        "track": track_name,
        "budget_tokens": budget_tokens,
        "sections": [
            {"resolver": s.resolver, "heading": s.heading, "body": s.body}
            for s in sections
        ],
        "provenance": [{"path": rel, "chars": nchars} for rel, nchars in ctx.sources],
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# CLI entry point — hand-parsed argv per repo convention (no argparse).
# ---------------------------------------------------------------------------

def cmd_bootstrap() -> None:
    """Project a curated bootstrap view of the repo for a new LLM session."""
    argv = sys.argv[2:]  # strip "nightclaw-ops.py" + "bootstrap"

    track = "general"
    budget_override: Optional[int] = None
    format_override: Optional[str] = None
    manifest_override: Optional[Path] = None
    list_tracks = False

    for arg in argv:
        if arg == "--list-tracks":
            list_tracks = True
        elif arg.startswith("--track="):
            track = arg.split("=", 1)[1]
        elif arg.startswith("--budget="):
            try:
                budget_override = int(arg.split("=", 1)[1])
            except ValueError:
                print(f"Invalid --budget value: {arg}", file=sys.stderr)
                sys.exit(2)
        elif arg.startswith("--format="):
            format_override = arg.split("=", 1)[1]
        elif arg.startswith("--manifest="):
            manifest_override = Path(arg.split("=", 1)[1])
        else:
            print(f"Unknown bootstrap option: {arg}", file=sys.stderr)
            sys.exit(2)

    root = _shared.ROOT or _shared.workspace_root()
    manifest_path = manifest_override or (root / MANIFEST_REL)
    try:
        manifest = _load_manifest(manifest_path)
    except FileNotFoundError as exc:
        print(f"BOOTSTRAP:ERR: {exc}", file=sys.stderr)
        sys.exit(2)
    except ValueError as exc:
        print(f"BOOTSTRAP:ERR: manifest invalid: {exc}", file=sys.stderr)
        sys.exit(2)

    if list_tracks:
        print("Available tracks:")
        for name, spec in manifest.get("tracks", {}).items():
            summary = spec.get("summary", "")
            print(f"  {name:16s}  {summary}")
        return

    defaults = manifest.get("defaults", {}) or {}
    budget_tokens = budget_override or int(defaults.get("budget_tokens", 12000))
    out_format = format_override or str(defaults.get("format", "md"))

    ctx = BootstrapContext(root=root)
    try:
        resolved = resolve_track(track, manifest, ctx)
    except KeyError as exc:
        print(f"BOOTSTRAP:ERR: {exc}", file=sys.stderr)
        sys.exit(2)
    except ValueError as exc:
        print(f"BOOTSTRAP:ERR: {exc}", file=sys.stderr)
        sys.exit(2)

    resolved = _apportion_budget(resolved, budget_tokens)

    if out_format == "json":
        print(render_json(track, resolved, ctx, budget_tokens))
    elif out_format == "md":
        print(render_markdown(track, resolved, ctx, budget_tokens))
    else:
        print(f"BOOTSTRAP:ERR: unknown format {out_format!r}", file=sys.stderr)
        sys.exit(2)
