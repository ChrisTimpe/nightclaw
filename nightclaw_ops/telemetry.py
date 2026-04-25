"""nightclaw_ops/telemetry.py -- fire-and-forget telemetry transport."""
from __future__ import annotations

import atexit
import datetime
import json
import os
import queue
import socket
import threading
from typing import Callable, Optional

DEFAULT_OPS_SOCK: str = os.environ.get("NIGHTCLAW_OPS_SOCK", "/tmp/nightclaw-ops.sock")
_QUEUE_MAXSIZE: int = 512
_SEND_TIMEOUT: float = 0.25
_FLUSH_BUDGET: float = 0.050

_q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
_lock = threading.Lock()
_worker_started = False
_custom_transport: Optional[Callable[[dict], None]] = None

def _worker_loop() -> None:
    while True:
        try:
            payload = _q.get(block=True, timeout=1.0)
        except queue.Empty:
            continue
        try:
            _raw_send_unix(payload)
        except Exception:
            pass
        finally:
            _q.task_done()

def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, name="nc-telemetry", daemon=True)
        t.start()
        _worker_started = True

def _enqueue(payload: dict) -> None:
    _ensure_worker()
    try:
        _q.put_nowait(payload)
    except queue.Full:
        try:
            _q.get_nowait()
            _q.task_done()
        except queue.Empty:
            pass
        try:
            _q.put_nowait(payload)
        except queue.Full:
            pass

def _raw_send_unix(payload: dict, path: str | None = None) -> None:
    if path is None:
        path = DEFAULT_OPS_SOCK
    if not os.path.exists(path):
        return
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(_SEND_TIMEOUT)
    try:
        s.connect(path)
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except Exception:
        pass
    finally:
        try:
            s.close()
        except Exception:
            pass

def _flush_on_exit() -> None:
    import time
    deadline = time.monotonic() + _FLUSH_BUDGET
    while not _q.empty() and time.monotonic() < deadline:
        time.sleep(0.001)

atexit.register(_flush_on_exit)

def utc_now_iso() -> str:
    return (datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

def set_transport(fn: Callable[[dict], None]) -> None:
    global _custom_transport
    _custom_transport = fn

def emit_step(tier: str, *, cmd: str, run_id: Optional[str] = None, slug: Optional[str] = None, session: Optional[str] = None, exit_code: Optional[int] = None) -> None:
    # NIGHTCLAW_NO_TELEMETRY=1 suppresses all telemetry emission. Used by
    # nightclaw_bridge.sources when it spawns nightclaw-ops.py as a utility
    # subprocess (longrunner-extract, scr-verify, etc.) to prevent those
    # bridge-internal calls from appearing as phantom step events in the monitor.
    if os.environ.get("NIGHTCLAW_NO_TELEMETRY") == "1":
        return
    try:
        # The wire contract is ``opsstepevent`` (see nightclaw_bridge.protocol).
        # Producing the ``type`` key here keeps the payload self-describing and
        # removes the need for a compensating shim on the bridge ingest path.
        # ops remains independent of bridge code: we only duplicate the literal
        # discriminator string, not the validator.
        payload: dict = {
            "type": "opsstepevent",
            "run_id": run_id or os.environ.get("NIGHTCLAW_RUN_ID", "UNKNOWN"),
            "tier": tier,
            "cmd": cmd,
            "t_emitted": utc_now_iso(),
        }
        if slug is not None: payload["slug"] = slug
        if session is not None: payload["session"] = session
        if exit_code is not None: payload["exit_code"] = exit_code
        if _custom_transport is not None:
            _custom_transport(payload)
        else:
            _enqueue(payload)
    except Exception:
        pass
