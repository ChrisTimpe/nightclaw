import asyncio, json, os, socket, tempfile
import pytest
from nightclaw_bridge.repository import MemorySessionRepository
from nightclaw_bridge.server import start_ops_sink
from nightclaw_bridge.state import fold_eventlog
from nightclaw_ops import telemetry


def _run(coro):
    # Scoped loop + explicit close; mirrors the canonical helper in
    # test_bridge_server_snapshot.py. Without .close() the selector
    # is GC'd at interpreter shutdown and triggers
    # PytestUnraisableExceptionWarning (Invalid file descriptor: -1).
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _exercise():
    sock_path = os.path.join(tempfile.mkdtemp(), "ops.sock")
    repo = MemorySessionRepository()
    broadcasted = []

    async def broadcast(event):
        broadcasted.append(event)

    server = await start_ops_sink(repo, broadcast, path=sock_path)

    # route the kernel-side emit_step through this exact socket
    def transport(payload):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(sock_path)
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        s.recv(256)
        s.close()

    telemetry.set_transport(transport)

    os.environ["NIGHTCLAW_RUN_ID"] = "RUN-20260417-099"
    telemetry.emit_step("T1", cmd="dispatch", session="worker")
    telemetry.emit_step("T1", cmd="dispatch", session="worker",
                        exit_code=0)
    telemetry.emit_step("T6", cmd="bundle-exec", slug="nightclaw",
                        session="worker", exit_code=0)

    # give the socket server a beat to process all three
    for _ in range(20):
        if len(repo.load_events()) >= 3:
            break
        await asyncio.sleep(0.02)

    server.close()
    await server.wait_closed()

    events = repo.load_events()
    assert [e["type"] for e in events] == ["opsstepevent"] * 3
    snap = fold_eventlog(events)
    tl = snap["ops_timeline"]["RUN-20260417-099"]
    assert len(tl) == 2
    assert tl[0]["cmd"] == "dispatch" and tl[0]["exit_code"] == 0
    assert tl[1]["cmd"] == "bundle-exec" and tl[1]["slug"] == "nightclaw"
    assert len(broadcasted) == 3


def test_end_to_end_unix_socket_sink():
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("AF_UNIX not available")
    _run(_exercise())
