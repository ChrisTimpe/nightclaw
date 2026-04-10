#!/usr/bin/env python3
"""
NightClaw lock check script.
Run from workspace root: python3 scripts/check-lock.py [session-name]
Outputs: PROCEED or DEFER:[reason]
Exit 0 = PROCEED, Exit 1 = DEFER
"""
import sys
import re
import pathlib
from datetime import datetime, timezone

LOCK_FILE = pathlib.Path("LOCK.md")
SESSION = sys.argv[1] if len(sys.argv) > 1 else "unknown"
STALE_MINUTES = 25  # orphan guard — locks older than this are always stale

def parse_lock():
    if not LOCK_FILE.exists():
        return {"status": "released"}
    content = LOCK_FILE.read_text()
    fields = {}
    for line in content.splitlines():
        m = re.match(r'^(\w+):\s*(.+)', line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields

def is_stale(lock):
    status = lock.get("status", "released")
    if status != "locked":
        return True  # released = free

    # Crash-partial safety: any required field missing or sentinel value → treat as stale
    _SENTINEL = ("", "—", "-", "~", "null", "None", "none")
    required_fields = ["expires_at", "locked_at", "run_id", "holder"]
    for field in required_fields:
        val = lock.get(field, "")
        if not val or val.strip() in _SENTINEL:
            return True  # crash-partial = stale

    now = datetime.now(timezone.utc)
    
    # Missing or em-dash timestamps = unknown state = treat as stale (fail-safe)
    expires_at = lock.get("expires_at", "—")
    locked_at = lock.get("locked_at", "—")
    if not expires_at or expires_at == "—":
        return True
    if not locked_at or locked_at == "—":
        return True
    
    # Check expires_at
    try:
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if now > exp_dt:
            return True  # expired
    except ValueError:
        return True  # unparseable = treat as stale
    
    # Orphan guard: locked_at > STALE_MINUTES ago
    try:
        lock_dt = datetime.fromisoformat(locked_at.replace("Z", "+00:00"))
        age_seconds = (now - lock_dt).total_seconds()
        if age_seconds > STALE_MINUTES * 60:
            return True  # orphaned
    except ValueError:
        return True  # unparseable = treat as stale
    
    return False  # lock is active

def main():
    lock = parse_lock()
    status = lock.get("status", "released")
    
    if status == "released" or is_stale(lock):
        # Free to proceed
        holder = lock.get("holder", "—")
        run_id = lock.get("run_id", "—")
        stale_info = ""
        if status == "locked":
            stale_info = f":STALE_HOLDER={holder}:STALE_RUN={run_id}"
        print(f"PROCEED{stale_info}")
        sys.exit(0)
    else:
        # Lock is active
        holder = lock.get("holder", "unknown")
        expires = lock.get("expires_at", "unknown")
        run_id = lock.get("run_id", "unknown")
        print(f"DEFER:holder={holder}:run_id={run_id}:expires={expires}")
        sys.exit(1)

if __name__ == "__main__":
    main()
