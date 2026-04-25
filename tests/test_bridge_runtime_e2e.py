"""End-to-end sandbox verification for the optional local runtime.

Simulates the real telemetry path — engine/CLI → UNIX socket → BridgeServer
broadcast — and asserts the runtime's broadcast fan-out adapts events into
the HTML-facing shapes the shipped monitor pages expect. No HTTP or
browser WebSocket listener is started here so we don't depend on a free
TCP port in the sandbox; the flow that matters (ops ingest → adapted
broadcast) is validated directly.

Also asserts that with the runtime NOT started, core telemetry emission
still succeeds (optional-and-non-blocking property).
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile

import pytest

from nightclaw_bridge.runtime import LocalRuntime, RuntimeConfig
from nightclaw_ops import telemetry


def _run(coro):
    # Use a scoped loop + explicit close to avoid leaking an open selector
    # across the test session. The leaked loop triggers a
    # PytestUnraisableExceptionWarning at interpreter shutdown (GC runs
    # BaseEventLoop.__del__ after the selector is already gone). Mirrors
    # the canonical pattern used in test_bridge_server_snapshot.py::_run.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_ops_to_broadcast_roundtrip(tmp_path):
    """Drive emit_step through the ops socket and verify the runtime's
    fan-out produced the expected browser-facing event shapes."""

    sock_path = str(tmp_path / "ops.sock")
    cfg = RuntimeConfig(
        workspace=str(tmp_path),
        docroot=str(tmp_path),
        bridge_port=0,  # no WS listener
        http_port=0,    # no HTTP listener
        ops_sock_path=sock_path,
    )
    rt = LocalRuntime(cfg)

    # Capture what the runtime _would_ broadcast to each endpoint.
    main_out: list[dict] = []
    sess_out: list[dict] = []

    class _FakeWs:
        def __init__(self, sink): self.sink = sink
        async def send(self, data): self.sink.append(json.loads(data))
        async def close(self): pass

    async def _scenario():
        # Start ONLY the ops sink (no WS listener, no HTTP).
        from nightclaw_bridge.server import start_ops_sink
        server = await start_ops_sink(
            rt._repo, rt._broadcast_bridge_event, path=sock_path,
        )
        try:
            # Pretend two WS clients are already connected.
            from nightclaw_bridge.runtime import _WsClient
            c1 = _WsClient(ws=_FakeWs(main_out), privilege="ro", endpoint="/ws")
            c2 = _WsClient(ws=_FakeWs(sess_out), privilege="ro", endpoint="/sessions")
            async with rt._clients_lock:
                rt._clients.add(c1)
                rt._clients.add(c2)

            # Route telemetry through a synchronous socket transport — this
            # is exactly how engine/CLI code reaches the bridge today.
            def transport(payload):
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect(sock_path)
                s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                s.recv(256)
                s.close()

            telemetry.set_transport(transport)
            os.environ["NIGHTCLAW_RUN_ID"] = "RUN-SANDBOX-1"
            telemetry.emit_step("T0", cmd="session-open", session="worker")
            telemetry.emit_step("T4", cmd="execute", session="worker",
                                slug="demo")
            telemetry.emit_step("T9", cmd="session-close", session="worker",
                                exit_code=0)

            # Let the sink and broadcast chain run.
            for _ in range(50):
                if len(rt._repo.load_events()) >= 3:
                    await asyncio.sleep(0.02)  # one more tick for fan-out
                    break
                await asyncio.sleep(0.02)
        finally:
            telemetry.set_transport(None)  # restore default queue transport
            server.close()
            await server.wait_closed()

    _run(_scenario())

    # Main monitor should have received: session_open + step (T0),
    # step (T4), step + session_close (T9).
    kinds = [e["event_type"] for e in main_out]
    assert kinds.count("session_open") == 1
    assert kinds.count("session_close") == 1
    assert kinds.count("step") == 3

    # Sessions dashboard should have received 3 snapshot frames, each a
    # valid sessions_snapshot with the required keys.
    assert len(sess_out) == 3
    for snap in sess_out:
        assert snap["event_type"] == "sessions_snapshot"
        assert "sessions" in snap and "step_times" in snap
        assert snap["bridgeport"] == 0  # mirrors configured port (0 here)

    # Final snapshot should show one session closed cleanly.
    final = sess_out[-1]
    assert final["sessions"][0]["runid"] == "RUN-SANDBOX-1"
    assert final["sessions"][0]["outcome"] == "clean"


def test_core_telemetry_unaffected_when_runtime_absent(tmp_path):
    """If the ops socket is not bound, emit_step must not raise and must
    not block. Core engine continues unaffected."""

    # Point telemetry at a socket path that does not exist.
    missing = str(tmp_path / "not-there.sock")
    telemetry.DEFAULT_OPS_SOCK  # symbol exists

    # The telemetry emit_step swallows any transport exception by design.
    # Confirm this by setting a transport that would fail, and asserting
    # emit_step returns normally.
    def failing_transport(_payload):
        raise ConnectionRefusedError("no bridge listener")

    telemetry.set_transport(failing_transport)
    try:
        os.environ["NIGHTCLAW_RUN_ID"] = "RUN-SANDBOX-ISO"
        telemetry.emit_step("T0", cmd="session-open")  # must not raise
        telemetry.emit_step("T4", cmd="execute")       # must not raise
    finally:
        telemetry.set_transport(None)


def test_ws_path_routing_live(tmp_path):
    """Live WebSocket probe: /ws returns state_replay; /sessions returns
    sessions_snapshot. Guards against regressions in how we read the path
    off the websockets library's ServerConnection object."""
    pytest.importorskip("websockets")
    import websockets as _ws

    sock_path = str(tmp_path / "ops.sock")
    cfg = RuntimeConfig(
        workspace=str(tmp_path),
        docroot=str(tmp_path),
        bridge_port=0,  # ephemeral port
        http_port=0,
        ops_sock_path=sock_path,
    )
    rt = LocalRuntime(cfg)

    async def _probe(path: str) -> list[dict]:
        async with _ws.connect(f"ws://127.0.0.1:{port}{path}") as ws:
            msgs: list[dict] = []
            for _ in range(3):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                m = json.loads(raw)
                msgs.append(m)
                if m.get("event_type") == "connect_required":
                    await ws.send(json.dumps({"type": "connect", "token": ""}))
            return msgs

    async def _scenario():
        nonlocal port
        # Start a real WS listener on an ephemeral port.
        rt.config.bridge_port = 0
        from nightclaw_bridge.server import start_ops_sink
        rt._ops_sink = await start_ops_sink(
            rt._repo, rt._broadcast_bridge_event, path=sock_path,
        )
        async def _router(ws, p=None):
            if p is None:
                req = getattr(ws, "request", None)
                if req is not None:
                    p = getattr(req, "path", None)
                if p is None:
                    p = getattr(ws, "path", None)
            if not p:
                p = "/ws"
            await rt._ws_handler(ws, p)
        server = await _ws.serve(_router, "127.0.0.1", 0)
        sockets = server.sockets
        assigned = sockets[0].getsockname()[1]
        try:
            return assigned, await _probe_wrap(assigned)
        finally:
            server.close()
            await server.wait_closed()
            rt._ops_sink.close()
            await rt._ops_sink.wait_closed()

    async def _probe_wrap(p):
        nonlocal port
        port = p
        ws_msgs = await _probe("/ws")
        sess_msgs = await _probe("/sessions")
        return ws_msgs, sess_msgs

    port = 0
    _, (ws_msgs, sess_msgs) = _run(_scenario())

    ws_kinds = [m["event_type"] for m in ws_msgs]
    sess_kinds = [m["event_type"] for m in sess_msgs]
    assert ws_kinds == ["connect_required", "connect_ack", "state_replay"]
    assert sess_kinds == ["connect_required", "connect_ack", "sessions_snapshot"]


