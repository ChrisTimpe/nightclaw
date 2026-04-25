"""nightclaw_bridge.server -- ops sink and BridgeServer."""
from __future__ import annotations
import asyncio, json, os
from typing import Awaitable, Callable
from .protocol import is_opsstepevent
from .state import fold_eventlog
from .snapshot_contract import build_sessionssnapshot_payload
import datetime

BroadcastFn = Callable[[dict], Awaitable[None]]

async def handle_ops_ingest(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                            repo, broadcast: BroadcastFn) -> None:
    # nightclaw_ops.telemetry._raw_send_unix fire-and-forgets: it calls
    # ``sendall`` then ``close`` without reading the ack, which means the
    # server-side ``drain`` can observe a half-closed socket and raise
    # ConnectionResetError / BrokenPipeError. The event is already captured
    # before the reply is written, so these are benign — swallow them to
    # keep the accept loop quiet.
    async def _safe_drain():
        try:
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
    try:
        data = await reader.readline()
        if not data:
            writer.write(b"{}\n"); await _safe_drain(); return
        try:
            payload = json.loads(data.decode("utf-8").strip())
        except Exception:
            writer.write(b'{"ok":false}\n'); await _safe_drain(); return
        # Producer (nightclaw_ops.telemetry.emit_step) sets ``type``; no
        # compensating reshape needed here. Reject anything missing the
        # discriminator so the contract stays crisp.
        if is_opsstepevent(payload):
            repo.append_event(payload)
            await broadcast(payload)
            writer.write(b'{"ok":true}\n')
        else:
            writer.write(b'{"ok":false}\n')
        await _safe_drain()
    finally:
        try: writer.close()
        except Exception: pass

async def start_ops_sink(repo, broadcast: BroadcastFn, *, path: str):
    if os.path.exists(path):
        try: os.unlink(path)
        except Exception: pass
    async def _cb(r, w): await handle_ops_ingest(r, w, repo, broadcast)
    server = await asyncio.start_unix_server(_cb, path=path)
    # H-SEC-03: restrict the ops ingest socket to the owning user. Without
    # this chmod the unix socket is created with the process umask (often
    # 0o022 → world-writable sockets on dev boxes), which would let any
    # local user inject OpsStepEvent payloads into the bridge event log.
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Best-effort: abstract sockets or exotic filesystems may reject
        # chmod. We do not fail sink startup over it.
        pass
    return server

class BridgeServer:
    """Thin facade: owns repo + broadcast fanout + snapshot rendering."""
    def __init__(self, repo, broadcast: BroadcastFn) -> None:
        self.repo = repo
        self.broadcast = broadcast
        self._sink = None
    async def start(self, *, path: str):
        self._sink = await start_ops_sink(self.repo, self.broadcast, path=path)
        return self._sink
    async def stop(self):
        if self._sink is not None:
            self._sink.close()
            await self._sink.wait_closed()
    def render_sessions_snapshot(self) -> dict:
        snap = fold_eventlog(self.repo.load_events())
        t = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return build_sessionssnapshot_payload(snap, t)
