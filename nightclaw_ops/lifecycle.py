"""nightclaw_ops.lifecycle -- CLI lifecycle telemetry insertion points.

Thin, exception-safe wrappers to be called at the boundaries of
scripts/nightclaw-ops.py (start/end of a tier step). Never raises.
"""
from __future__ import annotations
import contextlib, os
from typing import Iterator, Optional
from . import telemetry

@contextlib.contextmanager
def step(tier: str, cmd: str, *, slug: Optional[str] = None,
         session: Optional[str] = None, run_id: Optional[str] = None) -> Iterator[None]:
    rid = run_id or os.environ.get("NIGHTCLAW_RUN_ID", "UNKNOWN")
    try:
        telemetry.emit_step(tier, cmd=cmd, slug=slug, session=session, run_id=rid)
    except Exception:
        pass
    exit_code = 0
    try:
        yield
    except SystemExit as se:
        # ``sys.exit(N)`` is the documented exit path for CLI commands; preserve
        # the exact code (0 for success, non-zero for failure). Re-raise so the
        # process actually exits with that status.
        try:
            exit_code = int(se.code) if se.code is not None else 0
        except (TypeError, ValueError):
            exit_code = 1
        raise
    except BaseException:
        # Any other unhandled exception is a failure.
        exit_code = 1
        raise
    finally:
        try:
            telemetry.emit_step(tier, cmd=cmd, slug=slug, session=session,
                                run_id=rid, exit_code=exit_code)
        except Exception:
            pass

def mark(tier: str, cmd: str, *, exit_code: int = 0, **kw) -> None:
    try:
        telemetry.emit_step(tier, cmd=cmd, exit_code=exit_code, **kw)
    except Exception:
        pass
