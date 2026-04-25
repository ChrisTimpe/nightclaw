"""nightclaw_bridge.main -- CLI / factory entry point for the bridge.

G3 FIX: the previous version passed keyword arguments (``config=``,
``repository=``, ``workspace=``) that do not exist on ``BridgeServer``, and
read attributes (``sessions_path``, ``workspace_root``, ``maxsessions``) that
do not exist on ``BridgeConfig``. Calling ``build_server`` would raise
``TypeError`` immediately; the gap hid behind the fact that no test, nor any
entry in ``scripts/``, ever called it.

The real shapes are:
  * ``BridgeConfig(bridge_port, max_sessions, event_log_enabled)`` \u2014
    purely tuning knobs, no persistence path.
  * ``FileSessionRepository(path)`` and ``MemorySessionRepository()`` \u2014
    no ``maxsessions`` kwarg.
  * ``BridgeServer(repo, broadcast)`` \u2014 requires a broadcast callable.

This factory stitches those together with reasonable defaults and lets the
caller override persistence and the broadcast function.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

from .config import BridgeConfig
from .repository import FileSessionRepository, MemorySessionRepository
from .server import BridgeServer


# Type alias kept in sync with server.BroadcastFn.
BroadcastFn = Callable[[dict], Awaitable[None]]


async def _null_broadcast(_payload: dict) -> None:
    """Default broadcast that drops events. Tests/CLI override as needed."""
    return None


def build_server(
    config: Optional[BridgeConfig] = None,
    *,
    sessions_path: Optional[str] = None,
    broadcast: Optional[BroadcastFn] = None,
) -> BridgeServer:
    """Construct a ``BridgeServer`` wired with a repository + broadcast.

    Args:
        config: Tuning knobs. Defaults to ``BridgeConfig()``.
        sessions_path: If given, use a ``FileSessionRepository`` at this path.
            Otherwise events are held in-memory for the process lifetime.
        broadcast: Async callable invoked for every accepted ops event.
            Defaults to a no-op broadcaster.

    Returns:
        A ready-to-start ``BridgeServer``. Call ``await server.start(path=...)``
        to attach it to the ops unix socket.
    """
    _ = config or BridgeConfig()  # reserved for future tuning wiring
    if sessions_path is not None:
        repo = FileSessionRepository(sessions_path)
    else:
        repo = MemorySessionRepository()
    return BridgeServer(repo=repo, broadcast=broadcast or _null_broadcast)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point for the optional local runtime.

    Running ``python -m nightclaw_bridge`` with ``--serve`` brings up the
    HTTP + WebSocket + ops-sink stack so a browser can load
    apps/monitor/nightclaw-monitor.html against it. Core engine/CLI paths
    do not depend on this and continue to work when it is not running.
    """
    import argparse
    import asyncio as _asyncio
    import os as _os

    parser = argparse.ArgumentParser(prog="nightclaw_bridge")
    parser.add_argument("--serve", action="store_true",
                        help="Launch the optional local HTTP+WS runtime")
    parser.add_argument("--workspace", default=_os.getcwd(),
                        help="Workspace root (default: cwd)")
    parser.add_argument("--bridge-port", type=int, default=8787)
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--ops-sock",
                        default=_os.environ.get("NIGHTCLAW_OPS_SOCK",
                                                "/tmp/nightclaw-ops.sock"))
    parser.add_argument("--sessions-path", default=None,
                        help="Optional JSONL path to persist ops events")
    args = parser.parse_args(argv)

    if not args.serve:
        parser.print_help()
        return 0

    from .runtime import build_runtime
    token = _os.environ.get("NIGHTCLAW_BRIDGE_TOKEN")
    rt = build_runtime(
        workspace=args.workspace,
        bridge_port=args.bridge_port,
        http_port=args.http_port,
        ops_sock_path=args.ops_sock,
        bridge_token=token,
        sessions_path=args.sessions_path,
    )

    async def _run():
        await rt.start()
        try:
            # Park forever; asyncio.Event().wait() never returns.
            await _asyncio.Event().wait()
        finally:
            await rt.stop()
    try:
        _asyncio.run(_run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
