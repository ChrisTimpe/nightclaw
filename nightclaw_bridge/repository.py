"""nightclaw_bridge.repository -- event repositories."""
from __future__ import annotations
import json, os, threading
from typing import List

class MemorySessionRepository:
    def __init__(self) -> None:
        self._events: List[dict] = []
        self._lock = threading.Lock()
    def append_event(self, ev: dict) -> None:
        with self._lock:
            self._events.append(dict(ev))
    def load_events(self) -> List[dict]:
        with self._lock:
            return list(self._events)

class FileSessionRepository:
    """Append-only JSONL repository -- durable variant of MemorySessionRepository."""
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        d = os.path.dirname(path)
        if d: os.makedirs(d, exist_ok=True)
        if not os.path.exists(path):
            open(path, "a").close()
    def append_event(self, ev: dict) -> None:
        line = json.dumps(ev, sort_keys=True) + "\n"
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line); f.flush()
    def load_events(self) -> list[dict]:
        out: list[dict] = []
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line: continue
                        try:
                            parsed = json.loads(line)
                            if isinstance(parsed, dict):  # skip arrays/scalars (e.g. bare [] init)
                                out.append(parsed)
                        except Exception: continue
            except FileNotFoundError:
                return []
        return out
