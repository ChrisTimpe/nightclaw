from nightclaw_bridge.client_handlers import on_opsstepevent, _Store


def test_client_appends_and_completes():
    store = _Store()
    on_opsstepevent(store, {"type": "opsstepevent", "run_id": "RUN-1",
                            "tier": "T1", "cmd": "dispatch",
                            "t_emitted": "2026-04-17T16:40:00Z"})
    on_opsstepevent(store, {"type": "opsstepevent", "run_id": "RUN-1",
                            "tier": "T1", "cmd": "dispatch",
                            "t_emitted": "2026-04-17T16:40:00Z",
                            "exit_code": 0})
    tl = store.state["ops_timeline"]["RUN-1"]
    assert len(tl) == 1
    assert tl[0]["cmd"] == "dispatch"
    assert tl[0]["exit_code"] == 0
    assert store.notifications == 2
