"""nightclaw_engine — deterministic execution engine for NightClaw.

This package is the single source of truth for the NightClaw command
implementations. The ``scripts/nightclaw-ops.py`` file is a thin CLI
dispatcher that delegates every command to this package.

Package layering (post Pass 8 — thesis-aligned, shim-free):
    nightclaw_engine.commands  — authoritative home for every cmd_* function,
                                  split across nine domain modules + _shared.
    nightclaw_engine.schema    — YAML-backed schema loader + typed model
    nightclaw_engine.engine    — gates, bundle executor, changelog, audit
    nightclaw_engine.mutators  — per-object atomic writers
    nightclaw_engine.protocol  — SCR predicates + supporting checks
                                  (query the typed model directly; no prose regex)

The public import surface (``COMMANDS``, ``main``) stays stable across every
merge. Downstream code should import from the top-level package or
``nightclaw_engine.commands`` directly.
"""
from __future__ import annotations

from . import commands as _commands

# Public command table — same keys, same callables as the original script.
COMMANDS = _commands.COMMANDS

# Public entry point. Keeps sys.argv parsing identical to the script.
main = _commands.main

__all__ = ["COMMANDS", "main"]
