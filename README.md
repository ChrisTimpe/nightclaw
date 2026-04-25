# NightClaw

NightClaw is a file-based operating protocol for OpenClaw workspaces. OpenClaw
starts sessions, schedules crons, manages model/provider settings, and provides
the agent runtime. NightClaw provides the workspace files, prompts, schema,
commands, logs, and gates used by those sessions.

The repo is designed to be inspected through the code and the schema, not
through README prose alone. For a developer or maintenance LLM, start with:

```bash
python3 scripts/nightclaw-ops.py bootstrap --track=general
python3 scripts/nightclaw-ops.py schema-lint
python3 scripts/nightclaw-ops.py schema-sync
python3 scripts/nightclaw-ops.py scr-verify
python3 scripts/nightclaw-ops.py validate-bundles
python3 scripts/nightclaw-ops.py integrity-check
pytest tests/ -q
```

Current validated package shape:

```text
377 passed, 1 skipped
Smoke Test: 18 passed 0 failed
```

## Use at your own risk

NightClaw is intended for technical users who are comfortable reviewing and
configuring local automation tools. Initial setup and configuration are
expected.

The project was tested personally by its maintainer and revised with the time
and resources available to prepare it as a public open source contribution. The
core workflow was proven effective under the core engine before the bridge and
monitor additions, but behavior depends on the local environment, model setup,
workspace configuration, and operator judgment.

Results will vary. Nothing is guaranteed. Review the configuration, protect
credentials, monitor automated runs, and validate outputs before relying on
them. NightClaw is provided under the Apache License 2.0 on an "AS IS" basis,
without warranties or conditions of any kind.

## Repo layout

| Path | Purpose |
|---|---|
| `scripts/nightclaw-ops.py` | CLI entrypoint into `nightclaw_engine.commands`. |
| `nightclaw_engine/` | Core command dispatcher, schema loader, gates, bundle executor, render logic, longrunner helpers, and SCR driver. |
| `orchestration-os/` | Cron prompts, operational policies, registry, schema YAML, templates, and runtime doctrine. |
| `orchestration-os/schema/` | Machine-readable source for objects, fields, routes, edges, bundles, SCR rules, and protected paths. |
| `audit/` | Append logs, change log, approval chain, integrity manifest, and session registry. |
| `PROJECTS/` | Per-project LONGRUNNER state, phase files, and outputs. |
| `memory/` | Daily/session memory logs. Fresh installs may start with only `memory/README.md` and `.gitkeep`. |
| `MEMORY.md` | Protected curated long-term memory injected by OpenClaw sessions. |
| `internal_enhancement/` | Maintainer-only architecture notes, current-pass notes, and LLM bootstrap track definitions. |
| `nightclaw_bridge/` | Optional local bridge process for monitor/runtime views. |
| `nightclaw_monitor/` | Optional monitor-side state and handlers. |
| `apps/monitor/` | Optional browser monitor HTML assets. |
| `tests/` | Unit, core, bridge/monitor, and engine E2E tests. |

Root-level Markdown files are not all OpenClaw platform files. Some are
NightClaw workspace state intentionally kept at the root because OpenClaw
sessions, owners, or operators need to see or edit them directly.

## Runtime roles

NightClaw assumes two scheduled OpenClaw sessions:

| Session | Main prompt | Role |
|---|---|---|
| Worker | `orchestration-os/CRON-WORKER-PROMPT.md` | Selects/executes project work, updates project state, appends audit/memory entries. |
| Manager | `orchestration-os/CRON-MANAGER-PROMPT.md` | Reviews state, checks quality/direction, detects anomalies, manages pruning/review work. |

Both sessions read `orchestration-os/CRON-HARDLINES.md` first in the provided
cron command examples. `LOCK.md` is the shared workspace lock used by the
startup/close commands and by the smoke test.

There is no separate orchestrator cron. `orchestration-os/ORCHESTRATOR.md`
documents the distributed dispatch and phase-transition model used by worker,
manager, and manual operator sessions.

## The protocol

The protocol is represented in two forms:

| Form | Location | Use |
|---|---|---|
| Machine source | `orchestration-os/schema/*.yaml` | Loaded by `nightclaw_engine.schema.loader`. |
| Rendered registry | `orchestration-os/REGISTRY.md` | Human-readable registry sections kept in sync by schema commands. |

`REGISTRY.generated.md` is a generated comparison target. The canonical registry
file is `orchestration-os/REGISTRY.md`.

The current schema model contains:

```text
R1 objects: 25
R2 fields: 87
R3 routes: 104
R4 edges: 83
R5 bundles: 8
R6 SCR rules: 11
CL5 protected paths: 11
```

Schema fingerprint for this package:

```text
d2ba158e1c7ad68a4ad6a049f60f6727835d9e609977fc71e5038e43a2f70de0
```

### R1 to R6

