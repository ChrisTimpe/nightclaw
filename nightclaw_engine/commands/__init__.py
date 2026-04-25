"""nightclaw_engine.commands — deterministic command package.

This package is the authoritative home for every ``cmd_*`` function. It
replaces the monolithic ``_legacy.py`` (~3,094 LOC) with ten domain modules
plus one shared helper module:

* :mod:`.integrity`   — integrity-check
* :mod:`.lock`        — next-run-id, lock-acquire, lock-release
* :mod:`.append`      — append, append-batch
* :mod:`.validate`    — validate-field, registry-route, cascade-read,
                        strategic-context
* :mod:`.scr`         — scr-verify (thin driver; real logic in
                        :mod:`nightclaw_engine.protocol.integrity`)
* :mod:`.longrunner`  — longrunner-extract, longrunner-render, phase-validate
* :mod:`.dispatch`    — dispatch, dispatch-validate, scan-notifications,
                        idle-triage
* :mod:`.audit`       — audit-spine, audit-anomalies, crash-detect,
                        crash-context, prune-candidates, t7-dedup, os-file-sizes,
                        change-detect, timing-check, transition-expiry
* :mod:`.bundle`      — bundle-exec, validate-bundles, schema-render,
                        schema-lint
* :mod:`._shared`     — ROOT singleton, PROTECTED_PATHS, APPEND_ALLOWED,
                        YAML/LONGRUNNER parsers, time helpers, telemetry hook

The :data:`COMMANDS` mapping and :func:`main` entry point preserve byte-for-byte
identical CLI behaviour with the pre-Pass-6 ``_legacy.main``. The only
deliberate change is: ``ROOT`` is now an attribute of :mod:`._shared` rather
than a module global of ``_legacy``. The downstream import surface
(``nightclaw_engine.COMMANDS``, ``nightclaw_engine.main``) is unchanged.
"""
from __future__ import annotations

import os
import sys

from . import _shared
from ._shared import emit_step, lifecycle_step, workspace_root

# Import every command module. Each one registers its cmd_* callables against
# the COMMANDS mapping below. Import order is leaf-first so that if a future
# refactor creates inter-module dependencies, the leaves are already loaded.
from . import lock as _lock
from . import append as _append
from . import validate as _validate
from . import scr as _scr
from . import integrity as _integrity
from . import longrunner as _longrunner
from . import dispatch as _dispatch
from . import audit as _audit
from . import bundle as _bundle
from . import bootstrap as _bootstrap
from . import model_tier as _model_tier


# ---------------------------------------------------------------------------
# Command table — same keys, same callables as pre-Pass-6 _legacy.COMMANDS.
# Order is preserved to keep --help output deterministic.
# ---------------------------------------------------------------------------

COMMANDS = {
    "integrity-check":     _integrity.cmd_integrity_check,
    "next-run-id":         _lock.cmd_next_run_id,
    "dispatch":            _dispatch.cmd_dispatch,
    "scan-notifications":  _dispatch.cmd_scan_notifications,
    "timing-check":        _audit.cmd_timing_check,
    "crash-detect":        _audit.cmd_crash_detect,
    "transition-expiry":   _audit.cmd_transition_expiry,
    "change-detect":       _audit.cmd_change_detect,
    "audit-spine":         _audit.cmd_audit_spine,
    "audit-anomalies":     _audit.cmd_audit_anomalies,
    "prune-candidates":    _audit.cmd_prune_candidates,
    "os-file-sizes":       _audit.cmd_os_file_sizes,
    "scr-verify":          _scr.cmd_scr_verify,
    "dispatch-validate":   _dispatch.cmd_dispatch_validate,
    "longrunner-extract":  _longrunner.cmd_longrunner_extract,
    "idle-triage":         _dispatch.cmd_idle_triage,
    "strategic-context":   _validate.cmd_strategic_context,
    "t7-dedup":            _audit.cmd_t7_dedup,
    "crash-context":       _audit.cmd_crash_context,
    "append":              _append.cmd_append,
    "append-batch":        _append.cmd_append_batch,
    "bundle-exec":         _bundle.cmd_bundle_exec,
    "validate-bundles":    _bundle.cmd_validate_bundles,
    "schema-render":       _bundle.cmd_schema_render,
    "schema-sync":         _bundle.cmd_schema_sync,
    "schema-lint":         _bundle.cmd_schema_lint,
    # Merge-2 gate-exposing commands
    "validate-field":      _validate.cmd_validate_field,
    "cascade-read":        _validate.cmd_cascade_read,
    "registry-route":      _validate.cmd_registry_route,
    "lock-acquire":        _lock.cmd_lock_acquire,
    "lock-release":        _lock.cmd_lock_release,
    "phase-validate":      _longrunner.cmd_phase_validate,
    "longrunner-render":   _longrunner.cmd_longrunner_render,
    # Pass 10 — LLM bootstrap projection
    "bootstrap":           _bootstrap.cmd_bootstrap,
    # Pass 11 — Model tier switching
    "set-model-tier":      _model_tier.cmd_set_model_tier,
}