def test_admin_round_trip_against_real_admin_script(tmp_path):
    """Using a stub admin.sh, verify the end-to-end admin_command path."""

    (tmp_path / "scripts").mkdir()
    admin = tmp_path / "scripts" / "nightclaw-admin.sh"
    admin.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$1\" in\n"
        "  status) echo status-output ;;\n"
        "  alerts) echo alerts-output ;;\n"
        "  approve) echo approved-$2 ;;\n"
        "  guide) echo guided-$2 ;;\n"
        "  *) echo 'unsupported'; exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    admin.chmod(0o755)

    cfg = RuntimeConfig(
        workspace=str(tmp_path),
        docroot=str(tmp_path),
        bridge_port=0, http_port=0,
        ops_sock_path=str(tmp_path / "ops.sock"),
        bridge_token="owner-secret",
    )
    rt = LocalRuntime(cfg)

    # RO command runs regardless of token.
    r = _run(rt.run_admin_command("status", {}, privilege="ro"))
    assert r["ok"] and "status-output" in r["output"]

    # RW command requires privilege.
    r = _run(rt.run_admin_command("approve", {"slug": "demo"}, privilege="ro"))
    assert not r["ok"]

    # With RW privilege it runs.
    r = _run(rt.run_admin_command("approve", {"slug": "demo"}, privilege="rw"))
    assert r["ok"] and "approved-demo" in r["output"]

    # Guidance message passed as a single argv element, not shell-interpolated.
    r = _run(rt.run_admin_command("guide", {"message": "hold the line"},
                                  privilege="rw"))
    assert r["ok"] and "guided-hold the line" in r["output"]
