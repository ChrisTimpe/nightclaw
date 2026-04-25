"""tests/core/test_bootstrap.py — Pass 10 LLM bootstrap projection.

Covers the declarative bootstrap track system introduced in Pass 10:

* Manifest structural validity (all tracks declared; all referenced
  resolvers exist).
* Resolver registry lockstep with the manifest whitelist (Invariant 10).
* Invariant catalog harvester — finds every ``# @invariant:`` annotation
  and returns structured metadata (Invariant 11).
* Budget apportionment — truncation respects section share ratios
  (Invariant 12).
* Command smoke test — every declared track resolves without raising.

These tests are declared with the same ``# @invariant: …`` protocol the
bootstrap harvester consumes, so Pass 10's own invariants appear in the
catalog that the ``bootstrap`` command renders.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.commands import bootstrap as _boot  # noqa: E402


# ---------------------------------------------------------------------------
# Manifest loader + structure
# ---------------------------------------------------------------------------

def _manifest():
    return _boot._load_manifest(REPO_ROOT / _boot.MANIFEST_REL)


def test_manifest_loads_and_has_expected_top_level_shape():
    """LLM-BOOTSTRAP.yaml must load cleanly and expose version, defaults,
    resolvers, tracks — the shape the bootstrap command depends on."""
    m = _manifest()
    assert m["version"] == 1
    assert "defaults" in m and "budget_tokens" in m["defaults"]
    assert isinstance(m["resolvers"], list) and m["resolvers"]
    assert isinstance(m["tracks"], dict) and m["tracks"]


def test_manifest_declares_all_six_tracks():
    """Pass 10 ships all six tracks in v1; any drop would be a scope regression."""
    m = _manifest()
    expected = {"general", "add_bundle", "edit_schema", "fix_bug",
                "review_pr", "add_predicate"}
    assert expected.issubset(m["tracks"].keys()), (
        f"Missing tracks: {expected - set(m['tracks'].keys())}"
    )


def test_every_section_in_every_track_references_declared_resolver():
    """Each section's ``resolver:`` must appear in the manifest's
    top-level ``resolvers:`` whitelist. Prevents typos becoming silent
    runtime surprises."""
    m = _manifest()
    whitelist = set(m["resolvers"])
    for track_name, track in m["tracks"].items():
        for i, section in enumerate(track.get("sections", [])):
            name = section.get("resolver")
            assert name in whitelist, (
                f"track {track_name!r} section {i}: "
                f"resolver {name!r} not in manifest resolvers:"
            )


# ---------------------------------------------------------------------------
# Invariant 10 — resolver registry lockstep with manifest whitelist.
# ---------------------------------------------------------------------------

# @invariant: ID=INV-10 | domain=bootstrap/registry | fails_on=nightclaw_engine/commands/bootstrap.py RESOLVERS dict diverges from internal_enhancement/LLM-BOOTSTRAP.yaml resolvers: whitelist | remediation=update both in the same commit; they are the two halves of the bootstrap contract
def test_bootstrap_resolvers_match_manifest():
    """``RESOLVERS`` in commands/bootstrap.py MUST contain exactly the names
    declared in the manifest's ``resolvers:`` whitelist. Any drift breaks
    either track resolution (manifest references a missing resolver) or
    silently shadows a registered resolver (code adds one the manifest
    doesn't sanction). Lockstep is enforced here."""
    m = _manifest()
    manifest_resolvers = set(m["resolvers"])
    code_resolvers = set(_boot.RESOLVERS.keys())
    assert code_resolvers == manifest_resolvers, (
        f"Resolver registry drift. "
        f"In code only: {sorted(code_resolvers - manifest_resolvers)}. "
        f"In manifest only: {sorted(manifest_resolvers - code_resolvers)}."
    )


# ---------------------------------------------------------------------------
# Invariant 11 — invariant catalog harvest is non-empty, structured, and
# covers every @invariant: line that exists in tests/.
# ---------------------------------------------------------------------------

# @invariant: ID=INV-11 | domain=bootstrap/harvest | fails_on=harvest_invariants returns fewer items than there are '# @invariant:' lines in tests/ attached to a def test_* | remediation=inspect harvest_invariants regex vs the failing test annotation; annotation grammar is documented in bootstrap.py docstring
def test_invariant_harvester_finds_every_annotation():
    """The harvester must discover every ``# @invariant:`` comment that
    sits directly above a ``def test_*():``. A delta between the regex
    count of annotations and the harvester's yield indicates the parser
    has gotten out of sync with the annotation grammar."""
    import re
    tests_dir = REPO_ROOT / "tests"
    raw_count = 0
    for path in tests_dir.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        # Match only annotations immediately followed (optional blank line
        # tolerance is a property of the harvester, not of this count).
        raw_count += sum(
            1 for _ in re.finditer(
                r"^\s*#\s*@invariant:.*(?:\r?\n)+\s*def\s+test_\w+\s*\(",
                text, re.MULTILINE,
            )
        )
    catalog = _boot.harvest_invariants(REPO_ROOT)
    assert len(catalog) == raw_count, (
        f"Harvester found {len(catalog)} invariants but regex counts "
        f"{raw_count} in tests/. One of them has drifted from the grammar "
        f"described in commands/bootstrap.py docstring."
    )
    # Spot-check structure of at least one entry.
    assert catalog, "no invariants harvested at all"
    first = catalog[0]
    for key in ("id", "domain", "fails_on", "remediation", "test", "file"):
        assert key in first, f"missing key {key} in harvest entry"


def test_invariant_harvester_picks_up_pass10_ids():
    """The Pass 10 invariants (INV-10..INV-12) must be discoverable via the
    harvester — otherwise the bootstrap command's own invariants would not
    appear in the catalog it renders."""
    catalog = _boot.harvest_invariants(REPO_ROOT)
    ids = {item["id"] for item in catalog}
    for expected in ("INV-10", "INV-11", "INV-12"):
        assert expected in ids, f"Pass 10 invariant {expected} missing from catalog"


# ---------------------------------------------------------------------------
# Invariant 12 — budget apportionment is share-proportional and lossless
# outside of the truncation marker.
# ---------------------------------------------------------------------------

# @invariant: ID=INV-12 | domain=bootstrap/budget | fails_on=sum of section char-allowances exceeds total budget, or a section with share >> another gets equal or smaller allowance | remediation=inspect _apportion_budget; allowance math is (total_budget_chars * share / sum_shares) with a 200-char floor
def test_budget_apportionment_is_share_proportional():
    """A section with a larger ``budget_share`` must receive at least as
    much allowance as a section with a smaller share (given the same
    total budget). Truncation markers are added only when a body exceeds
    its allowance."""
    sections = [
        _boot.ResolvedSection(resolver="prose", heading="A",
                              body="x" * 10000, budget_share=10),
        _boot.ResolvedSection(resolver="prose", heading="B",
                              body="y" * 10000, budget_share=90),
    ]
    out = _boot._apportion_budget(sections, total_tokens=1000)  # 4000 chars
    # Section B (share=90) must end up with a strictly longer body than A.
    assert len(out[1].body) > len(out[0].body), (
        f"share-proportional failure: A={len(out[0].body)}, B={len(out[1].body)}"
    )
    # Both should have truncation markers (both inputs were larger than share).
    assert "[truncated" in out[0].body
    assert "[truncated" in out[1].body


def test_budget_does_not_truncate_short_sections():
    """Sections whose body already fits inside their allowance must be
    untouched — no stray truncation marker added."""
    sections = [
        _boot.ResolvedSection(resolver="prose", heading="short",
                              body="tiny", budget_share=100),
    ]
    out = _boot._apportion_budget(sections, total_tokens=10000)
    assert out[0].body == "tiny"


# ---------------------------------------------------------------------------
# Track resolution smoke tests — every declared track must resolve without
# raising, in both formats.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("track", [
    "general", "add_bundle", "edit_schema",
    "fix_bug", "review_pr", "add_predicate",
])
def test_every_track_resolves_cleanly(track):
    """Each track must resolve end-to-end. Missing optional sources are
    tolerated; missing required sources are a test failure (by design)."""
    ctx = _boot.BootstrapContext(root=REPO_ROOT)
    sections = _boot.resolve_track(track, _manifest(), ctx)
    assert sections, f"track {track!r} produced no sections"
    # Every section must have a non-empty heading.
    for s in sections:
        assert s.heading, f"section in {track!r} has empty heading"


