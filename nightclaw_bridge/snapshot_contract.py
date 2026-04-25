"""nightclaw_bridge.snapshot_contract -- sessionssnapshot payload validator."""
from __future__ import annotations
from typing import Any, Mapping

REQUIRED_TOP = {"type","snapshot","t_emitted"}

def build_sessionssnapshot_payload(snapshot: dict, t_emitted: str) -> dict:
    return {"type":"sessionssnapshot","snapshot": snapshot, "t_emitted": t_emitted}

def validate_sessionssnapshot_payload(p: Mapping[str, Any]) -> dict:
    if not isinstance(p, Mapping):
        raise ValueError("payload must be a mapping")
    missing = REQUIRED_TOP - set(p.keys())
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    if p.get("type") != "sessionssnapshot":
        raise ValueError("type must be sessionssnapshot")
    snap = p.get("snapshot")
    if not isinstance(snap, Mapping):
        raise ValueError("snapshot must be a mapping")
    if "sessions" not in snap or "ops_timeline" not in snap:
        raise ValueError("snapshot must contain sessions and ops_timeline")
    if not isinstance(snap["sessions"], Mapping) or not isinstance(snap["ops_timeline"], Mapping):
        raise ValueError("sessions/ops_timeline must be mappings")
    return dict(p)
