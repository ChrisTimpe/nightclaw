from nightclaw_bridge.repository import MemorySessionRepository


def test_memory_repo_preserves_interleave():
    repo = MemorySessionRepository()
    repo.append_event({"type": "sessionsevent",
                       "run_id": "RUN-1", "kind": "open"})
    repo.append_event({"type": "opsstepevent", "run_id": "RUN-1",
                       "tier": "T1", "cmd": "dispatch",
                       "t_emitted": "2026-04-17T16:40:00Z"})
    repo.append_event({"type": "opsstepevent", "run_id": "RUN-1",
                       "tier": "T6", "cmd": "bundle-exec",
                       "t_emitted": "2026-04-17T16:40:01Z",
                       "exit_code": 0})
    repo.append_event({"type": "sessionsevent",
                       "run_id": "RUN-1", "kind": "close"})
    types = [e["type"] for e in repo.load_events()]
    assert types == ["sessionsevent", "opsstepevent",
                     "opsstepevent", "sessionsevent"]


def test_memory_repo_copies_on_append():
    repo = MemorySessionRepository()
    event = {"type": "sessionsevent", "run_id": "RUN-1", "kind": "open"}
    repo.append_event(event)
    event["kind"] = "mutated"
    assert repo.load_events()[0]["kind"] == "open"