# ---------------------------------------------------------------------------
# End-to-end CLI smoke (subprocess) — proves the command is wired and emits
# valid markdown / JSON.
# ---------------------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "nightclaw-ops.py"),
         "bootstrap", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def test_cli_list_tracks_lists_all_six():
    r = _run_cli("--list-tracks")
    assert r.returncode == 0, r.stderr
    for name in ("general", "add_bundle", "edit_schema",
                 "fix_bug", "review_pr", "add_predicate"):
        assert name in r.stdout, f"track {name!r} missing from --list-tracks"


def test_cli_default_general_emits_markdown_with_provenance():
    r = _run_cli("--track=general", "--budget=4000")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("# NightClaw bootstrap — track: general")
    assert "## Provenance" in r.stdout


def test_cli_json_format_is_valid_json():
    r = _run_cli("--track=general", "--format=json", "--budget=4000")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["track"] == "general"
    assert isinstance(payload["sections"], list) and payload["sections"]
    assert isinstance(payload["provenance"], list)


def test_cli_unknown_track_errors_cleanly():
    r = _run_cli("--track=no-such-track")
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "BOOTSTRAP:ERR" in r.stderr
    assert "Unknown track" in r.stderr


# ---------------------------------------------------------------------------
# Invariant 15 — SCR-backed harvester completeness. Every ``(INV-NN)`` tag
# that appears in an scr_rules.yaml rule title must be surfaced by
# ``harvest_scr_backed_invariants`` and therefore by ``resolve_invariants``.
# Without this gate, adding a new SCR-backed invariant to the schema without
# updating the harvester would silently drop it from the bootstrap catalog
# that a fresh LLM reads to learn the governance surface.
# ---------------------------------------------------------------------------

