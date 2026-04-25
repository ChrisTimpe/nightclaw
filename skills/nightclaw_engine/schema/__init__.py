"""nightclaw_engine.schema — typed YAML schema (Tier A + Tier C).

Exports:
    loader         — Tier A orchestration-os/schema/*.yaml loader (Merge 1).
    load, invalidate, SchemaModel, SchemaError, and all row dataclasses.
    Phase, PhaseMachine, load_phase_machine, load_phase_machine_for_slug
                   — Tier C per-project phase state machines (Merge 2).
"""
from __future__ import annotations

from . import loader, phases
from .loader import (
    BundleSpec,
    Edge,
    FieldSpec,
    ObjectSpec,
    RouteRule,
    SCRRule,
    SchemaError,
    SchemaModel,
    invalidate,
    load,
)
from .phases import (
    Phase,
    PhaseMachine,
    load_phase_machine,
    load_phase_machine_for_slug,
)

__all__ = [
    "BundleSpec",
    "Edge",
    "FieldSpec",
    "ObjectSpec",
    "Phase",
    "PhaseMachine",
    "RouteRule",
    "SCRRule",
    "SchemaError",
    "SchemaModel",
    "invalidate",
    "load",
    "load_phase_machine",
    "load_phase_machine_for_slug",
    "loader",
    "phases",
]
