"""nightclaw_bridge.config -- normalized config with back-compat aliases."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class BridgeConfig:
    bridge_port: int = 8787
    max_sessions: int = 64
    event_log_enabled: bool = True

    # back-compat aliases
    @property
    def bridgeport(self) -> int: return self.bridge_port
    @property
    def maxsessions(self) -> int: return self.max_sessions
    @property
    def eventlogenabled(self) -> bool: return self.event_log_enabled
