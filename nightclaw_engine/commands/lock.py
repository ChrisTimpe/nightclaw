"""nightclaw_engine.commands.lock — session lock + run-id allocation.

Three commands that coordinate session lifecycle:

* ``next-run-id``    STARTUP.3: compute next ``RUN-YYYYMMDD-NNN`` id.
* ``lock-acquire``   T0: structurally acquire ``LOCK.md`` with status=locked.
* ``lock-release``   T9: structurally release ``LOCK.md`` on session close.

Bodies migrated from ``_legacy.py`` (Pass 6); lock-acquire and lock-release
rewritten in the adversarial-audit remediation pass to write the full
operational LOCK.md schema (status=locked, all six fields) so they are
byte-compatible with ``scripts/check-lock.py`` and the cron prompt protocol.
"""
from __future__ import annotations

import re
import sys

from . import _shared


def cmd_next_run_id():
    """Compute next RUN-YYYYMMDD-NNN from SESSION-REGISTRY.
    Output: RUN-YYYYMMDD-NNN
    """
    session_arg = sys.argv[3] if len(sys.argv) > 3 else None
    content = _shared.read_file("audit/SESSION-REGISTRY.md")
    if content is None:
        # First run ever
        today = _shared.now_utc().strftime("%Y%m%d")
        print(f"RUN-{today}-001")
        return

    today = _shared.now_utc().strftime("%Y%m%d")
    # Count entries with today's date
    pattern = re.compile(rf'RUN-{today}-(\d{{3}})')
    max_n = 0
    for m in pattern.finditer(content):
        n = int(m.group(1))
        if n > max_n:
            max_n = n

    next_n = max_n + 1
    print(f"RUN-{today}-{next_n:03d}")


def cmd_lock_acquire():
    """Acquire LOCK.md structurally. Writes the full operational schema (status=locked).

    Usage: lock-acquire <holder> <run_id> <expires_at_iso8601z>
    Output: LOCK:ACQUIRED holder=... run_id=... locked_at=...
            LOCK:DENIED reason=already_locked

    Writes all six fields required by check-lock.py and the operational
    lock protocol: status=locked, holder, run_id, locked_at (auto-set to
    now), expires_at, consecutive_pass_failures (preserved from prior file).
    Denies if the existing lock is status=locked with a future expires_at
    (active lock). Treats unparseable or past expiry as stale and overwrites.
    """
    if len(sys.argv) < 5:
        print("ERROR:USAGE: lock-acquire <holder> <run_id> <expires_at_iso8601z>",
              file=sys.stderr)
        sys.exit(2)
    holder = sys.argv[2]
    run_id = sys.argv[3]
    expires_at = sys.argv[4]
    lock_path = _shared.ROOT / "LOCK.md"

    from datetime import datetime, timezone

    # Read existing file: check for an active lock and preserve cpf.
    cpf = 0
    if lock_path.exists():
        existing = lock_path.read_text(encoding="utf-8", errors="replace")
        is_locked = "status: locked" in existing or "status:locked" in existing
        if is_locked:
            # Deny only if expires_at is parseable and still in the future.
            exp_m = re.search(r'expires_at:\s*(\S+)', existing)
            if exp_m:
                try:
                    exp_dt = datetime.fromisoformat(
                        exp_m.group(1).replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) < exp_dt:
                        print("LOCK:DENIED reason=already_locked")
                        sys.exit(1)
                except ValueError:
                    pass  # unparseable expiry — treat as stale, allow overwrite
        # Preserve crash-loop counter regardless of current status.
        cpf_m = re.search(r'consecutive_pass_failures:\s*(\d+)', existing)
        if cpf_m:
            try:
                cpf = int(cpf_m.group(1))
            except ValueError:
                cpf = 0

    locked_at = _shared.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    body = (
        "# LOCK\n\n"
        "```yaml\n"
        f"status: locked\n"
        f"holder: {holder}\n"
        f"run_id: {run_id}\n"
        f"locked_at: {locked_at}\n"
        f"expires_at: {expires_at}\n"
        f"consecutive_pass_failures: {cpf}\n"
        "```\n"
    )
    lock_path.write_text(body, encoding="utf-8")
    print(f"LOCK:ACQUIRED holder={holder} run_id={run_id} locked_at={locked_at}")


def cmd_lock_release():
    """Release LOCK.md. Overwrites with the full released schema (status=released).

    Usage: lock-release [holder]
    Output: LOCK:RELEASED  |  LOCK:DENIED reason=not_held

    Writes all six fields so the file stays schema-complete after release.
    Resets consecutive_pass_failures to 0 (successful session close).
    Denies if the lock is already released (status != locked).
    """
    lock_path = _shared.ROOT / "LOCK.md"
    if not lock_path.exists():
        print("LOCK:DENIED reason=not_held")
        sys.exit(1)
    existing = lock_path.read_text(encoding="utf-8", errors="replace")
    is_locked = "status: locked" in existing or "status:locked" in existing
    if not is_locked:
        print("LOCK:DENIED reason=not_held")
        sys.exit(1)
    body = (
        "# LOCK\n\n"
        "```yaml\n"
        "status: released\n"
        "holder: \u2014\n"
        "run_id: \u2014\n"
        "locked_at: \u2014\n"
        "expires_at: \u2014\n"
        "consecutive_pass_failures: 0\n"
        "```\n"
    )
    lock_path.write_text(body, encoding="utf-8")
    print("LOCK:RELEASED")


__all__ = ["cmd_next_run_id", "cmd_lock_acquire", "cmd_lock_release"]
