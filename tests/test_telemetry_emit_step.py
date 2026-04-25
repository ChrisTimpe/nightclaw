import os
from nightclaw_ops import telemetry


def test_emit_step_uses_injected_transport():
    seen = []
    telemetry.set_transport(lambda p: seen.append(p))
    os.environ["NIGHTCLAW_RUN_ID"] = "RUN-20260417-050"
    telemetry.emit_step("T6", cmd="bundle-exec",
                        slug="nightclaw", session="worker")
    telemetry.emit_step("T6", cmd="bundle-exec",
                        slug="nightclaw", session="worker",
                        exit_code=0)
    assert len(seen) == 2
    assert seen[0]["tier"] == "T6"
    assert seen[0]["cmd"] == "bundle-exec"
    assert seen[0]["run_id"] == "RUN-20260417-050"
    assert "exit_code" not in seen[0]
    assert seen[1]["exit_code"] == 0


def test_emit_step_never_raises_when_transport_fails():
    def boom(payload):
        raise RuntimeError("bridge down")
    telemetry.set_transport(boom)
    # must be a silent no-op
    telemetry.emit_step("T1", cmd="dispatch", run_id="RUN-X")


def test_emit_step_tier_is_opaque_to_transport():
    """emit_step itself does not validate tier; the bridge does at ingest."""
    seen = []
    telemetry.set_transport(lambda p: seen.append(p))
    telemetry.emit_step("not-a-tier", cmd="x", run_id="RUN-1")
    assert seen[0]["tier"] == "not-a-tier"
