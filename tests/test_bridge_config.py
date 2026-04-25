"""tests/test_bridge_config.py — Pass 13 Chunk B.2 (H-TEST-05).

``nightclaw_bridge.config.BridgeConfig`` exposes three back-compat alias
properties (``bridgeport``, ``maxsessions``, ``eventlogenabled``) that
mirror the snake_case fields (``bridge_port``, ``max_sessions``,
``event_log_enabled``). These aliases are the documented migration
surface from the pre-G3-fix era and the monitor HTML scripts still read
the legacy names, so silently removing one would break downstream
consumers.

Pre-Pass-13 this module had zero test coverage. These tests encode the
three alias contracts plus the default-value surface as CI invariants.
"""
from __future__ import annotations

from nightclaw_bridge.config import BridgeConfig


def test_bridge_config_default_values():
    """The defaults are doctrine: port 8787, 64 concurrent sessions, event
    log on. Changing any of these values is a breaking change for every
    installed monitor client."""
    cfg = BridgeConfig()
    assert cfg.bridge_port == 8787
    assert cfg.max_sessions == 64
    assert cfg.event_log_enabled is True


def test_bridgeport_alias_mirrors_bridge_port():
    """``.bridgeport`` is the pre-G3-fix name; it must always read the same
    value as ``.bridge_port``."""
    cfg = BridgeConfig(bridge_port=9999)
    assert cfg.bridgeport == 9999
    assert cfg.bridgeport == cfg.bridge_port


def test_maxsessions_alias_mirrors_max_sessions():
    cfg = BridgeConfig(max_sessions=128)
    assert cfg.maxsessions == 128
    assert cfg.maxsessions == cfg.max_sessions


def test_eventlogenabled_alias_mirrors_event_log_enabled():
    cfg_on = BridgeConfig(event_log_enabled=True)
    cfg_off = BridgeConfig(event_log_enabled=False)
    assert cfg_on.eventlogenabled is True
    assert cfg_off.eventlogenabled is False
    assert cfg_on.eventlogenabled is cfg_on.event_log_enabled
    assert cfg_off.eventlogenabled is cfg_off.event_log_enabled


def test_aliases_reflect_post_construction_mutation():
    """BridgeConfig is a non-frozen dataclass, so mutation is legal and the
    aliases must track the mutation. If BridgeConfig is ever frozen this
    test flags the behavior change.
    """
    cfg = BridgeConfig()
    cfg.bridge_port = 7000
    cfg.max_sessions = 1
    cfg.event_log_enabled = False
    assert cfg.bridgeport == 7000
    assert cfg.maxsessions == 1
    assert cfg.eventlogenabled is False


def test_aliases_are_read_only_properties():
    """The aliases are declared as ``@property`` getters. Assigning to them
    must raise AttributeError so no caller accidentally writes to the
    alias and sees the canonical field stay stale."""
    cfg = BridgeConfig()
    import pytest

    for alias in ("bridgeport", "maxsessions", "eventlogenabled"):
        with pytest.raises(AttributeError):
            setattr(cfg, alias, 1)
