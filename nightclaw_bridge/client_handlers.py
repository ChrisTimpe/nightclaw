"""nightclaw_bridge.client_handlers -- client-side handlers."""
from __future__ import annotations
from typing import Any, Mapping

class _Store:
    def __init__(self) -> None:
        self.state: dict = {"ops_timeline": {}, "sessions": {}}
        self.notifications: int = 0
    def notify(self) -> None:
        self.notifications += 1

def on_opsstepevent(store: _Store, payload: Mapping[str, Any]) -> None:
    run = payload.get("run_id")
    if not run:
        return
    tl = store.state.setdefault("ops_timeline", {}).setdefault(run, [])
    if "exit_code" in payload:
        for step in reversed(tl):
            if step.get("cmd")==payload.get("cmd") and step.get("slug")==payload.get("slug") and "exit_code" not in step:
                step["exit_code"] = payload["exit_code"]
                store.notify()
                return
    tl.append({k:v for k,v in payload.items() if k != "type"})
    store.notify()
