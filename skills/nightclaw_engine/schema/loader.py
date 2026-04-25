"""nightclaw_engine.schema.loader — YAML schema loader with mtime caching.

This is the Merge-1 reader for the Tier-A machine schema files under
``orchestration-os/schema/``. It deliberately stays read-only: nothing in
this module mutates workspace state. The engine gates added in Merge 2 will
consume the typed ``SchemaModel`` returned by :func:`load`.

Design:
  * stdlib-only except for ``yaml`` (already present in the runtime env).
  * mtime-invalidated in-process cache keyed by the schema directory.
  * Graceful degradation: if ``yaml`` is unavailable, ``load()`` raises
    :class:`SchemaError` with an actionable message. The engine's existing
    R5 bundle executor still works because it reads REGISTRY.md directly in
    Merge 1; Merge 2 makes the YAML required.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # pragma: no cover \u2014 env always has pyyaml today
    import yaml  # type: ignore
    _HAVE_YAML = True
except Exception:  # pragma: no cover
    yaml = None  # type: ignore
    _HAVE_YAML = False


class SchemaError(RuntimeError):
    """Raised for any schema-load or shape problem."""


# ---------------------------------------------------------------------------
# Typed schema model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ObjectSpec:
    obj: str
    file: str
    pk: str
    reader: str
    writer: str
    append_only: bool


@dataclass(frozen=True)
class FieldSpec:
    obj: str
    field: str
    type: str
    req: str  # "y" / "n"
    constraint: str
    fk: str


@dataclass(frozen=True)
class RouteRule:
    file: str
    tier: str
    bundle: str
    note: str


@dataclass(frozen=True)
class Edge:
    source: str
    type: str
    target: str


@dataclass(frozen=True)
class BundleSpec:
    name: str
    trigger: str
    args: Tuple[str, ...]
    validates: Tuple[str, ...]
    writes: Dict[str, Dict[str, Any]]
    append: Dict[str, str]
    notify: Optional[Dict[str, Any]]
    returns: str
    inline: bool
    # Passthrough for pa_invoke / manifest_verify extras.
    extras: Dict[str, Any]


@dataclass(frozen=True)
class SCRRule:
    id: str
    severity: str
    predicate: str
    title: str


@dataclass(frozen=True)
class SchemaModel:
    objects: Tuple[ObjectSpec, ...]
    fields: Tuple[FieldSpec, ...]
    routes: Tuple[RouteRule, ...]
    edges: Tuple[Edge, ...]
    bundles: Tuple[BundleSpec, ...]
    protected_paths: Tuple[str, ...]
    schema_paths: Tuple[str, ...]
    scr_rules: Tuple[SCRRule, ...]
    source_dir: Path
    fingerprint: str

    def bundle(self, name: str) -> Optional[BundleSpec]:
        for b in self.bundles:
            if b.name == name:
                return b
        return None

    def is_protected(self, rel_path: str) -> bool:
        return rel_path in self.protected_paths


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.Lock()
_CACHE: Dict[Path, Tuple[float, SchemaModel]] = {}


def _schema_dir_mtime(schema_dir: Path) -> float:
    """Max mtime over every .yaml file in schema_dir. Missing dir -> 0.0."""
    if not schema_dir.is_dir():
        return 0.0
    latest = 0.0
    for name in sorted(os.listdir(schema_dir)):
        if not name.endswith(".yaml"):
            continue
        p = schema_dir / name
        try:
            m = p.stat().st_mtime
            if m > latest:
                latest = m
        except OSError:
            continue
    return latest


def _fingerprint(schema_dir: Path) -> str:
    """SHA-256 over the concatenated bytes of every YAML file, sorted by name.
    Used for the render-header signature so ``schema-lint`` can detect drift
    between REGISTRY.md rendered sections and the YAML source of truth.
    """
    import hashlib
    h = hashlib.sha256()
    for name in sorted(os.listdir(schema_dir)):
        if not name.endswith(".yaml"):
            continue
        p = schema_dir / name
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        try:
            h.update(p.read_bytes())
        except OSError:
            pass
        h.update(b"\x00")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _read_yaml(p: Path) -> Dict[str, Any]:
    if not _HAVE_YAML:
        raise SchemaError(
            "PyYAML is required to load orchestration-os/schema/. "
            "Install pyyaml or run with a Python env that includes it."
        )
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise SchemaError(f"missing schema file: {p}") from e
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        raise SchemaError(f"invalid YAML in {p}: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SchemaError(f"expected mapping at top of {p}, got {type(data).__name__}")
    return data


def _load_objects(schema_dir: Path) -> Tuple[ObjectSpec, ...]:
    data = _read_yaml(schema_dir / "objects.yaml")
    rows = data.get("objects", [])
    if not isinstance(rows, list):
        raise SchemaError("objects.yaml:objects must be a list")
    out: List[ObjectSpec] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SchemaError(f"objects.yaml row {i} is not a mapping")
        out.append(ObjectSpec(
            obj=str(row.get("obj", "")),
            file=str(row.get("file", "")),
            pk=str(row.get("pk", "")),
            reader=str(row.get("reader", "")),
            writer=str(row.get("writer", "")),
            append_only=bool(row.get("append_only", False)),
        ))
    return tuple(out)


def _load_fields(schema_dir: Path) -> Tuple[FieldSpec, ...]:
    data = _read_yaml(schema_dir / "fields.yaml")
    rows = data.get("fields", [])
    if not isinstance(rows, list):
        raise SchemaError("fields.yaml:fields must be a list")
    out: List[FieldSpec] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SchemaError(f"fields.yaml row {i} is not a mapping")
        out.append(FieldSpec(
            obj=str(row.get("obj", "")),
            field=str(row.get("field", "")),
            type=str(row.get("type", "")),
            req=str(row.get("req", "")).lower(),
            constraint=str(row.get("constraint", "")),
            fk=str(row.get("fk", "")),
        ))
    return tuple(out)


def _load_routes(schema_dir: Path) -> Tuple[RouteRule, ...]:
    data = _read_yaml(schema_dir / "routing.yaml")
    rows = data.get("routes", [])
    if not isinstance(rows, list):
        raise SchemaError("routing.yaml:routes must be a list")
    out: List[RouteRule] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SchemaError(f"routing.yaml row {i} is not a mapping")
        out.append(RouteRule(
            file=str(row.get("file", "")),
            tier=str(row.get("tier", "")),
            bundle=str(row.get("bundle", "")),
            note=str(row.get("note", "")),
        ))
    return tuple(out)


def _load_edges(schema_dir: Path) -> Tuple[Edge, ...]:
    data = _read_yaml(schema_dir / "edges.yaml")
    rows = data.get("edges", [])
    if not isinstance(rows, list):
        raise SchemaError("edges.yaml:edges must be a list")
    out: List[Edge] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SchemaError(f"edges.yaml row {i} is not a mapping")
        out.append(Edge(
            source=str(row.get("source", "")),
            type=str(row.get("type", "")),
            target=str(row.get("target", "")),
        ))
    return tuple(out)


def _load_bundles(schema_dir: Path) -> Tuple[BundleSpec, ...]:
    data = _read_yaml(schema_dir / "bundles.yaml")
    rows = data.get("bundles", [])
    if not isinstance(rows, list):
        raise SchemaError("bundles.yaml:bundles must be a list")
    out: List[BundleSpec] = []
    known_top = {"name", "trigger", "args", "validates", "writes", "append",
                 "notify", "returns", "inline"}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SchemaError(f"bundles.yaml row {i} is not a mapping")
        extras = {k: v for k, v in row.items() if k not in known_top}
        out.append(BundleSpec(
            name=str(row.get("name", "")),
            trigger=str(row.get("trigger", "")),
            args=tuple(str(a) for a in (row.get("args") or [])),
            validates=tuple(str(v) for v in (row.get("validates") or [])),
            writes=dict(row.get("writes") or {}),
            append=dict(row.get("append") or {}),
            notify=row.get("notify") if isinstance(row.get("notify"), dict) else None,
            returns=str(row.get("returns", "")),
            inline=bool(row.get("inline", False)),
            extras=extras,
        ))
    return tuple(out)


def _load_protected(schema_dir: Path) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    data = _read_yaml(schema_dir / "protected.yaml")
    pp = data.get("protected_paths", [])
    sp = data.get("schema_paths", [])
    if not isinstance(pp, list) or not isinstance(sp, list):
        raise SchemaError("protected.yaml: protected_paths and schema_paths must be lists")
    return tuple(str(x) for x in pp), tuple(str(x) for x in sp)


def _load_scr_rules(schema_dir: Path) -> Tuple[SCRRule, ...]:
    data = _read_yaml(schema_dir / "scr_rules.yaml")
    rows = data.get("scr_rules", [])
    if not isinstance(rows, list):
        raise SchemaError("scr_rules.yaml:scr_rules must be a list")
    out: List[SCRRule] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SchemaError(f"scr_rules.yaml row {i} is not a mapping")
        out.append(SCRRule(
            id=str(row.get("id", "")),
            severity=str(row.get("severity", "")).upper(),
            predicate=str(row.get("predicate", "")),
            title=str(row.get("title", "")),
        ))
    return tuple(out)


def load(schema_dir: Path, *, force: bool = False) -> SchemaModel:
    """Load the full schema model from ``schema_dir``.

    The result is cached; re-invocations return the cached model unless the
    directory mtime has advanced (or ``force=True``). Thread-safe.
    """
    schema_dir = Path(schema_dir).resolve()
    if not force:
        with _CACHE_LOCK:
            cached = _CACHE.get(schema_dir)
            if cached is not None and cached[0] >= _schema_dir_mtime(schema_dir):
                return cached[1]

    objects = _load_objects(schema_dir)
    fields_ = _load_fields(schema_dir)
    routes = _load_routes(schema_dir)
    edges = _load_edges(schema_dir)
    bundles = _load_bundles(schema_dir)
    protected_paths, schema_paths = _load_protected(schema_dir)
    scr_rules = _load_scr_rules(schema_dir)

    model = SchemaModel(
        objects=objects,
        fields=fields_,
        routes=routes,
        edges=edges,
        bundles=bundles,
        protected_paths=protected_paths,
        schema_paths=schema_paths,
        scr_rules=scr_rules,
        source_dir=schema_dir,
        fingerprint=_fingerprint(schema_dir),
    )

    with _CACHE_LOCK:
        _CACHE[schema_dir] = (_schema_dir_mtime(schema_dir), model)
    return model


def invalidate(schema_dir: Optional[Path] = None) -> None:
    """Drop the cached model for ``schema_dir`` (or all cached models)."""
    with _CACHE_LOCK:
        if schema_dir is None:
            _CACHE.clear()
        else:
            _CACHE.pop(Path(schema_dir).resolve(), None)
