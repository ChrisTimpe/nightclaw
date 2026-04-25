"""nightclaw_engine.commands.longrunner — LONGRUNNER extract/render/validate.

Three commands that bridge the Tier-C per-project phase state machine
with the human-readable LONGRUNNER markdown:

* ``longrunner-extract``   — pull routing fields without reading whole file
* ``longrunner-render``    — deterministic card render
* ``phase-validate``       — phase machine transition check
"""
from __future__ import annotations

import re
import sys

from . import _shared
from .validate import _load_gate_model


def cmd_longrunner_extract():
    """Extract routing-critical fields from a LONGRUNNER without requiring full file read.
    Usage: nightclaw-ops.py longrunner-extract <slug>
    Output: key=value pairs, one per line. LLM reads these instead of the full file.
    Only reads the full LONGRUNNER if T4 execution requires narrative context.
    """
    if len(sys.argv) < 3:
        print("ERROR: usage: longrunner-extract <slug>", file=sys.stderr)
        sys.exit(2)
    slug = sys.argv[2]

    fields = _shared.parse_longrunner(slug)
    if fields is None:
        print(f"ERROR: No LONGRUNNER found for slug={slug}")
        sys.exit(1)

    # Provide default for context_budget if not present
    if "next_pass.context_budget" not in fields:
        fields["next_pass.context_budget"] = "80K"  # default per spec

    # Determine routing decision
    status = fields.get("phase.status", "unknown").lower()
    objective = fields.get("next_pass.objective", "")

    if status == "complete":
        fields["routing"] = "COMPLETE"
    elif status == "blocked":
        fields["routing"] = "BLOCKED"
    elif not objective:
        fields["routing"] = "STALE_OBJECTIVE"
    elif status == "active":
        fields["routing"] = "ACTIVE"
    else:
        fields["routing"] = f"UNKNOWN_STATUS:{status}"

    # Output all fields
    for key, val in fields.items():
        print(f"{key}={val}")

def cmd_phase_validate():
    """Validate a phase transition against the project's phases.yaml.

    Usage: phase-validate <slug> <from_phase> <to_phase>
    Output: PHASE:OK  |  PHASE:DENIED:<code>:<detail>
    """
    from nightclaw_engine.schema.phases import load_phase_machine_for_slug
    if len(sys.argv) < 5:
        print("ERROR:USAGE: phase-validate <slug> <from_phase> <to_phase>", file=sys.stderr)
        sys.exit(2)
    slug = sys.argv[2]
    src = sys.argv[3]
    dst = sys.argv[4]
    machine_path = _shared.ROOT / "PROJECTS" / slug / "phases.yaml"
    if not machine_path.exists():
        print(f"PHASE:DENIED:MACHINE_MISSING:PROJECTS/{slug}/phases.yaml")
        sys.exit(1)
    try:
        machine = load_phase_machine_for_slug(_shared.ROOT, slug)
    except Exception as exc:
        print(f"PHASE:DENIED:MACHINE_INVALID:{exc}")
        sys.exit(1)
    if machine.get(src) is None:
        print(f"PHASE:DENIED:UNKNOWN_SOURCE:{src}")
        sys.exit(1)
    if machine.get(dst) is None:
        print(f"PHASE:DENIED:UNKNOWN_TARGET:{dst}")
        sys.exit(1)
    if not machine.allows_transition(src, dst):
        print(f"PHASE:DENIED:NOT_DECLARED:{src}->{dst}")
        sys.exit(1)
    print("PHASE:OK")

def cmd_longrunner_render():
    """Render LONGRUNNER.md for a project from its phases.yaml.

    Usage: longrunner-render <slug>
    Output: LONGRUNNER:OK:<path>:BYTES=<n>  |  LONGRUNNER:ERROR:<msg>
    """
    from nightclaw_engine.schema.phases import load_phase_machine_for_slug
    from nightclaw_engine.engine.longrunner import render_longrunner_card
    if len(sys.argv) < 3:
        print("ERROR:USAGE: longrunner-render <slug>", file=sys.stderr)
        sys.exit(2)
    slug = sys.argv[2]
    # H-SEC-02: reject traversal / malformed slugs before touching the
    # filesystem. The slug is joined into PROJECTS/<slug>/ both for the
    # phases.yaml read and the LONGRUNNER.md write; any slug that slips
    # through would otherwise let argv escape the workspace. Matches the
    # defense added in commands.bundle_mutators.mutate_longrunner_field so
    # both LONGRUNNER write paths enforce the same contract.
    if not _shared.is_valid_slug(slug):
        print(f"LONGRUNNER:ERROR:INVALID_SLUG:{slug!r}")
        sys.exit(1)
    lr_path = _shared.ROOT / "PROJECTS" / slug / "LONGRUNNER.md"
    machine_path = _shared.ROOT / "PROJECTS" / slug / "phases.yaml"
    if not machine_path.exists():
        print(f"LONGRUNNER:ERROR:machine_missing:PROJECTS/{slug}/phases.yaml")
        sys.exit(1)
    try:
        machine = load_phase_machine_for_slug(_shared.ROOT, slug)
    except Exception as exc:
        print(f"LONGRUNNER:ERROR:{exc}")
        sys.exit(1)
    model = _load_gate_model()
    n = render_longrunner_card(lr_path, machine, model.fingerprint)
    print(f"LONGRUNNER:OK:PROJECTS/{slug}/LONGRUNNER.md:BYTES={n}")


__all__ = ["cmd_longrunner_extract", "cmd_phase_validate", "cmd_longrunner_render"]
