"""nightclaw_engine.protocol — typed command modules.

Merge-2 surface:
    integrity  — SCR predicate registry and run_scr_verify driver.

Future merges will move the remaining cmd_* functions out of ``_legacy`` into
dedicated modules here (dispatch, notifications, triage, detect, audit_ops,
longrunner, strategy, runs, dedup, crash, phase).
"""
from __future__ import annotations

from . import integrity

__all__ = ["integrity"]