| Section | Question answered | Source file |
|---|---|---|
| R1 objects | What state objects exist, where they live, and who reads/writes them? | `objects.yaml` |
| R2 field contracts | What fields exist for each object, and what type/required/enum constraints apply? | `fields.yaml` |
| R3 write routing | What route tier and bundle, if any, is declared for a file path? | `routing.yaml` |
| R4 dependency edges | What files/operations read, write, validate, trigger, reference, or authorize other files/operations? | `edges.yaml` |
| R5 bundles | What named multi-file operations exist, what arguments they take, and what they write/append? | `bundles.yaml` |
| R6 SCR index | What self-consistency rules are declared by ID, severity, predicate, and title? | `scr_rules.yaml` |

The renderer emits R1-R6 plus CL5 protected paths:

```bash
python3 scripts/nightclaw-ops.py schema-render
```

`schema-sync` updates the rendered sections inside `orchestration-os/REGISTRY.md`:

```bash
python3 scripts/nightclaw-ops.py schema-sync
```

`schema-lint` reloads the YAML model and checks that the generated render is
byte-identical to a fresh render:

```bash
python3 scripts/nightclaw-ops.py schema-lint
```

## Query commands

The CLI exposes the schema through small commands:

```bash
python3 scripts/nightclaw-ops.py registry-route README.md
python3 scripts/nightclaw-ops.py cascade-read PROJECTS/example-research/LONGRUNNER.md
python3 scripts/nightclaw-ops.py validate-field OBJ:PROJ last_pass.quality STRONG
python3 scripts/nightclaw-ops.py validate-bundles
```

Meanings:

| Command | What it does |
|---|---|
| `registry-route <path>` | Looks up the first matching R3 route for a relative path. If no route row matches, it prints `ROUTE:UNKNOWN`. |
| `cascade-read <path>` | Lists R4 edges where the path is the source, including glob-expanded project paths. |
| `validate-field <OBJ> <field> <value>` | Checks one value against R2 required/type/enum logic. |
| `validate-bundles` | Parses R5 bundle declarations and checks argument references, guard predicates, and protected write targets. |
| `scr-verify` | Runs the R6 predicate registry and CL5 protected-path check. |

`ROUTE:UNKNOWN` means the route lookup did not find an R3 row for that path. It
does not by itself prove the file is unused. Some read-only doctrine/template
files are referenced by prompts, docs, or tests without being direct mutation
targets.

## Route tiers

R3 route rows use these tiers:

| Tier | Meaning in this repo |
|---|---|
| `PROTECTED` | Listed as protected by R3 and/or CL5. Bundle execution blocks writes to these targets; hashes are checked by `integrity-check`. |
| `APPEND` | Intended append surface. The `append` and `append-batch` commands check the append allowlist and schema route before writing. |
| `STANDARD` | Normal routed file. Some rows specify a bundle; some are standalone. |
| `MANIFEST-VERIFY` | Integrity manifest timestamp update path used by the manifest bundle. |
| `CODE` | Code/UI file route entries used by schema and SCR checks. |

The code path for generic R5 writes is `bundle-exec`. It loads bundle specs
from `orchestration-os/schema/bundles.yaml` through the typed schema model.
There is a deprecated legacy parser over `REGISTRY.md`, but normal execution
uses the YAML-backed model.

## Bundles

R5 bundles are named operations loaded by `bundle-exec`.

Current bundles:

```text
longrunner_update
phase_transition
phase_advance
route_block
surface_escalation
pa_invoke
manifest_verify
session_close
```

Bundle execution resolves declared arguments, evaluates declared guards, writes
known target types, appends configured lines, and emits change-log rows for
mutations where the old and new values differ. The supported write targets are
implemented in `nightclaw_engine/commands/bundle_mutators.py`.

## SCR

SCR means Self-Consistency Rule. R6 declares SCR rule IDs and predicate names.
The predicates live in:

```text
nightclaw_engine/protocol/integrity.py
```

The driver command is:

```bash
python3 scripts/nightclaw-ops.py scr-verify
```

Current `scr-verify` output includes SCR-01 through SCR-11 plus CL5. Some rules
query the typed schema model. Some rules read workspace files such as
`SESSION-REGISTRY.md`, `LOCK.md`, prompt files, or test/code surfaces. SCR-07
prints reference edges as `INFO` for review.

## Protected files

Protected paths are declared in:

```text
orchestration-os/schema/protected.yaml
```

The corresponding file hashes are stored in `audit/INTEGRITY-MANIFEST.md`.

Current protected files:

```text
AGENTS-CORE.md
IDENTITY.md
MEMORY.md
SOUL.md
USER.md
orchestration-os/CRON-HARDLINES.md
orchestration-os/CRON-MANAGER-PROMPT.md
orchestration-os/CRON-WORKER-PROMPT.md
orchestration-os/OPS-AUTONOMOUS-SAFETY.md
orchestration-os/OPS-PREAPPROVAL.md
orchestration-os/REGISTRY.md
```

`integrity-check` computes SHA-256 hashes for these files and compares them to
`audit/INTEGRITY-MANIFEST.md`.

```bash
python3 scripts/nightclaw-ops.py integrity-check
```

After an intentional protected-file edit, use:

