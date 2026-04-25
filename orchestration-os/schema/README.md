# orchestration-os/schema/ — Tier A Machine Schema

This directory holds the typed, machine-readable schema that the NightClaw
engine consults. It is the **single source of truth** for object structure,
field contracts, write routing, dependency edges, bundle specifications,
protected paths, and self-consistency rule metadata.

As of Merge 1 of the deterministic-first revamp, these YAML files are
written and a `schema-render` command regenerates the corresponding sections
of `orchestration-os/REGISTRY.md`. Merge 1 preserves existing engine
behaviour — the R5 bundle executor still reads REGISTRY.md. Merge 2 flips
the engine to read these YAML files directly and enforces R2/R3/R4/CL5
gates at every MUTATE site.

## Files

| File | REGISTRY.md section | Purpose |
|---|---|---|
| `objects.yaml`   | R1 | Object types: file location, PK, reader, writer, append-only flag |
| `fields.yaml`    | R2 | Per-object field contracts: type, required, enum/format, FK |
| `routing.yaml`   | R3 | File → tier → bundle write routing table |
| `edges.yaml`     | R4 | Typed dependency edges: READS / WRITES / VALIDATES / TRIGGERS / REFERENCES / AUTHORIZES |
| `bundles.yaml`   | R5 | Bundle specifications: TRIGGER, ARGS, VALIDATES, WRITES, APPEND, NOTIFY, RETURNS |
| `protected.yaml` | R3 PROTECTED tier + CL5 | Protected paths (single list, used by both route gate and CL5 audit) |
| `scr_rules.yaml` | R6 | Self-consistency rule IDs, severity, predicate names |

## Authorship

Hand-edit these YAML files. Then run:

```
python3 scripts/nightclaw-ops.py schema-render
```

This regenerates the rendered sections of `orchestration-os/REGISTRY.md`.
Never hand-edit the rendered sections directly; the render header carries
a fingerprint that `schema-lint` verifies.

## Bootstrap self-reference

These schema files are themselves listed in `protected.yaml` — the only
writer is `{OWNER}` plus the deterministic `schema-render` command. The
engine resolves the bootstrap by treating schema files as immutable during
any run that is not explicitly a schema-edit run.
