from nightclaw_monitor.handlers import HandlerRouter, DEFAULT_HANDLERS
from nightclaw_monitor.store import MonitorStore
from nightclaw_bridge.snapshot_contract import build_sessionssnapshot_payload

def test_router_dispatches_snapshot_and_opsstep():
    store = MonitorStore()
    router = HandlerRouter(store)
    snap = {"sessions":{}, "ops_timeline":{}}
    payload = build_sessionssnapshot_payload(snap, "2026-04-17T16:51:00Z")
    assert router.dispatch(payload) is True
    assert store.last_t_emitted() == "2026-04-17T16:51:00Z"

    ev = {"type":"opsstepevent","run_id":"RUN-77","tier":"T1",
          "cmd":"dispatch","t_emitted":"2026-04-17T16:51:05Z"}
    assert router.dispatch(ev) is True
    done = {**ev, "exit_code": 0}
    assert router.dispatch(done) is True
    tl = store.snapshot()["ops_timeline"]["RUN-77"]
    assert len(tl) == 1 and tl[0]["exit_code"] == 0

def test_router_ignores_unknown_types():
    store = MonitorStore()
    router = HandlerRouter(store)
    assert router.dispatch({"type":"nope"}) is False

def test_default_handlers_registered():
    assert set(DEFAULT_HANDLERS.keys()) == {"sessionssnapshot","opsstepevent"}
