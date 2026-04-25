"""Gate that every shipped apps/monitor/*.html file contains JS that
parses without a SyntaxError.

This gate exists because a past pass left escaped backticks (`\\``) inside
real template-literal expressions in nightclaw-monitor.html. The file
itself was valid HTML and no Python test caught it; the break only
surfaced when a browser loaded the page and hit:

    Uncaught SyntaxError: Invalid or unexpected token

Every other truthful surface added by the monitor-completion work is
reachable only after the page's JS runs — so a JS parse break silently
defeats the entire monitor UX.

Implementation: extract each ``<script>...</script>`` block verbatim and
pipe it through ``node --check``. If node is not on PATH (some CI
images) the gate skips with a reason so it does not become a false
negative.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MONITOR_DIR = REPO_ROOT / "apps" / "monitor"

_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE
)


def _html_files() -> list[Path]:
    return sorted(MONITOR_DIR.glob("*.html"))


@pytest.mark.parametrize("html_path", _html_files(), ids=lambda p: p.name)
def test_monitor_html_script_blocks_parse(html_path: Path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; cannot syntax-check inline JS")

    text = html_path.read_text(encoding="utf-8")
    blocks = _SCRIPT_RE.findall(text)
    if not blocks:
        pytest.skip(f"no <script> blocks in {html_path.name}")

    for idx, block in enumerate(blocks):
        # Skip blocks with a src= attribute — those are external refs,
        # not inline source. Our regex only captures the body, but an
        # empty body still means nothing to parse.
        if not block.strip():
            continue
        proc = subprocess.run(
            [node, "--check", "-"],
            input=block,
            text=True,
            capture_output=True,
            timeout=15,
        )
        assert proc.returncode == 0, (
            f"{html_path.name} script block #{idx} failed node --check:\n"
            f"{proc.stderr.strip()}"
        )
