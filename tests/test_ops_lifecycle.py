import os
from nightclaw_ops import telemetry, lifecycle

def test_step_context_emits_open_and_close():
    seen = []
    telemetry.set_transport(lambda p: seen.append(p))
    os.environ["NIGHTCLAW_RUN_ID"] = "RUN-LC-1"
    with lifecycle.step("T1", "dispatch", session="worker"):
        pass
    assert len(seen) == 2
    assert "exit_code" not in seen[0]
    assert seen[1]["exit_code"] == 0
    assert seen[0]["run_id"] == "RUN-LC-1"

def test_step_context_reports_failure():
    seen = []
    telemetry.set_transport(lambda p: seen.append(p))
    os.environ["NIGHTCLAW_RUN_ID"] = "RUN-LC-2"
    try:
        with lifecycle.step("T6", "bundle-exec", slug="nightclaw"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert seen[1]["exit_code"] == 1
    assert seen[1]["slug"] == "nightclaw"

def test_mark_is_silent_on_transport_failure():
    def boom(p): raise RuntimeError("down")
    telemetry.set_transport(boom)
    lifecycle.mark("T1", "dispatch", run_id="RUN-Z")  # must not raise
