"""tests/core/test_schema_sync.py — Pass-7 F9 byte-equality invariant.

Verifies that the bodies of the rendered sections inside
``orchestration-os/REGISTRY.md`` are byte-identical to the canonical bodies
produced by ``nightclaw_engine.commands.bundle._generated_section_bodies``.

This is the living invariant that enforces "schema drives doctrine" — any
change to ``orchestration-os/schema/*.yaml`` that is not propagated via
``schema-sync`` will fail CI.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.commands import bundle as cmd_bundle
from nightclaw_engine.schema.loader import load as load_schema


REGISTRY_PATH = REPO_ROOT / "orchestration-os" / "REGISTRY.md"
SECTION_IDS = ("R1", "R2", "R3", "R4", "R5", "R6", "CL5")


@pytest.fixture(scope="module")
def model():
    return load_schema(REPO_ROOT / "orchestration-os" / "schema")


@pytest.fixture(scope="module")
def registry_text():
    return REGISTRY_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def generated_bodies(model):
    return cmd_bundle._generated_section_bodies(model)


def _extract_body(text: str, sid: str) -> str:
    open_re = re.compile(cmd_bundle._MARKER_OPEN_RE_FMT.format(sid=sid))
    m = open_re.search(text)
    assert m is not None, f"open marker for section {sid} not found in REGISTRY.md"
    after_open = m.end()
    close_idx = text.find(cmd_bundle._MARKER_CLOSE, after_open)
    assert close_idx != -1, f"close marker for section {sid} not found after open"
    return text[after_open:close_idx]


@pytest.mark.parametrize("sid", SECTION_IDS)
def test_registry_sections_byte_equal_generated(sid, registry_text, generated_bodies):
    """The body between each section's render markers must equal the generated body."""
    in_registry = _extract_body(registry_text, sid)
    expected = generated_bodies[sid]
    assert in_registry == expected, (
        f"REGISTRY.md section {sid} body diverges from generated render.\n"
        f"Run: python3 scripts/nightclaw-ops.py schema-sync"
    )


def test_generated_section_ids_complete(generated_bodies):
    """Renderer covers exactly the expected 7 sections."""
    assert set(generated_bodies.keys()) == set(SECTION_IDS)


def test_schema_sync_is_idempotent(tmp_path, model):
    """Calling schema-sync twice in a row yields NOOP the second time.

    We exercise the splice logic directly rather than invoking the CLI, so the
    test does not mutate the working REGISTRY.md file.
    """
    # Copy the current registry to a tmp file and splice the same generated
    # bodies twice; the result must match the first splice.
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    bodies = cmd_bundle._generated_section_bodies(model)

    once = text
    for sid in SECTION_IDS:
        once, _, _ = cmd_bundle._splice_section(once, sid, bodies[sid])

    twice = once
    for sid in SECTION_IDS:
        twice, _, _ = cmd_bundle._splice_section(twice, sid, bodies[sid])

    assert once == twice, "schema-sync must be idempotent"


def test_schema_sync_noop_when_in_sync():
    """After schema-sync runs, immediate re-splice of the on-disk registry is a no-op."""
    from nightclaw_engine.schema.loader import load as _load
    m = _load(REPO_ROOT / "orchestration-os" / "schema")
    bodies = cmd_bundle._generated_section_bodies(m)
    text = REGISTRY_PATH.read_text(encoding="utf-8")

    new_text = text
    for sid in SECTION_IDS:
        new_text, _, _ = cmd_bundle._splice_section(new_text, sid, bodies[sid])

    assert new_text == text, (
        "REGISTRY.md is not byte-synced with schema render. "
        "Run: python3 scripts/nightclaw-ops.py schema-sync"
    )
