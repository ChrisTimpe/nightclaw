"""tests/core/test_cmd_module_helpers.py — Pass-7 per-module unit tests.

Pass 6 split the monolithic ``_legacy`` module into 10 smaller modules under
``nightclaw_engine/commands/``. Per the architecture plan, every module is
expected to have direct unit coverage in addition to the integration tests
exercised via CLI subprocess calls.

This file provides the per-module test debt absorbed from Pass 6 — targeted
unit tests for pure helpers in each module. Integration-level coverage for
entire commands continues to live in the integration / CLI tests.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.commands import _shared
from nightclaw_engine.commands import append as cmd_append
from nightclaw_engine.commands import bundle as cmd_bundle
from nightclaw_engine.commands import bundle_mutators as cmd_mutators
from nightclaw_engine.commands import __init__ as cmd_root  # noqa: F401 — ensures import works


# --------------------------------------------------------------------------- #
# _shared.py
# --------------------------------------------------------------------------- #

class TestSharedIsoParsing:
    def test_parse_iso_zulu_form(self):
        dt = _shared.parse_iso("2026-04-03T12:00:00Z")
        assert dt == datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_iso_offset_form(self):
        dt = _shared.parse_iso("2026-04-03T12:00:00+00:00")
        assert dt == datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_iso_naive_coerced_to_utc(self):
        dt = _shared.parse_iso("2026-04-03T12:00:00")
        assert dt.tzinfo == timezone.utc

    @pytest.mark.parametrize("sentinel", ["—", "-", "~", "null", "None", "none", "", None])
    def test_parse_iso_sentinels_return_none(self, sentinel):
        assert _shared.parse_iso(sentinel) is None

    def test_parse_iso_invalid_returns_none(self):
        assert _shared.parse_iso("not-a-date") is None

    def test_now_utc_is_tz_aware(self):
        n = _shared.now_utc()
        assert n.tzinfo is not None


# --------------------------------------------------------------------------- #
# append.py
# --------------------------------------------------------------------------- #

class TestAppendTargetGate:
    def test_legacy_allowlist_members_permitted(self):
        # A representative member of the legacy allow-list must always be allowed.
        for p in _shared.APPEND_ALLOWED:
            assert cmd_append._is_allowed_append_target(p), p

    def test_append_allowed_matches_r3_append_tier(self):
        """APPEND_ALLOWED in _shared.py must be kept in sync with R3 APPEND-tier
        entries in routing.yaml.  Adding a file to routing.yaml with tier=APPEND
        without updating _shared.py (or vice-versa) will fail here.

        The dynamic memory/YYYY-MM-DD.md route is excluded from this check
        because it is matched by regex rather than a literal frozenset entry.
        Suffix-qualified variants such as "NOTIFICATIONS.md(append)" are
        normalised to their bare name before comparison so both sides speak
        the same language.
        """
        from nightclaw_engine.schema.loader import load as _load
        model = _load(REPO_ROOT / "orchestration-os" / "schema")

        _DYNAMIC = {"memory/YYYY-MM-DD.md"}   # handled by regex, not frozenset

        # Collect every R3 APPEND-tier file name, stripping "(suffix)" qualifiers.
        schema_append: set[str] = set()
        for route in model.routes:
            if route.tier.upper() != "APPEND":
                continue
            bare = route.file.split("(")[0]   # strip e.g. "(append)" / "(prune)"
            if bare in _DYNAMIC:
                continue
            schema_append.add(bare)

        # Every schema APPEND file must be in APPEND_ALLOWED.
        missing_from_shared = schema_append - _shared.APPEND_ALLOWED
        assert not missing_from_shared, (
            f"routing.yaml declares these files as APPEND tier but they are "
            f"missing from _shared.APPEND_ALLOWED: {sorted(missing_from_shared)}\n"
            f"Add them to nightclaw_engine/commands/_shared.py APPEND_ALLOWED."
        )

        # Every APPEND_ALLOWED entry must have a corresponding R3 APPEND-tier row.
        missing_from_schema = _shared.APPEND_ALLOWED - schema_append
        assert not missing_from_schema, (
            f"_shared.APPEND_ALLOWED contains files not declared as APPEND tier "
            f"in routing.yaml: {sorted(missing_from_schema)}\n"
            f"Add them to orchestration-os/schema/routing.yaml with tier: APPEND."
        )

    def test_memory_date_pattern_permitted(self):
        assert cmd_append._is_allowed_append_target("memory/2026-04-03.md")

    def test_memory_malformed_date_rejected(self):
        # Not matching the YYYY-MM-DD shape and not in R3 APPEND routes.
        assert not cmd_append._is_allowed_append_target("memory/2026-04-3.md")

    def test_arbitrary_file_rejected(self):
        assert not cmd_append._is_allowed_append_target("random/path.md")

    def test_backslashes_normalized(self):
        # A Windows-style separator should not bypass the gate.
        p = next(iter(_shared.APPEND_ALLOWED))
        assert cmd_append._is_allowed_append_target(p.replace("/", "\\"))


# --------------------------------------------------------------------------- #
# bundle.py — expression resolver + guard evaluator
# --------------------------------------------------------------------------- #

class TestResolveExpression:
    def test_literal_passthrough(self):
        assert cmd_bundle.resolve_expression("ACTIVE", {}) == "ACTIVE"

    def test_arg_substitution(self):
        assert cmd_bundle.resolve_expression("{slug}", {"slug": "demo"}) == "demo"

    def test_null_marker_passthrough(self):
        # The executor uses "~" as an explicit NULL/clear sentinel and
        # carries it through the resolver verbatim so downstream mutators
        # can treat it as a deletion signal.
        assert cmd_bundle.resolve_expression("~", {}) == "~"

    def test_none_expr_returns_empty(self):
        assert cmd_bundle.resolve_expression(None, {}) == ""

    def test_now_literal_is_iso_z(self):
        out = cmd_bundle.resolve_expression("{NOW}", {})
        # ISO8601 Z-suffixed timestamp
        assert out.endswith("Z") and "T" in out

    def test_today_literal_is_date(self):
        out = cmd_bundle.resolve_expression("{TODAY}", {})
        # YYYY-MM-DD shape
        assert len(out) == 10 and out[4] == "-" and out[7] == "-"


# --------------------------------------------------------------------------- #
# bundle.py — schema-sync splice primitives (F9)
# --------------------------------------------------------------------------- #

class TestSchemaSyncPrimitives:
    def test_generated_bodies_have_expected_section_ids(self):
        from nightclaw_engine.schema.loader import load
        model = load(REPO_ROOT / "orchestration-os" / "schema")
        bodies = cmd_bundle._generated_section_bodies(model)
        assert set(bodies.keys()) == {"R1", "R2", "R3", "R4", "R5", "R6", "CL5"}

    def test_generated_bodies_never_contain_heading_line(self):
        """The canonical body strips the leading `## <title>` line."""
        from nightclaw_engine.schema.loader import load
        model = load(REPO_ROOT / "orchestration-os" / "schema")
        bodies = cmd_bundle._generated_section_bodies(model)
        for sid, body in bodies.items():
            # Body must start with \n (leading separator), not with `## `.
            assert not body.lstrip().startswith("## "), (
                f"Body for {sid} retained its section heading")

    def test_splice_section_raises_on_missing_marker(self):
        with pytest.raises(ValueError):
            cmd_bundle._splice_section("no markers here", "R1", "\n\n")


# --------------------------------------------------------------------------- #
# commands/__init__.py — command dispatcher
# --------------------------------------------------------------------------- #

class TestCommandDispatcher:
    def test_schema_sync_registered(self):
        from nightclaw_engine.commands import COMMANDS
        assert "schema-sync" in COMMANDS
        assert COMMANDS["schema-sync"] is cmd_bundle.cmd_schema_sync

    def test_all_three_schema_commands_are_distinct_callables(self):
        from nightclaw_engine.commands import COMMANDS
        fns = {COMMANDS["schema-render"], COMMANDS["schema-sync"], COMMANDS["schema-lint"]}
        assert len(fns) == 3

    def test_step_tier_map_includes_schema_sync(self):
        from nightclaw_engine.commands import STEP_CMD_MAP
        assert STEP_CMD_MAP.get("schema-sync") == "T8"


# --------------------------------------------------------------------------- #
# bundle_mutators.py — surface smoke
# --------------------------------------------------------------------------- #

class TestBundleMutatorsSurface:
    def test_module_exports_five_mutators(self):
        names = {"mutate_longrunner_field", "mutate_dispatch_field",
                 "mutate_manifest_field", "mutate_lock_field", "do_append"}
        assert names.issubset(set(dir(cmd_mutators)))

    def test_mutators_are_callables(self):
        for n in ("mutate_longrunner_field", "mutate_dispatch_field",
                  "mutate_manifest_field", "mutate_lock_field", "do_append"):
            assert callable(getattr(cmd_mutators, n))


# --------------------------------------------------------------------------- #
# audit.py — cmd_os_file_sizes
# --------------------------------------------------------------------------- #

class TestOsFileSizes:
    """Unit tests for the os-file-sizes command added in the archival pass."""

    def _run(self, monkeypatch, file_map: dict) -> list[str]:
        """Run cmd_os_file_sizes with a temp directory whose files are provided
        as {relative_path: line_count} and return stdout lines."""
        import io, pathlib, tempfile
        from nightclaw_engine.commands import audit as cmd_audit
        from nightclaw_engine.commands import _shared

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for rel, n_lines in file_map.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("\n".join(["x"] * n_lines), encoding="utf-8")

            monkeypatch.setattr(_shared, "ROOT", str(root))

            buf = io.StringIO()
            import sys
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                cmd_audit.cmd_os_file_sizes()
            finally:
                sys.stdout = old_stdout

        return buf.getvalue().splitlines()

    def test_all_ok_when_under_thresholds(self, monkeypatch):
        lines = self._run(monkeypatch, {
            "orchestration-os/OPS-FAILURE-MODES.md":      100,
            "orchestration-os/OPS-KNOWLEDGE-EXECUTION.md": 100,
            "orchestration-os/OPS-TOOL-REGISTRY.md":       100,
            "AGENTS-LESSONS.md":                            100,
        })
        assert "RESULT:OK" in lines
        assert all("THRESHOLD_EXCEEDED" not in l for l in lines if l.startswith("SIZE:"))

    def test_single_file_exceeds_threshold(self, monkeypatch):
        lines = self._run(monkeypatch, {
            "orchestration-os/OPS-FAILURE-MODES.md":      1501,   # threshold 1500
            "orchestration-os/OPS-KNOWLEDGE-EXECUTION.md": 100,
            "orchestration-os/OPS-TOOL-REGISTRY.md":       100,
            "AGENTS-LESSONS.md":                            100,
        })
        # SIZE line for the exceeded file
        exceeded = [l for l in lines if "OPS-FAILURE-MODES" in l and "THRESHOLD_EXCEEDED" in l]
        assert exceeded, f"Expected exceeded SIZE line, got: {lines}"
        # RESULT line signals which file
        result_line = next((l for l in lines if l.startswith("RESULT:")), "")
        assert "THRESHOLD_EXCEEDED" in result_line
        assert "OPS-FAILURE-MODES" in result_line

    def test_missing_file_emits_missing_status(self, monkeypatch):
        # Only provide three of the four expected files
        lines = self._run(monkeypatch, {
            "orchestration-os/OPS-KNOWLEDGE-EXECUTION.md": 100,
            "orchestration-os/OPS-TOOL-REGISTRY.md":       100,
            "AGENTS-LESSONS.md":                            100,
        })
        missing_lines = [l for l in lines if "MISSING" in l]
        assert missing_lines, f"Expected a MISSING line, got: {lines}"
        assert "OPS-FAILURE-MODES" in missing_lines[0]

    def test_output_format_per_line(self, monkeypatch):
        """Each SIZE line must be SIZE:<rel>:<count>:<status>."""
        import re
        lines = self._run(monkeypatch, {
            "orchestration-os/OPS-FAILURE-MODES.md":      10,
            "orchestration-os/OPS-KNOWLEDGE-EXECUTION.md": 10,
            "orchestration-os/OPS-TOOL-REGISTRY.md":       10,
            "AGENTS-LESSONS.md":                            10,
        })
        pattern = re.compile(r"^SIZE:[^:]+:\d+:(OK|THRESHOLD_EXCEEDED)$")
        size_lines = [l for l in lines if l.startswith("SIZE:")]
        assert len(size_lines) == 4
        for l in size_lines:
            assert pattern.match(l), f"Malformed SIZE line: {l!r}"

    def test_registered_in_commands_table(self):
        from nightclaw_engine.commands import COMMANDS
        assert "os-file-sizes" in COMMANDS

    def test_tier_is_t8(self):
        from nightclaw_engine.commands import STEP_CMD_MAP
        assert STEP_CMD_MAP.get("os-file-sizes") == "T8"
