#!/usr/bin/env python3
"""
nightclaw-ops.py — Deterministic operations toolkit for NightClaw.
Replaces LLM reasoning with code for all structured checks.

Usage: python3 scripts/nightclaw-ops.py <command>  [options]
Run from workspace root.

Commands:
  integrity-check     T0/T1: SHA256 verification against manifest
  next-run-id         STARTUP.3: Compute next RUN-YYYYMMDD-NNN
  dispatch            T1: Select highest-priority dispatchable project
  scan-notifications  T1.5: Find actionable notification entries
  timing-check        T0-manager: Check if worker session is too recent
  crash-detect        T0-manager: Cross-ref SESSION-REGISTRY vs AUDIT-LOG
  transition-expiry   T2-manager: Check TRANSITION-HOLD expiry dates
  change-detect       T3-manager: Compare worker passes vs manager reviews
  audit-spine         T8: Validate T0→T4→T9 sequence per session
  audit-anomalies     T8: Scan AUDIT-LOG for anomaly patterns
  prune-candidates    T8.3: Identify NOTIFICATIONS entries eligible for pruning
  os-file-sizes       T8: Report OS compounding file line counts against bloat thresholds
  scr-verify          T8: R6 self-consistency rules (SCR-01 through SCR-08)
  dispatch-validate   Field contract validation (R2 enums, NOT EMPTY, FK)
  longrunner-extract  T2: Extract machine-parseable fields from LONGRUNNER
  idle-triage         T1.5: Determine first actionable idle cycle tier
  strategic-context   T3.5-manager: Pre-digest strategic context for idle manager
  t7-dedup            T7: Check if a signal is already documented in target file
  crash-context       T0: Retrieve context from a crashed session for recovery
  append              Append a single line to an APPEND-ONLY file (safe exec-based alternative to Edit tool)
  append-batch        Append multiple lines to an APPEND-ONLY file in one call (||| delimited)
  bundle-exec         Generic R5 transition executor (reads BUNDLE spec, resolves, validates, writes)
  validate-bundles    Parse all R5 bundles and verify syntax, ARG consistency, PROTECTED paths
  schema-render       Render Tier A YAML schema to REGISTRY.generated.md (parallel target, not canonical)
  schema-sync         Replace REGISTRY.md rendered-section bodies with generated content (idempotent)
  schema-lint         Load Tier A schema and verify REGISTRY.generated.md is byte-identical to a fresh render

Merge-2 gate-exposing commands (internal / gate-facing):
  validate-field      T6: Field-contract validation against Tier A schema (R2 enums, NOT EMPTY, FK)
  cascade-read        T6: Resolve a field value through REGISTRY cascade rules
  registry-route      T6: Return the R3 routing row for a given file path
  lock-acquire        T0: Acquire LOCK.md (status=locked, all 6 fields) — usage: lock-acquire <holder> <run_id> <expires_at_iso8601z>
  lock-release        T9: Release LOCK.md (status=released, all 6 fields reset)
  longrunner-render   T6: Render LONGRUNNER.md from phase/task data
  phase-validate      T6: Validate a phase transition against schema rules
  bootstrap           T0: LLM bootstrap projection — emit onboarding context for new LLM sessions

All output is machine-parseable. LLM reads output and acts on it.
LLM never does the computation itself.
"""
# ----------------------------------------------------------------------------
# Thin CLI dispatcher. All command logic lives in nightclaw_engine.commands.
# Pass 6 of the deterministic-first revamp split the legacy monolith into
# nine domain modules plus commands/_shared. This script stays a one-liner
# so the entry point is stable across future re-organisations.
# ----------------------------------------------------------------------------

import os
import sys
import time

# Make the repo root importable so `nightclaw_engine` resolves regardless of
# how this script is invoked.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Optional ``--run-id=RUN-YYYYMMDD-NNN`` flag — must appear as the FIRST
# argument (before the command name) so the engine dispatcher never sees it.
# This lets the cron worker LLM propagate its registry-backed run_id into
# every nightclaw-ops.py subprocess invocation without relying on env-var
# inheritance (which doesn't work across independent OpenClaw tool calls).
#
# Usage:  python3 scripts/nightclaw-ops.py --run-id=RUN-20260423-001 append ...
# Usage:  python3 scripts/nightclaw-ops.py --run-id RUN-20260423-001 append ...
#
# The flag is stripped from sys.argv so the command dispatcher is unaffected.
if len(sys.argv) > 1 and sys.argv[1].startswith("--run-id"):
    if "=" in sys.argv[1]:
        _explicit_run_id = sys.argv[1].split("=", 1)[1].strip()
        sys.argv.pop(1)
    elif len(sys.argv) > 2:
        _explicit_run_id = sys.argv[2].strip()
        sys.argv.pop(1)
        sys.argv.pop(1)
    else:
        _explicit_run_id = ""
    if _explicit_run_id:
        os.environ["NIGHTCLAW_RUN_ID"] = _explicit_run_id

# Ensure a per-invocation ``NIGHTCLAW_RUN_ID`` so downstream telemetry
# (nightclaw_ops.telemetry, nightclaw_ops.lifecycle) can correlate events
# emitted in the same CLI run. Callers that set the env var themselves
# (tests, bootstrap scripts, the cron worker) keep control — this only
# fills the gap when nothing else has. Ephemeral; not persisted.
# Format deliberately distinct from the registry-backed ``RUN-YYYYMMDD-NNN``
# allocated by the ``next-run-id`` command so the two cannot collide.
if not os.environ.get("NIGHTCLAW_RUN_ID"):
    os.environ["NIGHTCLAW_RUN_ID"] = f"CLI-{int(time.time() * 1000)}-{os.getpid()}"

import nightclaw_engine  # noqa: E402
from nightclaw_engine import commands as _engine_commands  # noqa: E402

# Re-export the CLI docstring onto the commands package so `--help` output
# stays byte-identical to the pre-refactor version. The commands.main()
# helper reads ``commands.__doc__`` at help-print time. The previous form
# reached through the Pass-6 ``_legacy`` shim; Pass 8 wires the attribute
# directly to the canonical home to retire that shim.
_engine_commands.__doc__ = __doc__


def main() -> None:
    """Delegate to the engine's CLI entry point."""
    nightclaw_engine.main()


if __name__ == "__main__":
    main()
