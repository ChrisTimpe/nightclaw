"""nightclaw_monitor.handlers -- handler routing for bridge payloads."""
from __future__ import annotations
from typing import Callable, Dict, Mapping, Any

Handler = Callable[[Any, Mapping[str, Any]], None]

def _on_snapshot(store, payload): store.apply_sessionssnapshot(payload)
def _on_opsstep(store, payload):  store.apply_opsstepevent(payload)

DEFAULT_HANDLERS: Dict[str, Handler] = {
    "sessionssnapshot": _on_snapshot,
    "opsstepevent":     _on_opsstep,
}

class HandlerRouter:
    def __init__(self, store, handlers: Dict[str, Handler] | None = None) -> None:
        self.store = store
        self.handlers = dict(DEFAULT_HANDLERS)
        if handlers:
            self.handlers.update(handlers)

    def dispatch(self, payload: Mapping[str, Any]) -> bool:
        t = payload.get("type")
        fn = self.handlers.get(t)
        if fn is None:
            return False
        fn(self.store, payload)
        return True
