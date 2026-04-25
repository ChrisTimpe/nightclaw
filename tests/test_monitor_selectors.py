"""tests/test_monitor_selectors.py -- Pass 13 Chunk B.3 (H-TEST-07).

The three selectors in ``nightclaw_monitor.selectors`` are the pure
read-side API that the monitor HTML scripts and any future replay
consumer (KI-03) call. They are the only mechanism that surfaces
in-flight telemetry steps from a rendered snapshot, so regressions
would silently corrupt the monitor's step-timeline UI.

Pre-Pass-13 this module had zero test coverage. This suite encodes:

  * ``timeline_for_run`` -- empty snapshot, unknown run, single
    complete step, open step, list-copy semantics.
  * ``open_steps`` -- key-presence check: returns every step dict
    that does not carry an ``exit_code`` key, across all runs. This
    is not a pair-match: in the current event shape the enter and
    exit are separate events (only the exit carries ``exit_code``),
    so every enter event is returned. Future consumers pair them.
  * ``runs_index`` -- deterministic sorted union of ``ops_timeline``
    and ``sessions`` keys.
"""
from __future__ import annotations

from nightclaw_monitor.selectors import (
    open_steps,
    runs_index,
    timeline_for_run,
)


# ---------------------------------------------------------------------------
# Fixture snapshots
# ---------------------------------------------------------------------------

EMPTY_SNAPSHOT: dict = {}

SINGLE_COMPLETE_SNAPSHOT = {
    "ops_timeline": {
        "RUN-20260420-001": [
            {
                "t_emitted": "2026-04-20T10:00:00Z",
                "tier": "T1",
                "cmd": "dispatch",
            },
            {
                "t_emitted": "2026-04-20T10:00:01Z",
                "tier": "T1",
                "cmd": "dispatch",
                "exit_code": 0,
            },
        ],
    },
}

OPEN_STEP_SNAPSHOT = {
    "ops_timeline": {
        "RUN-20260420-002": [
            {
                "t_emitted": "2026-04-20T10:01:00Z",
                "tier": "T6",
                "cmd": "bundle-exec",
                "slug": "nightclaw",
            },
            # no exit event: the bundle-exec crashed before emitting it
        ],
    },
}

MIXED_SNAPSHOT = {
    "ops_timeline": {
        "RUN-A": [
            {"t_emitted": "2026-04-20T10:00:00Z", "cmd": "dispatch"},
            {"t_emitted": "2026-04-20T10:00:01Z", "cmd": "dispatch",
             "exit_code": 0},
        ],
        "RUN-B": [
            {"t_emitted": "2026-04-20T10:01:00Z", "cmd": "bundle-exec"},
            # no exit for RUN-B
        ],
        "RUN-C": [
            {"t_emitted": "2026-04-20T10:02:00Z", "cmd": "append"},
            {"t_emitted": "2026-04-20T10:02:01Z", "cmd": "append",
             "exit_code": 1},
        ],
    },
    "sessions": {
        # session key not present in ops_timeline -- runs_index must still
        # surface it.
        "RUN-SESSION-ONLY": {"status": "open"},
    },
}


# ---------------------------------------------------------------------------
# timeline_for_run
# ---------------------------------------------------------------------------

def test_timeline_for_run_empty_snapshot():
    assert timeline_for_run(EMPTY_SNAPSHOT, "RUN-X") == []


def test_timeline_for_run_unknown_run():
    assert timeline_for_run(SINGLE_COMPLETE_SNAPSHOT, "RUN-DOES-NOT-EXIST") == []


def test_timeline_for_run_single_complete_step():
    tl = timeline_for_run(SINGLE_COMPLETE_SNAPSHOT, "RUN-20260420-001")
    assert len(tl) == 2
    assert tl[0]["cmd"] == "dispatch"
    assert "exit_code" not in tl[0]
    assert tl[1]["exit_code"] == 0


def test_timeline_for_run_open_step_preserves_missing_exit_code():
    tl = timeline_for_run(OPEN_STEP_SNAPSHOT, "RUN-20260420-002")
    assert len(tl) == 1
    assert "exit_code" not in tl[0], (
        "timeline_for_run must not fabricate an exit_code for open steps"
    )