```bash
bash scripts/resign.sh <path>
```

## Session files

| File | Role |
|---|---|
| `ACTIVE-PROJECTS.md` | Dispatch table used by worker/manager logic. |
| `PROJECTS/<slug>/LONGRUNNER.md` | Per-project control state. |
| `PROJECTS/<slug>/outputs/` | Project artifacts. |
| `NOTIFICATIONS.md` | Append-oriented owner/operator notification surface. |
| `LOCK.md` | Workspace lock state. |
| `audit/AUDIT-LOG.md` | Step/audit entries. |
| `audit/CHANGE-LOG.md` | Field mutation log emitted by bundle execution. |
| `audit/SESSION-REGISTRY.md` | Session/run registry. |
| `memory/YYYY-MM-DD.md` | Daily/session memory log. |

## Bootstrap for developers

The bootstrap command is for repo maintenance and developer orientation:

```bash
python3 scripts/nightclaw-ops.py bootstrap --track=general
```

Track definitions live in:

```text
internal_enhancement/LLM-BOOTSTRAP.yaml
```

The cron worker and cron manager prompts do not invoke this command and do not
read `internal_enhancement/LLM-BOOTSTRAP.yaml`.

Available tracks:

```text
general
add_bundle
edit_schema
review_pr
add_predicate
extend
fix_bug
```

## Install

Minimum runtime:

```text
Python 3.10+
PyYAML
OpenClaw
```

Test/gate runs also use `pytest`.

Recommended install path:

```bash
bash scripts/install.sh
bash scripts/verify-integrity.sh
bash scripts/validate.sh
python3 scripts/nightclaw-ops.py schema-lint
python3 scripts/nightclaw-ops.py schema-sync
python3 scripts/nightclaw-ops.py scr-verify
python3 scripts/nightclaw-ops.py validate-bundles
python3 scripts/nightclaw-ops.py integrity-check
pytest tests/ -q
```

`install.sh` substitutes install placeholders, writes `MODEL-TIERS.md` values
when provided, and generates initial protected-file hashes.

The domain anchor in `SOUL.md` is intentionally manual. The model tier values
in `MODEL-TIERS.md` can be edited manually if they are not set during install.

See `DEPLOY.md` for OpenClaw model setup, cron examples, heartbeat guidance,
day-to-day operation, and emergency stop notes.

## Smoke test

Run the smoke test against a packaged copy, not the working repo:

```bash
cd ..
zip -rq /tmp/nightclaw-smoke.zip nightclaw \
  -x 'nightclaw/.git/*' \
     'nightclaw/__pycache__/*' \
     'nightclaw/**/__pycache__/*' \
     'nightclaw/.pytest_cache/*' \
     'nightclaw/**/.pytest_cache/*'

cd nightclaw
bash scripts/smoke-test.sh /tmp/nightclaw-smoke.zip
```

The smoke test extracts a clean copy, runs install flow checks, verifies
protected-file hashing, creates a sample project, simulates T0 protected-file
checks, and checks lock behavior.

## Optional monitor

The core runtime does not require the monitor packages.

Optional monitor components:

```text
nightclaw_bridge/
nightclaw_monitor/
apps/monitor/
scripts/start-monitor.sh
```

Tests assert the core engine does not import `nightclaw_bridge` or
`nightclaw_monitor`. The bridge uses subprocess calls to `scripts/nightclaw-ops.py`
and `scripts/nightclaw-admin.sh` for runtime views/actions.

## Development rules

When editing schema:

```bash
python3 scripts/nightclaw-ops.py schema-render
python3 scripts/nightclaw-ops.py schema-sync
python3 scripts/nightclaw-ops.py schema-lint
python3 scripts/nightclaw-ops.py scr-verify
python3 scripts/nightclaw-ops.py validate-bundles
```

If `orchestration-os/REGISTRY.md` changes, re-sign it:

```bash
bash scripts/resign.sh orchestration-os/REGISTRY.md
```

When editing protected files, re-sign the edited file. When editing code, run
the relevant focused tests and then the full suite before packaging.

## Limits

NightClaw does not make model reasoning deterministic. It makes selected
workspace structures inspectable and checkable through files, schema, commands,
tests, and logs.

Some safety rules are behavioral prompt rules, not OS-level or cryptographic
barriers. SHA-256 integrity checks detect protected-file changes between
sessions when `integrity-check` runs. They do not prevent out-of-band filesystem
edits by a user with shell access.

`registry-route` and `cascade-read` expose the declared schema model. They do
not prove that every prose reference in every file is complete or correct.

## Related docs

| File | Purpose |
|---|---|
| `INSTALL.md` | Short pointer to README install section. |
| `DEPLOY.md` | Extended deployment and operations guide. |
| `CONTRIBUTING.md` | Contributor guidance. |
| `SECURITY.md` | Security notes. |
| `internal_enhancement/ARCHITECTURE.md` | Internal maintainer architecture map. |
| `internal_enhancement/CURRENT-PASS.md` | Current validation/handoff notes. |
