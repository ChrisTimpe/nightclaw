"""nightclaw_bridge.protocol -- opsstepevent payload contract."""
from __future__ import annotations
from typing import Any, Mapping

# G2 FIX: full NightClaw tier set, including T5/T7/T8/T9 and half-steps.
# Sourced from orchestration-os/CRON-WORKER-PROMPT.md and CRON-MANAGER-PROMPT.md.
# Worker tiers: T0, T1, T1.5, T2, T2.5, T2.7, T3, T3.5, T4, T5, T5.5, T6, T7, T7a-T7d, T8, T8.3, T8.5, T9
# Rejecting a valid tier here silently drops telemetry events that the bridge
# would otherwise broadcast to the monitor — which is how the gap hid.
ALLOWED_TIERS = {
    "T0", "T1", "T1.5", "T2", "T2.5", "T2.7", "T3", "T3.5", "T4",
    "T5", "T5.5", "T6", "T7", "T7a", "T7b", "T7c", "T7d",
    "T8", "T8.3", "T8.5", "T9",
}

def build_opsstepevent(*, run_id: str, tier: str, cmd: str, t_emitted: str,
                       slug: str | None = None, pid: int | None = None,
                       session: str | None = None, exit_code: int | None = None) -> dict:
    if not run_id: raise ValueError("run_id required")
    if not cmd: raise ValueError("cmd required")
    if tier not in ALLOWED_TIERS: raise ValueError(f"bad tier {tier!r}")
    if not t_emitted: raise ValueError("t_emitted required")
    p: dict = {"type":"opsstepevent","run_id":run_id,"tier":tier,"cmd":cmd,"t_emitted":t_emitted}
    if slug is not None: p["slug"]=slug
    if pid is not None: p["pid"]=pid
    if session is not None: p["session"]=session
    if exit_code is not None: p["exit_code"]=exit_code
    return p

def is_opsstepevent(p: Mapping[str, Any]) -> bool:
    try:
        return (p.get("type")=="opsstepevent"
                and bool(p.get("run_id")) and bool(p.get("cmd"))
                and p.get("tier") in ALLOWED_TIERS
                and bool(p.get("t_emitted")))
    except Exception:
        return False