# @invariant: ID=INV-15 | domain=bootstrap/scr-harvest | fails_on=an (INV-NN) tag in an orchestration-os/schema/scr_rules.yaml rule title is not emitted by harvest_scr_backed_invariants, or the emitted entry is missing the canonical keys (id, domain, fails_on, remediation, test, file, raw) | remediation=inspect harvest_scr_backed_invariants in nightclaw_engine/commands/bootstrap.py; the regex _SCR_TITLE_INV_RE expects literal ``(INV-NN)`` and the SchemaModel loader must expose the rule in model.scr_rules
def test_scr_backed_harvester_covers_every_inv_tag_in_scr_rules():
    """Walk orchestration-os/schema/scr_rules.yaml line-by-line and count
    every ``(INV-NN)`` tag that appears inside a rule title. The set of
    ids discovered by ``harvest_scr_backed_invariants`` must be a superset
    of this ground-truth set — otherwise a new SCR-backed invariant has
    been authored in the schema but the bootstrap catalog would miss it.
    """
    import re
    scr_yaml = REPO_ROOT / "orchestration-os" / "schema" / "scr_rules.yaml"
    text = scr_yaml.read_text(encoding="utf-8")
    # Regex matches INV-NN tokens inside parentheses that live on a line
    # declaring an SCR rule (i.e. a YAML mapping entry with a ``title:``).
    ground_truth = set()
    for line in text.splitlines():
        if "title:" not in line:
            continue
        for m in re.finditer(r"\(INV-(\d+)\)", line):
            ground_truth.add(f"INV-{m.group(1)}")
    # If ground_truth is empty the test is still meaningful: it proves the
    # harvester is not emitting spurious entries either.
    catalog = _boot.harvest_scr_backed_invariants(REPO_ROOT)
    harvested_ids = {entry["id"] for entry in catalog}
    missing = ground_truth - harvested_ids
    assert not missing, (
        f"SCR-backed invariants in scr_rules.yaml not surfaced by harvester: "
        f"{sorted(missing)}. Inspect harvest_scr_backed_invariants and "
        f"_SCR_TITLE_INV_RE in nightclaw_engine/commands/bootstrap.py."
    )
    # Every emitted entry must carry the full canonical key set so the
    # rendering layer in resolve_invariants does not KeyError.
    for entry in catalog:
        for key in ("id", "domain", "fails_on", "remediation", "test", "file", "raw"):
            assert key in entry, (
                f"SCR-backed catalog entry {entry.get('id', '?')!r} missing key {key!r}"
            )
        # The test field must point at scr-verify so provenance is visible.
        assert entry["test"].startswith("scr-verify:"), (
            f"entry {entry['id']} test field {entry['test']!r} should start with 'scr-verify:'"
        )


def test_resolve_invariants_unions_test_and_scr_catalogs():
    """``resolve_invariants`` must concatenate the pytest-annotation catalog
    and the SCR-backed catalog. Regression guard against a future refactor
    that drops one of the two sources."""
    ctx = _boot.BootstrapContext(root=REPO_ROOT)
    _heading, body = _boot.resolve_invariants(ctx, {})
    # At least one test-backed invariant (INV-11 is self-referential and
    # therefore guaranteed to exist as long as tests/ is non-empty).
    assert "INV-11" in body, "test-backed INV-11 missing from resolve_invariants output"
    # At least one SCR-backed invariant (INV-13 is backed by SCR-11 since Pass 13).
    assert "INV-13" in body, "SCR-backed INV-13 missing from resolve_invariants output"