def test_timeline_for_run_returns_new_list_not_view():
    """The selector returns ``list(...)``; mutating the result must not
    mutate the snapshot."""
    tl = timeline_for_run(SINGLE_COMPLETE_SNAPSHOT, "RUN-20260420-001")
    tl.append({"injected": True})
    assert len(SINGLE_COMPLETE_SNAPSHOT["ops_timeline"]["RUN-20260420-001"]) == 2


# ---------------------------------------------------------------------------
# open_steps
# ---------------------------------------------------------------------------

def test_open_steps_empty_snapshot():
    assert open_steps(EMPTY_SNAPSHOT) == []


def test_open_steps_returns_enter_event_of_complete_pair():
    """Key-presence semantics: in a complete enter+exit pair the enter
    event has no ``exit_code`` key, so it surfaces in ``open_steps``.
    Pairing is the consumer's job, not the selector's."""
    opens = open_steps(SINGLE_COMPLETE_SNAPSHOT)
    assert len(opens) == 1
    assert opens[0]["run_id"] == "RUN-20260420-001"
    assert opens[0]["cmd"] == "dispatch"
    assert opens[0]["t_emitted"] == "2026-04-20T10:00:00Z"


def test_open_steps_surfaces_enter_event_with_no_exit():
    """A run that crashed before emitting its exit event must still
    surface the enter event (same code path as the complete case)."""
    opens = open_steps(OPEN_STEP_SNAPSHOT)
    assert len(opens) == 1
    step = opens[0]
    assert step["run_id"] == "RUN-20260420-002"
    assert step["cmd"] == "bundle-exec"
    assert "exit_code" not in step


def test_open_steps_mixed_runs_returns_one_per_enter_event():
    """MIXED: RUN-A enter+exit, RUN-B enter only, RUN-C enter+exit.
    Three enter events total, one open_steps row per run."""
    opens = open_steps(MIXED_SNAPSHOT)
    assert len(opens) == 3
    run_ids = {o["run_id"] for o in opens}
    assert run_ids == {"RUN-A", "RUN-B", "RUN-C"}
    for o in opens:
        assert "exit_code" not in o


def test_open_steps_skips_events_that_carry_exit_code():
    """``exit_code=0`` is a successful exit. A step dict that carries
    that key is a fully-emitted exit event and must NOT be in
    ``open_steps``. Key-presence, not truthiness."""
    snap = {
        "ops_timeline": {
            "RUN-OK": [
                {"cmd": "x", "exit_code": 0},
                {"cmd": "x", "exit_code": 1},
            ],
        },
    }
    assert open_steps(snap) == []


# ---------------------------------------------------------------------------
# runs_index
# ---------------------------------------------------------------------------

def test_runs_index_empty_snapshot():
    assert runs_index(EMPTY_SNAPSHOT) == []


def test_runs_index_sorted_union_of_timeline_and_sessions():
    ix = runs_index(MIXED_SNAPSHOT)
    # Union: RUN-A, RUN-B, RUN-C (from ops_timeline) + RUN-SESSION-ONLY
    # (from sessions only). Output must be sorted.
    assert ix == ["RUN-A", "RUN-B", "RUN-C", "RUN-SESSION-ONLY"]


def test_runs_index_dedupes_runs_in_both_maps():
    snap = {
        "ops_timeline": {"RUN-A": [], "RUN-B": []},
        "sessions":     {"RUN-A": {}, "RUN-C": {}},
    }
    assert runs_index(snap) == ["RUN-A", "RUN-B", "RUN-C"]


def test_runs_index_is_deterministic():
    """Sorting guarantee: the monitor UI renders the run list from this
    selector and depends on stable ordering."""
    snap = {
        "ops_timeline": {"RUN-Z": [], "RUN-A": [], "RUN-M": []},
        "sessions": {},
    }
    assert runs_index(snap) == ["RUN-A", "RUN-M", "RUN-Z"]
