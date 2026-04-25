import pytest
from nightclaw_bridge.protocol import build_opsstepevent, is_opsstepevent


def test_opsstepevent_minimal():
    p = build_opsstepevent(run_id="RUN-20260417-001", tier="T6",
                           cmd="bundle-exec",
                           t_emitted="2026-04-17T16:51:00Z")
    assert is_opsstepevent(p)
    assert p == {
        "type": "opsstepevent",
        "run_id": "RUN-20260417-001",
        "tier": "T6",
        "cmd": "bundle-exec",
        "t_emitted": "2026-04-17T16:51:00Z",
    }


def test_opsstepevent_with_slug_and_exit():
    p = build_opsstepevent(run_id="RUN-20260417-002", tier="T2",
                           cmd="longrunner-extract",
                           t_emitted="2026-04-17T16:52:01Z",
                           slug="nightclaw", pid=42123,
                           session="worker", exit_code=0)
    assert p["slug"] == "nightclaw"
    assert p["exit_code"] == 0
    assert p["session"] == "worker"
    assert p["pid"] == 42123


def test_opsstepevent_rejects_unknown_tier():
    # G2 FIX regression guard: the previous assertion used tier="T5" which is
    # actually a valid worker tier per CRON-WORKER-PROMPT.md (T5 = execute
    # deterministic actions). Using a genuinely-invalid tier name here keeps
    # the rejection contract asserted without re-introducing the bug.
    with pytest.raises(ValueError):
        build_opsstepevent(run_id="RUN-X", tier="T99", cmd="dispatch",
                           t_emitted="2026-04-17T16:53:00Z")


def test_opsstepevent_accepts_full_tier_set():
    # Every tier that appears in CRON-WORKER-PROMPT.md / CRON-MANAGER-PROMPT.md
    # must round-trip cleanly. This locks the G2 fix.
    for t in ("T0", "T1", "T1.5", "T2", "T2.5", "T2.7", "T3", "T3.5", "T4",
              "T5", "T5.5", "T6", "T7", "T7a", "T7b", "T7c", "T7d",
              "T8", "T8.3", "T8.5", "T9"):
        p = build_opsstepevent(run_id="RUN-Z", tier=t, cmd="x",
                               t_emitted="2026-04-17T16:53:00Z")
        assert p["tier"] == t


def test_opsstepevent_requires_core_fields():
    with pytest.raises(ValueError):
        build_opsstepevent(run_id="", tier="T1", cmd="dispatch",
                           t_emitted="2026-04-17T16:53:00Z")
    with pytest.raises(ValueError):
        build_opsstepevent(run_id="RUN-Y", tier="T1", cmd="",
                           t_emitted="2026-04-17T16:53:00Z")