# Telemetry tier map — same content as pre-Pass-6 _legacy.main() inline dict.
# Hoisted to module scope so tests can import it directly.
STEP_CMD_MAP = {
    "integrity-check": "startup", "next-run-id": "startup",
    "dispatch": "T1", "scan-notifications": "T1", "idle-triage": "T1",
    "longrunner-extract": "T2", "transition-expiry": "T2", "dispatch-validate": "T2",
    "crash-detect": "T0", "crash-context": "T0", "timing-check": "T0",
    "change-detect": "T3", "strategic-context": "T3",
    "bundle-exec": "T6", "append": "T6", "append-batch": "T6",
    "audit-spine": "T8", "audit-anomalies": "T8", "scr-verify": "T8",
    "prune-candidates": "T8", "validate-bundles": "T8", "os-file-sizes": "T8",
    "schema-render": "T8", "schema-sync": "T8", "schema-lint": "T8",
    "t7-dedup": "T7",
    # Merge-2 gate-exposing commands
    "validate-field": "T6", "cascade-read": "T6", "registry-route": "T6",
    "lock-acquire": "T0", "lock-release": "T9",
    "phase-validate": "T6", "longrunner-render": "T6",
    # Pass 10
    "bootstrap": "T0",
    # Pass 11
    "set-model-tier": "T9",
}


def main():
    """CLI entry point. Byte-identical dispatch behaviour to pre-Pass-6 _legacy.main."""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        # The CLI docstring is attached to this module at program start by the
        # nightclaw-ops.py shim (``_engine_commands.__doc__ = __doc__``). Pass 8
        # retires the ``_legacy`` indirection: this module is the canonical
        # home of the dispatcher, so it is also the canonical carrier of the
        # help text.
        import nightclaw_engine.commands as _doc_source
        print(_doc_source.__doc__)
        print("Commands:")
        for name, fn in COMMANDS.items():
            desc = (fn.__doc__ or "").strip().split("\n")[0]
            print(f"  {name:24s} {desc}")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(f"Available: {', '.join(COMMANDS.keys())}", file=sys.stderr)
        sys.exit(2)

    # Bind workspace root once, on the shared singleton, before dispatching.
    # Every migrated cmd_* function reads ``_shared.ROOT`` at call time, so
    # this single assignment is sufficient. Pass 8 retired the ``_legacy``
    # shim; the only canonical source of ROOT is now ``_shared.ROOT``.
    _shared.ROOT = workspace_root()

    # Telemetry — wrap dispatch in the lifecycle context manager so both the
    # enter event and the paired exit event (with exit_code) reach the bridge.
    # Transparent to commands: if the bridge is not running, all emissions are
    # silent no-ops. ``SystemExit`` is preserved so CLI exit codes still flow.
    # BUG-12: pass NIGHTCLAW_SESSION env var through to lifecycle_step so the
    # bridge receives the correct agent_type (worker/manager) on every step
    # event instead of always falling back to the 'worker' default.
    _session_tag = os.environ.get("NIGHTCLAW_SESSION") or None
    with lifecycle_step(STEP_CMD_MAP.get(cmd, "T4"), cmd, session=_session_tag):
        COMMANDS[cmd]()


__all__ = ["COMMANDS", "STEP_CMD_MAP", "main"]
