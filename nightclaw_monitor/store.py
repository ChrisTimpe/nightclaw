"""nightclaw_monitor.store -- snapshot-driven view store.

Round 9 introduces MonitorStore (snapshot/opsstep handlers that consume
validated bridge payloads). The legacy Store remains for back-compat with
older monitor HTML adapters that still pass the denormalized dict shape.
"""
from __future__ import annotations
import copy, threading
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from nightclaw_bridge.snapshot_contract import validate_sessionssnapshot_payload

# ------------------- Round 9: canonical monitor store -------------------
class MonitorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: dict = {"sessions": {}, "ops_timeline": {}}
        self._last_t_emitted: Optional[str] = None

    def apply_sessionssnapshot(self, payload: Mapping[str, Any]) -> None:
        validated = validate_sessionssnapshot_payload(payload)
        with self._lock:
            self._snapshot = dict(validated["snapshot"])
            self._last_t_emitted = validated["t_emitted"]

    def apply_opsstepevent(self, ev: Mapping[str, Any]) -> None:
        run = ev.get("run_id")
        if not run: return
        with self._lock:
            tl = self._snapshot.setdefault("ops_timeline", {}).setdefault(run, [])
            if "exit_code" in ev:
                for step in reversed(tl):
                    if step.get("cmd")==ev.get("cmd") and step.get("slug")==ev.get("slug") and "exit_code" not in step:
                        step["exit_code"] = ev["exit_code"]
                        return
            tl.append({k:v for k,v in ev.items() if k != "type"})

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def last_t_emitted(self) -> Optional[str]:
        with self._lock: return self._last_t_emitted

    def runs(self) -> list[str]:
        with self._lock:
            return sorted(set(self._snapshot.get("ops_timeline", {}).keys())
                          | set(self._snapshot.get("sessions", {}).keys()))


# ------------------- Legacy shape used by test_monitor_store.py -------------------
@dataclass
class _LegacyState:
    sessions: list = field(default_factory=list)
    scrlast: Any = None
    steptimes: dict = field(default_factory=dict)
    opstimeline: dict = field(default_factory=dict)
    bridgeport: int = 0
    privilege: str = "ro"
    selected_runid: Optional[str] = None

class Store:
    """Back-compat shape the older HTML monitors consumed."""
    def __init__(self) -> None:
        self.state = _LegacyState()

    def apply_snapshot(self, snap: Mapping[str, Any]) -> None:
        s = self.state
        s.sessions    = list(snap.get("sessions", []))
        s.scrlast     = snap.get("scrlast")
        s.steptimes   = dict(snap.get("steptimes", {}))
        s.opstimeline = {k: list(v) for k,v in snap.get("opstimeline", {}).items()}
        s.bridgeport  = int(snap.get("bridgeport", 0) or 0)
        s.privilege   = str(snap.get("privilege", "ro"))
        if s.selected_runid is None:
            # default selection: first session.runid, else first opstimeline key
            if s.sessions and isinstance(s.sessions[0], Mapping):
                s.selected_runid = s.sessions[0].get("runid")
            elif s.opstimeline:
                s.selected_runid = next(iter(s.opstimeline))
