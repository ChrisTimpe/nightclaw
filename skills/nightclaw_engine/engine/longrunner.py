"""nightclaw_engine.engine.longrunner — LONGRUNNER.md phase-card renderer.

Merge-2 scope: insert / refresh a **rendered phase-machine card** inside a
LONGRUNNER.md between the markers::

    <!-- nightclaw:phase-machine schema_fingerprint=<sha256> -->
    ...rendered card...
    <!-- /nightclaw:phase-machine -->

The rest of LONGRUNNER.md — mission, last_pass, next_pass, decision log,
phase history — stays hand-authored. The card is deterministic: same
``phases.yaml`` + same current phase name -> same bytes.

If the markers don't exist the card is appended at end of file. If they do
exist, the block between them is replaced. The surrounding file content is
preserved byte-for-byte outside the block.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

from ..schema.phases import PhaseMachine


CARD_HEADER = "<!-- nightclaw:phase-machine"
CARD_FOOTER = "<!-- /nightclaw:phase-machine -->"

_PHASE_NAME_RE = re.compile(
    r"^\s*name:\s*[\"']?([A-Za-z0-9_\-]+)[\"']?\s*$",
    re.MULTILINE,
)


def _render_card(machine: PhaseMachine, current_phase: str, fingerprint: str) -> str:
    """Render the rendered-card block body (between the markers)."""
    lines = [
        f"{CARD_HEADER} schema_fingerprint={fingerprint} -->",
        "",
        f"### Phase Machine: `{machine.slug}`",
        "",
        f"- **Current phase:** `{current_phase}`",
        f"- **Initial phase:** `{machine.initial_phase}`",
        f"- **Total phases:** {len(machine.phases)}",
        "",
        "| Phase | Objective | Stop condition | Allowed tools | Successors |",
        "|---|---|---|---|---|",
    ]
    for p in machine.phases:
        marker = " \u2190" if p.name == current_phase else ""
        tools = ", ".join(f"`{t}`" for t in p.allowed_tools) or "\u2014"
        succs = ", ".join(f"`{s}`" for s in p.successors) or "\u2014 (terminal)"
        # Collapse whitespace and escape pipes to keep the table readable.
        obj = p.objective.strip().replace("\n", " ").replace("|", "\\|")
        stop = p.stop_condition.strip().replace("\n", " ").replace("|", "\\|") or "\u2014"
        lines.append(
            f"| `{p.name}`{marker} | {obj} | {stop} | {tools} | {succs} |"
        )
    lines.append("")
    lines.append(CARD_FOOTER)
    return "\n".join(lines) + "\n"


def extract_current_phase_name(longrunner_body: str) -> Optional[str]:
    """Read the current phase name from a hand-authored ``## Current Phase`` YAML block.

    Looks for the first ``name: <value>`` inside a code-fenced block that
    follows a ``## Current Phase`` header. Returns None if not found.
    """
    # Locate the Current Phase section body (up to next H2).
    m = re.search(
        r"##\s+Current Phase\s*\n(.*?)(?=\n##\s+|\Z)",
        longrunner_body,
        re.DOTALL,
    )
    if not m:
        return None
    section = m.group(1)
    name_match = _PHASE_NAME_RE.search(section)
    if not name_match:
        return None
    return name_match.group(1).strip()


def render_longrunner_card(
    longrunner_path: Path,
    machine: PhaseMachine,
    schema_fingerprint: str,
) -> Tuple[str, str]:
    """Regenerate the rendered card for a given LONGRUNNER.md.

    Returns a (new_body, current_phase_name) tuple. Raises ``FileNotFoundError``
    if the target file is missing.
    """
    if not longrunner_path.exists():
        raise FileNotFoundError(longrunner_path)
    body = longrunner_path.read_text(encoding="utf-8")

    current = extract_current_phase_name(body) or machine.initial_phase
    card = _render_card(machine, current, schema_fingerprint)

    # Replace-or-append the block.
    pattern = re.compile(
        re.escape(CARD_HEADER) + r".*?" + re.escape(CARD_FOOTER) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(body):
        new_body = pattern.sub(card, body)
    else:
        # Append with a separating blank line if file doesn't end with one.
        if not body.endswith("\n"):
            body += "\n"
        if not body.endswith("\n\n"):
            body += "\n"
        new_body = body + card

    return new_body, current


__all__ = [
    "CARD_FOOTER",
    "CARD_HEADER",
    "extract_current_phase_name",
    "render_longrunner_card",
]
