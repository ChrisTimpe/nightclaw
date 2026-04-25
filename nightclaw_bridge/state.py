"""nightclaw_bridge.state -- deterministic fold over event log."""
from __future__ import annotations
from typing import Iterable, Mapping, Any

def fold_eventlog(events: Iterable[Mapping[str, Any]]) -> dict:
    snapshot: dict = {"sessions": {}, "ops_timeline": {}}
    # Track (run_id, cmd) open steps so a second event with exit_code closes them.
    open_steps: dict[tuple, dict] = {}
    for ev in events:
        t = ev.get("type")
        run = ev.get("run_id")
        if not run:
            continue
        if t == "sessionsevent":
            s = snapshot["sessions"].setdefault(run, {"kinds": []})
            s["kinds"].append(ev.get("kind"))
        elif t == "opsstepevent":
            tl = snapshot["ops_timeline"].setdefault(run, [])
            key = (run, ev.get("cmd"), ev.get("slug"))
            if key in open_steps and "exit_code" in ev and "exit_code" not in open_steps[key]:
                open_steps[key]["exit_code"] = ev["exit_code"]
                continue
            step = {k:v for k,v in ev.items() if k != "type"}
            tl.append(step)
            if "exit_code" not in ev:
                open_steps[key] = step
            else:
                # already-completed step; do not re-open
                pass
    return snapshot
