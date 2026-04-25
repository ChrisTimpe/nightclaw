"""nightclaw_monitor.selectors -- pure read-side helpers."""
from __future__ import annotations
from typing import Mapping, Any

def timeline_for_run(snapshot: Mapping[str, Any], run_id: str) -> list[dict]:
    return list(snapshot.get("ops_timeline", {}).get(run_id, []))

def open_steps(snapshot: Mapping[str, Any]) -> list[dict]:
    out = []
    for run, steps in snapshot.get("ops_timeline", {}).items():
        for s in steps:
            if "exit_code" not in s:
                out.append({"run_id": run, **s})
    return out

def runs_index(snapshot: Mapping[str, Any]) -> list[str]:
    return sorted(set(snapshot.get("ops_timeline", {}).keys())
                  | set(snapshot.get("sessions", {}).keys()))
