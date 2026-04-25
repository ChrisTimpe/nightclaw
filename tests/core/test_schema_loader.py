"""tests/core/test_schema_loader.py — Tier A YAML loader contract.

Verifies the Merge-1 schema loader (``nightclaw_engine.schema.loader``) loads
the authoritative YAML files under ``orchestration-os/schema/`` and exposes
the typed SchemaModel with stable invariants. All assertions are structural:
we do not hard-code row counts that will shift legitimately in Merge 2, but
we do assert floor values derived from the REGISTRY baseline captured at the
start of Merge 1.

Baseline (REGISTRY.md, 2026.4.16):
  * R1 objects:          17
  * R2 field contracts:  ~75 (floor: 60)
  * R3 route rules:      populated
  * R4 edges:            populated
  * R5 bundles:          8 canonical names
  * R6 SCR rules:        SCR-01 through SCR-09
  * CL5 protected paths: populated
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Allow ``python -m pytest tests/`` from the repo root without install step.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.schema import loader as schema_loader
from nightclaw_engine.schema.loader import (
    BundleSpec,
    Edge,
    FieldSpec,
    ObjectSpec,
    RouteRule,
    SCRRule,
    SchemaError,
    SchemaModel,
)


SCHEMA_DIR = REPO_ROOT / "orchestration-os" / "schema"


@pytest.fixture(autouse=True)
def _clean_cache():
    schema_loader.invalidate()
    yield
    schema_loader.invalidate()


# --- Load success & typing --------------------------------------------------


def test_load_returns_schema_model_instance():
    model = schema_loader.load(SCHEMA_DIR)
    assert isinstance(model, SchemaModel)


def test_load_populates_all_sections():
    model = schema_loader.load(SCHEMA_DIR)

    assert len(model.objects) >= 15, "R1 should have all 17 canonical objects"
    assert len(model.fields) >= 60, "R2 should carry the full field contract set"
    assert len(model.routes) >= 5
    assert len(model.edges) >= 10
    assert len(model.bundles) == 8, "R5 declares exactly 8 bundles"
    assert len(model.protected_paths) >= 8, "CL5 PROTECTED-PATHS must be non-trivial"
    assert len(model.scr_rules) >= 9, "R6 must expose at least SCR-01 through SCR-09"


def test_load_yields_correctly_typed_rows():
    model = schema_loader.load(SCHEMA_DIR)
    assert all(isinstance(o, ObjectSpec) for o in model.objects)
    assert all(isinstance(f, FieldSpec) for f in model.fields)
    assert all(isinstance(r, RouteRule) for r in model.routes)
    assert all(isinstance(e, Edge) for e in model.edges)
    assert all(isinstance(b, BundleSpec) for b in model.bundles)
    assert all(isinstance(s, SCRRule) for s in model.scr_rules)


def test_schema_paths_declared():
    model = schema_loader.load(SCHEMA_DIR)
    # schema_paths tracks the Tier-A YAML files themselves so the engine can
    # integrity-check them in Merge 2.
    assert len(model.schema_paths) >= 5
    for p in model.schema_paths:
        assert p.endswith(".yaml"), f"schema_paths should be YAML files, got {p}"


# --- Bundle + helper contract ----------------------------------------------


CANONICAL_BUNDLE_NAMES = {
    "longrunner_update",
    "phase_transition",
    "phase_advance",
    "route_block",
    "surface_escalation",
    "pa_invoke",
    "manifest_verify",
    "session_close",
}


def test_bundle_names_match_registry_r5():
    model = schema_loader.load(SCHEMA_DIR)
    names = {b.name for b in model.bundles}
    assert names == CANONICAL_BUNDLE_NAMES


def test_bundle_lookup_helper():
    model = schema_loader.load(SCHEMA_DIR)
    assert model.bundle("longrunner_update") is not None
    assert model.bundle("__does_not_exist__") is None


def test_bundle_args_and_writes_nonempty():
    model = schema_loader.load(SCHEMA_DIR)
    lr = model.bundle("longrunner_update")
    assert lr is not None
    assert isinstance(lr.args, tuple) and len(lr.args) > 0
    assert isinstance(lr.writes, dict)


def test_is_protected_helper():
    model = schema_loader.load(SCHEMA_DIR)
    # At least one protected path should exist and round-trip through the helper.
    assert model.protected_paths, "protected_paths must not be empty"
    sample = model.protected_paths[0]
    assert model.is_protected(sample) is True
    assert model.is_protected("PATH/THAT/DOES/NOT/EXIST.md") is False


# --- SCR rule contract ------------------------------------------------------


def test_scr_rules_cover_01_through_09():
    """The original nine SCR predicates must remain declared.

    Pass 5 added SCR-10 (code_files_have_r3_rows); later passes may add more.
    The invariant this test guards is that SCR-01..09 stay present and named.
    """
    model = schema_loader.load(SCHEMA_DIR)
    ids = {r.id for r in model.scr_rules}
    required = {f"SCR-0{i}" for i in range(1, 10)}
    assert required.issubset(ids), f"missing SCR rules: {required - ids}"


def test_scr_rules_have_severity_and_predicate():
    model = schema_loader.load(SCHEMA_DIR)
    for r in model.scr_rules:
        assert r.severity, f"{r.id} missing severity"
        assert r.predicate, f"{r.id} missing predicate"
        assert r.title, f"{r.id} missing title"


# --- Cache + fingerprint ----------------------------------------------------


def test_fingerprint_is_sha256_hex():
    model = schema_loader.load(SCHEMA_DIR)
    assert len(model.fingerprint) == 64
    int(model.fingerprint, 16)  # must parse as hex


def test_load_cache_returns_same_object_within_mtime():
    first = schema_loader.load(SCHEMA_DIR)
    second = schema_loader.load(SCHEMA_DIR)
    # mtime cache: identical fingerprint + same object reference
    assert first.fingerprint == second.fingerprint
    assert first is second


def test_force_bypass_returns_fresh_model():
    first = schema_loader.load(SCHEMA_DIR)
    second = schema_loader.load(SCHEMA_DIR, force=True)
    assert first.fingerprint == second.fingerprint
    assert first is not second


def test_invalidate_clears_cache():
    first = schema_loader.load(SCHEMA_DIR)
    schema_loader.invalidate(SCHEMA_DIR)
    second = schema_loader.load(SCHEMA_DIR)
    assert first is not second
    assert first.fingerprint == second.fingerprint


# --- Error paths ------------------------------------------------------------


def test_missing_schema_dir_raises_schema_error(tmp_path: Path):
    with pytest.raises(SchemaError):
        schema_loader.load(tmp_path / "does_not_exist")


def test_invalid_yaml_top_shape_raises(tmp_path: Path):
    # Write a minimal fake schema dir where objects.yaml has the wrong shape.
    d = tmp_path / "schema"
    d.mkdir()
    (d / "objects.yaml").write_text("- not-a-mapping\n", encoding="utf-8")
    (d / "fields.yaml").write_text("fields: []\n", encoding="utf-8")
    (d / "routing.yaml").write_text("routes: []\n", encoding="utf-8")
    (d / "edges.yaml").write_text("edges: []\n", encoding="utf-8")
    (d / "bundles.yaml").write_text("bundles: []\n", encoding="utf-8")
    (d / "protected.yaml").write_text(
        "protected_paths: []\nschema_paths: []\n", encoding="utf-8"
    )
    (d / "scr_rules.yaml").write_text("scr_rules: []\n", encoding="utf-8")
    with pytest.raises(SchemaError):
        schema_loader.load(d)
