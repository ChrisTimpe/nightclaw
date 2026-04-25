#!/usr/bin/env python3
"""
skills/nightclaw-ops.py — deterministic re-export of scripts/nightclaw-ops.py.

G4 FIX: this directory historically held drift-prone duplicates of ``scripts/``.
As part of the deterministic-first engine revamp we collapse the duplicate
surface to a single source of truth at ``scripts/nightclaw-ops.py``. This file
exists only so that any lingering ``skills/nightclaw-ops.py`` invocation keeps
working; it simply forwards to the canonical script.

To distribute the real implementation into ``skills/`` for packaging, run:

    python3 scripts/skills-sync.py

That script copies ``scripts/nightclaw-ops.py`` and the ``nightclaw_engine``
package tree into ``skills/`` verbatim. Never hand-edit files under
``skills/``; the canonical source lives in ``scripts/`` and
``nightclaw_engine/``.
"""
from __future__ import annotations

import os
import runpy
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_CANONICAL = os.path.join(_REPO_ROOT, "scripts", "nightclaw-ops.py")


def main() -> None:
    if not os.path.isfile(_CANONICAL):
        sys.stderr.write(
            f"ERROR: canonical script missing at {_CANONICAL}. "
            "skills/nightclaw-ops.py is only a forwarder; the real "
            "implementation lives under scripts/ and nightclaw_engine/.\n"
        )
        sys.exit(2)
    # Make the repo root importable so `nightclaw_engine` resolves.
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    # Execute the canonical script in-process. runpy preserves argv and exit
    # semantics, so callers see identical behaviour.
    runpy.run_path(_CANONICAL, run_name="__main__")


if __name__ == "__main__":
    main()
