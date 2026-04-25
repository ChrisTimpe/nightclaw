"""tests/core/test_schema_render.py — Tier A -> REGISTRY.generated.md renderer.

Verifies the Merge-1 renderer (``nightclaw_engine.engine.render``) produces:
  * a byte-stable output for a fixed schema input (determinism);
  * the render-header / footer markers used by ``schema-lint``;
  * the seven canonical REGISTRY sections driven by YAML.

No canonical REGISTRY.md file is touched by any test here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightclaw_engine.schema import loader as schema_loader
from nightclaw_engine.engine import render as engine_render
from nightclaw_engine.engine.render import (
    RENDER_FOOTER_MARK,
    RENDER_HEADER_MARK,
    iter_rendered_section_titles,
    render_markdown,
)


SCHEMA_DIR = REPO_ROOT / "orchestration-os" / "schema"


@pytest.fixture(autouse=True)
def _clean_cache():
    schema_loader.invalidate()
    yield
    schema_loader.invalidate()


# --- Determinism ------------------------------------------------------------


def test_render_markdown_is_byte_stable():
    model = schema_loader.load(SCHEMA_DIR)
    first = render_markdown(model)
    second = render_markdown(model)
    assert first == second, "render_markdown must be byte-identical for identical input"


def test_render_markdown_stable_across_cache_invalidation():
    model_a = schema_loader.load(SCHEMA_DIR)
    first = render_markdown(model_a)
    schema_loader.invalidate()
    model_b = schema_loader.load(SCHEMA_DIR)
    second = render_markdown(model_b)
    # Cache reset must not perturb output for identical file contents.
    assert first == second
    assert model_a.fingerprint == model_b.fingerprint


# --- Header / footer contract ----------------------------------------------


def test_render_output_wrapped_with_header_and_footer():
    model = schema_loader.load(SCHEMA_DIR)
    body = render_markdown(model)
    assert RENDER_HEADER_MARK in body, "header marker must be present"
    assert body.rstrip().endswith(RENDER_FOOTER_MARK), "footer marker must close the render"


def test_render_header_embeds_schema_fingerprint():
    model = schema_loader.load(SCHEMA_DIR)
    body = render_markdown(model)
    # Header signature format documented in render.py:
    #   <!-- nightclaw:render schema_fingerprint=<sha256> -->
    assert f"schema_fingerprint={model.fingerprint}" in body


# --- Section coverage -------------------------------------------------------


def test_iter_rendered_section_titles_returns_seven_titles():
    model = schema_loader.load(SCHEMA_DIR)
    titles = list(iter_rendered_section_titles(model))
    assert len(titles) == 7


def test_all_section_titles_present_in_rendered_body():
    model = schema_loader.load(SCHEMA_DIR)
    body = render_markdown(model)
    for title in iter_rendered_section_titles(model):
        assert title in body, f"rendered body missing section: {title}"


# --- Content sanity ---------------------------------------------------------


def test_render_contains_every_bundle_name():
    model = schema_loader.load(SCHEMA_DIR)
    body = render_markdown(model)
    for b in model.bundles:
        assert b.name in body, f"rendered body missing bundle: {b.name}"


def test_render_contains_every_scr_id():
    model = schema_loader.load(SCHEMA_DIR)
    body = render_markdown(model)
    for r in model.scr_rules:
        assert r.id in body, f"rendered body missing SCR rule: {r.id}"


def test_render_contains_every_protected_path():
    model = schema_loader.load(SCHEMA_DIR)
    body = render_markdown(model)
    for p in model.protected_paths:
        assert p in body, f"rendered body missing protected path: {p}"


def test_render_output_has_no_timestamp_like_strings():
    """Render must not embed wall-clock strings in the body, else lint becomes unstable."""
    model = schema_loader.load(SCHEMA_DIR)
    body = render_markdown(model)
    # Simple heuristic: no ISO-8601 date substrings like 2020- through 2099-.
    import re

    iso_like = re.findall(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}", body)
    assert not iso_like, f"found timestamps in rendered body: {iso_like[:3]}"
