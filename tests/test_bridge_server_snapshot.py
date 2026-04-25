import asyncio, tempfile, os, socket, json, pytest
from nightclaw_bridge.config import BridgeConfig
from nightclaw_bridge.main import build_server
from nightclaw_bridge.repository import FileSessionRepository, MemorySessionRepository
from nightclaw_bridge.server import BridgeServer
from nightclaw_bridge.snapshot_contract import validate_sessionssnapshot_payload

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def _exercise_memory():
    # Pass 3.3: exercise the published ``build_server`` factory (routing.yaml
    # R3-CODE row for nightclaw_bridge/main.py) rather than hand-wiring a
    # ``BridgeServer(repo, broadcast)``. With ``sessions_path=None`` the
    # factory installs a ``MemorySessionRepository``; the branch with a
    # concrete path is covered by ``test_build_server_file_repo_factory``.
    sent = []
    async def bcast(ev):
        sent.append(ev)
    srv = build_server(BridgeConfig(), sessions_path=None, broadcast=bcast)
    assert isinstance(srv, BridgeServer)
    assert isinstance(srv.repo, MemorySessionRepository)
    sock_path = os.path.join(tempfile.mkdtemp(), "ops.sock")
    await srv.start(path=sock_path)
    try:
        payload = {"type":"opsstepevent","run_id":"RUN-BS-1","tier":"T1",
                   "cmd":"dispatch","t_emitted":"2026-04-17T16:51:00Z"}
        def client_send():
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(sock_path)
            s.sendall((json.dumps(payload)+"\n").encode())
            s.recv(256)
            s.close()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, client_send)
        for _ in range(30):
            if srv.repo.load_events():
                break
            await asyncio.sleep(0.02)
        snap = srv.render_sessions_snapshot()
        validate_sessionssnapshot_payload(snap)
        assert "RUN-BS-1" in snap["snapshot"]["ops_timeline"]
        assert len(sent) == 1
    finally:
        await srv.stop()

def test_bridge_server_snapshot_memory():
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("AF_UNIX not available")
    _run(_exercise_memory())

def test_file_repo_durable_append(tmp_path):
    p = tmp_path / "events.jsonl"
    repo = FileSessionRepository(str(p))
    repo.append_event({"type":"opsstepevent","run_id":"RUN-F-1","tier":"T1",
                       "cmd":"dispatch","t_emitted":"2026-04-17T16:51:00Z"})
    repo2 = FileSessionRepository(str(p))
    evs = repo2.load_events()
    assert len(evs) == 1 and evs[0]["run_id"] == "RUN-F-1"


def test_build_server_file_repo_factory(tmp_path):
    """Pass 3.3: cover the ``sessions_path=...`` branch of ``build_server``.

    The factory's docstring promises that passing ``sessions_path`` installs
    a ``FileSessionRepository`` at that path, while leaving it ``None``
    uses an in-memory repository. The memory branch is exercised by
    ``test_bridge_server_snapshot_memory``; this test pins the file branch
    so both documented code paths have runtime coverage.
    """
    p = tmp_path / "factory_events.jsonl"
    srv = build_server(sessions_path=str(p))
    assert isinstance(srv, BridgeServer)
    assert isinstance(srv.repo, FileSessionRepository)
    # Append through the factory-built repo and confirm durable write-through.
    srv.repo.append_event({"type":"opsstepevent","run_id":"RUN-FACT-1",
                           "tier":"T1","cmd":"dispatch",
                           "t_emitted":"2026-04-20T17:00:00Z"})
    reloaded = FileSessionRepository(str(p)).load_events()
    assert len(reloaded) == 1 and reloaded[0]["run_id"] == "RUN-FACT-1"
    # Factory must also default the broadcast to a working no-op awaitable.
    assert asyncio.iscoroutinefunction(srv.broadcast)
    _run(srv.broadcast({"noop": True}))  # must not raise
