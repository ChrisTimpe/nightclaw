"""tests/core/test_phase_machine.py — Tier C phase state machine loader.

Covers ``nightclaw_engine.schema.phases``:
  * load_phase_machine: schema validation (required fields, unknown successors)
  * load_phase_machine_for_slug: path safety
  * PhaseMachine: get / phase_names / allows_transition / is_terminal

The tests build minimal YAML fixtures inside a tmp_path so they do not
depend on any data outside the test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.schema.loader import SchemaError
from nightclaw_engine.schema.phases import (
    PhaseMachine,
    load_phase_machine,
    load_phase_machine_for_slug,
)

VALID_YAML = """\
slug: demo
initial_phase: a
phases:
  a:
    objective: "first"
    stop_condition: "stop_a"
    allowed_tools: [web_search]
    successors: [b]
  b:
    objective: "second"
    stop_condition: "stop_b"
    allowed_tools: [file_system]
    successors: []
"""


def _write(tmp_path, body):
    p = tmp_path / "phases.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_phase_machine_valid(tmp_path):
    fp = _write(tmp_path, VALID_YAML)
    m = load_phase_machine(fp)
    assert isinstance(m, PhaseMachine)
    assert m.slug == "demo"
    assert m.initial_phase == "a"
    assert m.phase_names == ("a", "b")
    assert m.allows_transition("a", "b")
    assert not m.allows_transition("b", "a")
    assert m.is_terminal("b")
    assert not m.is_terminal("a")
    assert m.get("a").allowed_tools == ("web_search",)


def test_load_phase_machine_missing_initial(tmp_path):
    bad = VALID_YAML.replace("initial_phase: a", "initial_phase: c")
    fp = _write(tmp_path, bad)
    with pytest.raises(SchemaError):
        load_phase_machine(fp)


def test_load_phase_machine_undeclared_successor(tmp_path):
    bad = VALID_YAML.replace("successors: [b]", "successors: [nonexistent]")
    fp = _write(tmp_path, bad)
    with pytest.raises(SchemaError):
        load_phase_machine(fp)


def test_load_phase_machine_missing_objective(tmp_path):
    bad = VALID_YAML.replace('objective: "first"', 'objective: ""')
    fp = _write(tmp_path, bad)
    with pytest.raises(SchemaError):
        load_phase_machine(fp)


def test_load_phase_machine_file_not_found(tmp_path):
    with pytest.raises(SchemaError):
        load_phase_machine(tmp_path / "nope.yaml")


def test_load_phase_machine_for_slug_rejects_traversal(tmp_path):
    with pytest.raises(SchemaError):
        load_phase_machine_for_slug(tmp_path, "../../etc")


def test_example_research_machine_loads():
    # Integration with the real workspace phases.yaml shipped in Merge 2.
    m = load_phase_machine_for_slug(REPO_ROOT, "example-research")
    assert m.initial_phase == "exploration"
    assert "adversarial-challenge" in m.phase_names
    assert m.allows_transition("exploration", "adversarial-challenge")
    assert not m.allows_transition("exploration", "synthesis")
    assert m.is_terminal("publication")
