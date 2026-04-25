from nightclaw_bridge.state import fold_eventlog


def test_ops_timeline_appends_and_completes():
    events = [
        {"type": "opsstepevent", "run_id": "RUN-010",
         "tier": "T1", "cmd": "dispatch",
         "t_emitted": "2026-04-17T16:40:00Z"},
        {"type": "opsstepevent", "run_id": "RUN-010",
         "tier": "T1", "cmd": "dispatch",
         "t_emitted": "2026-04-17T16:40:00Z", "exit_code": 0},
        {"type": "opsstepevent", "run_id": "RUN-010",
         "tier": "T6", "cmd": "bundle-exec", "slug": "nightclaw",
         "t_emitted": "2026-04-17T16:40:02Z", "exit_code": 0},
    ]
    snap = fold_eventlog(events)
    tl = snap["ops_timeline"]["RUN-010"]
    assert len(tl) == 2
    assert tl[0]["cmd"] == "dispatch" and tl[0]["exit_code"] == 0
    assert tl[1]["cmd"] == "bundle-exec" and tl[1]["slug"] == "nightclaw"


def test_ops_timeline_isolated_per_run():
    events = [
        {"type": "opsstepevent", "run_id": "RUN-A",
         "tier": "T1", "cmd": "dispatch",
         "t_emitted": "2026-04-17T16:40:00Z"},
        {"type": "opsstepevent", "run_id": "RUN-B",
         "tier": "T1", "cmd": "dispatch",
         "t_emitted": "2026-04-17T16:40:01Z"},
    ]
    snap = fold_eventlog(events)
    assert set(snap["ops_timeline"].keys()) == {"RUN-A", "RUN-B"}


def test_snapshot_preserves_sessions_field():
    events = [
        {"type": "sessionsevent", "run_id": "RUN-Z", "kind": "open"},
        {"type": "opsstepevent", "run_id": "RUN-Z",
         "tier": "T1", "cmd": "dispatch",
         "t_emitted": "2026-04-17T16:40:00Z"},
        {"type": "sessionsevent", "run_id": "RUN-Z", "kind": "close"},
    ]
    snap = fold_eventlog(events)
    assert "sessions" in snap and "RUN-Z" in snap["sessions"]
    assert snap["sessions"]["RUN-Z"]["kinds"] == ["open", "close"]
    assert "ops_timeline" in snap and "RUN-Z" in snap["ops_timeline"]
