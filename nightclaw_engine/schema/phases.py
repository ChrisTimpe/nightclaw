"""nightclaw_engine.schema.phases — Tier C per-project phase state machines.

Each active project may declare a formal state machine in
``PROJECTS/[slug]/phases.yaml`` with the shape::

    slug: <project-slug>
    initial_phase: <name>
    phases:
      <name>:
        objective: <text>
        stop_condition: <text>
        allowed_tools: [<tool>, <tool>, ...]
        successors: [<name>, ...]   # [] means terminal

``phase_advance`` and ``phase_transition`` bundle executions consult this
machine before they write. An unknown successor, an undeclared current
phase, or a missing ``phases.yaml`` is a hard reject.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .loader import SchemaError, _HAVE_YAML, yaml  # reuse loader-level guard


@dataclass(frozen=True)
class Phase:
    name: str
    objective: str
    stop_condition: str
    allowed_tools: Tuple[str, ...]
    successors: Tuple[str, ...]


@dataclass(frozen=True)
class PhaseMachine:
    slug: str
    initial_phase: str
    phases: Tuple[Phase, ...]
    source_path: Path

    def get(self, name: str) -> Optional[Phase]:
        for p in self.phases:
            if p.name == name:
                return p
        return None

    @property
    def phase_names(self) -> Tuple[str, ...]:
        return tuple(p.name for p in self.phases)

    def allows_transition(self, from_phase: str, to_phase: str) -> bool:
        p = self.get(from_phase)
        if p is None:
            return False
        return to_phase in p.successors

    def is_terminal(self, name: str) -> bool:
        p = self.get(name)
        return bool(p) and len(p.successors) == 0


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _require_str(data: Mapping, key: str, ctx: str) -> str:
    v = data.get(key)
    if not isinstance(v, str) or not v.strip():
        raise SchemaError(f"{ctx}: missing required string '{key}'")
    return v.strip()


def _coerce_str_list(v, ctx: str) -> Tuple[str, ...]:
    if v is None:
        return ()
    if not isinstance(v, list):
        raise SchemaError(f"{ctx}: expected list, got {type(v).__name__}")
    out: List[str] = []
    for item in v:
        if not isinstance(item, str) or not item.strip():
            raise SchemaError(f"{ctx}: list entries must be non-empty strings")
        out.append(item.strip())
    return tuple(out)


def load_phase_machine(yaml_path: Path) -> PhaseMachine:
    """Parse a ``phases.yaml`` file into a :class:`PhaseMachine`.

    Raises :class:`SchemaError` for any shape problem.
    """
    if not _HAVE_YAML:
        raise SchemaError(
            "PyYAML is required to load phases.yaml; install pyyaml."
        )
    if not yaml_path.exists():
        raise SchemaError(f"phases.yaml not found: {yaml_path}")

    try:
        text = yaml_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"cannot read {yaml_path}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        raise SchemaError(f"invalid YAML in {yaml_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SchemaError(f"{yaml_path}: top-level must be a mapping")

    slug = _require_str(data, "slug", str(yaml_path))
    initial = _require_str(data, "initial_phase", str(yaml_path))

    phases_raw = data.get("phases")
    if not isinstance(phases_raw, dict) or not phases_raw:
        raise SchemaError(f"{yaml_path}: 'phases' must be a non-empty mapping")

    phases: List[Phase] = []
    for name, body in phases_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise SchemaError(f"{yaml_path}: phase names must be non-empty strings")
        if not isinstance(body, dict):
            raise SchemaError(f"{yaml_path}: phase '{name}' must be a mapping")
        ctx = f"{yaml_path}#phases.{name}"
        phases.append(Phase(
            name=name.strip(),
            objective=_require_str(body, "objective", ctx),
            stop_condition=body.get("stop_condition", "").strip() if isinstance(body.get("stop_condition"), str) else "",
            allowed_tools=_coerce_str_list(body.get("allowed_tools"), f"{ctx}.allowed_tools"),
            successors=_coerce_str_list(body.get("successors"), f"{ctx}.successors"),
        ))

    names = {p.name for p in phases}
    if initial not in names:
        raise SchemaError(
            f"{yaml_path}: initial_phase '{initial}' not declared in phases"
        )
    for p in phases:
        for s in p.successors:
            if s not in names:
                raise SchemaError(
                    f"{yaml_path}: phase '{p.name}' lists undeclared successor '{s}'"
                )

    return PhaseMachine(
        slug=slug,
        initial_phase=initial,
        phases=tuple(phases),
        source_path=yaml_path,
    )


def load_phase_machine_for_slug(workspace_root: Path, slug: str) -> PhaseMachine:
    """Resolve and load ``PROJECTS/[slug]/phases.yaml``."""
    if not slug or any(c in slug for c in ("/", "\\", "..")):
        raise SchemaError(f"invalid slug: {slug!r}")
    fp = workspace_root / "PROJECTS" / slug / "phases.yaml"
    return load_phase_machine(fp)


__all__ = [
    "Phase",
    "PhaseMachine",
    "load_phase_machine",
    "load_phase_machine_for_slug",
]
