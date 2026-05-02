# NightClaw

NightClaw is a file-based operating protocol for OpenClaw workspaces. OpenClaw
starts sessions, schedules crons, manages model/provider settings, and provides
the agent runtime. NightClaw provides the workspace files, prompts, schema,
commands, logs, and gates used by those sessions.

**First-time operator?** Jump to [§ Install](#install). The commands shown later
in this README under §Bootstrap and §Development rules are for repo
maintainers and maintenance LLMs — they are not part of the install path.

Current validated package shape:

```text
377 passed, 1 skipped
Smoke Test: 18 passed 0 failed
```

## Why NightClaw

OpenClaw is the runtime — sessions, crons, models, providers. NightClaw is the
workspace and protocol layer that sits on top of it. The split matters:

- **Reference implementation, not a framework.** NightClaw is one concrete
  realization of the protocol. The methods are intentionally customizable —
  swap in your own domain-specific bundles, predicates, prompts, and phase
  rules without forking the engine.
- **Compounding workspace knowledge.** Memory, audit, change log, project
  state, and notifications accumulate as files in the workspace. Every pass
  starts from what previous passes wrote down, not from scratch.
- **Inspectable gates, not vibes.** Projects, phases, state transitions,
  audit entries, protected paths, and schema rules are all expressed as
  typed YAML and checked by deterministic commands (`schema-lint`,
  `scr-verify`, `validate-bundles`, `integrity-check`). What the LLM is
  allowed to do is what the schema says.
- **Model- and provider-portable.** No model lock-in. The worker switches
  tier between passes from `MODEL-TIERS.md`; the manager pins a stronger
  model via cron flag. Any provider OpenClaw supports works.

This repo is one such NightClaw-style implementation. It is exploratory
engineering and architecture aligned with open source and OpenClaw, not a
product — others can adopt it as-is or fork the bundles, prompts, schema,
and predicates into their own NightClaw-style protocol.

### Early test demos

Two early test/demo links that motivated the design — not product promises,
just illustrations of the kind of work autonomous passes can compound toward:

- <https://www.tokenarch.com/cinematic>
- <https://www.tokenarch.com/nightclaw-demo.html>

## How interaction works

NightClaw runs as two scheduled OpenClaw cron sessions over a workspace you
own on disk. After install you mostly approve or reject what the sessions
surface; you don't drive the pass loop yourself.

**Setup the operator does once, by hand:**

1. Run `bash scripts/install.sh` from the workspace root. It is interactive
   and substitutes `{OWNER}`, `{WORKSPACE_ROOT}`, `{OPENCLAW_CRON_DIR}`,
   `{OPENCLAW_LOGS_DIR}`, `{PLATFORM}`, and other install placeholders
   across the workspace; writes the three model tier IDs into
   `MODEL-TIERS.md` when provided; then generates the initial
   protected-file hashes in `audit/INTEGRITY-MANIFEST.md`.
2. Open `SOUL.md`, replace `{DOMAIN_ANCHOR}` with 2–3 sentences describing
   your domain focus, and re-sign: `bash scripts/resign.sh SOUL.md`.
   `SOUL.md` is a protected file, so the new hash must be re-recorded
   before any session will run.
3. Schedule the two crons described in `DEPLOY.md` § Step 5: a worker
   (`session:nightclaw-worker`) and a manager (`session:nightclaw-manager`).
   Each fires as a fresh, non-persistent OpenClaw session — no in-memory
   state carries between runs; everything they need to "remember" is in
   the workspace files.

**What each session does on its own:**

Both prompts follow a structured T-step pass lifecycle (T0–T9 with
substeps) where each step calls a deterministic engine command that
curates only the context that step needs, so a fresh session does not
re-load irrelevant history.

- The **worker** executes its prompt (`orchestration-os/CRON-WORKER-PROMPT.md`)
  end-to-end: integrity check, lock acquisition, dispatch, one objective at
  T4, validate, state update, optional OS improvement, session close. It
  picks the top-priority project from `ACTIVE-PROJECTS.md` via the
  deterministic `dispatch` command.
- The **manager** runs less often, reviews recent worker activity, surfaces
  escalations, runs anomaly/spine checks on the audit log, and — when the
  workspace is idle — does strategic-direction work (T3.5): reviewing draft
  proposals, suggesting follow-on projects, or flagging a stale Domain
  Anchor.
- When no projects exist or all are paused/blocked, the worker's idle cycle
  (Tier 4 in `orchestration-os/OPS-IDLE-CYCLE.md`) can draft a new project
  proposal grounded in the `SOUL.md` Domain Anchor and `USER.md` constraints.
  The proposal is written as `PROJECTS/<slug>/LONGRUNNER-DRAFT.md` and
  surfaced in `NOTIFICATIONS.md` for you to approve or decline. The exact
  research/grounding shape is prompt-guided, not hardcoded — the engine
  enforces where it gets written, not how the proposal is reasoned.

**What you actually do day to day:**

- **Approve or reject new projects.** Rename `LONGRUNNER-DRAFT.md` →
  `LONGRUNNER.md` and add a row to `ACTIVE-PROJECTS.md` to approve, or
  delete the draft to decline. The `nightclaw-admin` helper script wraps
  these moves.
- **Approve or reject phase escalations.** When a phase's stop conditions
  evaluate TRUE, the worker writes `phase.successor` and fires the
  `phase_transition` bundle, which surfaces a HIGH-priority entry to
  `NOTIFICATIONS.md` and sets `escalation_pending` on the project.
- **Provide pre-approvals** in `orchestration-os/OPS-PREAPPROVAL.md` for
  classes of action that should run unattended (e.g. extended file writes,
  phase auto-advance with declared boundaries). The worker's `pa_invoke`
  bundle validates scope/boundary/expiry against the planned action before
  executing — out-of-scope use is blocked and re-surfaced.
- **Provide manual guidance** when the manager surfaces a strategic
  direction note, a quality concern, or a stale Domain Anchor. Edits to
  `SOUL.md` or `USER.md` are followed by `bash scripts/resign.sh <file>`
  on the protected files.

The manager's draft-review notification phrases its read on a draft as
"strong draft" or "weak draft" (see `CRON-MANAGER-PROMPT.md` T3.5-A) —
it is a protocol-guided judgment surfaced as a recommendation, not a
numeric score. Pass quality is recorded as the
`last_pass.quality` enum (`STRONG | ADEQUATE | WEAK | FAIL`) by the
worker at T5.5.

**State that crosses sessions, by file:**

- Project state, phases, escalation_pending, and the next pass plan live
  in `PROJECTS/<slug>/LONGRUNNER.md` (`last_pass.*`, `next_pass.*`,
  `phase.*` fields — see `orchestration-os/schema/fields.yaml`).
- Field-level mutations are recorded in `audit/CHANGE-LOG.md` whenever a
  bundle write changes a value; step-level events go to
  `audit/AUDIT-LOG.md` (append-only); session bookkeeping goes to
  `audit/SESSION-REGISTRY.md`.
- Pending decisions for the operator surface in `NOTIFICATIONS.md`.
- OS-level lessons the worker learns at T7 are appended to the relevant
  `orchestration-os/OPS-*.md` doctrine files (e.g.
  `OPS-KNOWLEDGE-EXECUTION.md`, `OPS-FAILURE-MODES.md`,
  `OPS-QUALITY-STANDARD.md`) per the gate in the worker prompt.

**Model tiering across fresh sessions.** Because each cron run is a fresh
session, the current pass cannot keep state in memory for the next one.
Instead, the worker writes its planned `next_pass.model_tier`
(`lightweight | standard | heavy`) into the project's `LONGRUNNER.md`,
and at T9.5 calls `set-model-tier` so OpenClaw's platform default model
for the next worker session matches that tier via `MODEL-TIERS.md`. The
manager cron is unaffected — it pins its own model via `--model` on the
cron line.

**Multiple projects in one workspace.** `ACTIVE-PROJECTS.md` is the
dispatch table; the engine's `dispatch` command applies the
status/`escalation_pending`/priority filtering deterministically. If the
top project is blocked awaiting an approval or escalation, dispatch
selects the next eligible row instead of consuming LLM tokens scanning
for it. The same is true at T1.5 when no project is dispatchable: the
`scan-notifications` and `idle-triage` commands route the pass to the
right idle tier without the model having to read the full doctrine.

**Why this saves tokens.** Routing-critical context (next pass objective,
model tier, context budget, tool requirements, last-pass quality, phase
stop condition) is curated by the deterministic
`longrunner-extract` command — the prompt instructs the worker to consume
those key=value lines before reading the full LONGRUNNER, and to read the
full file only at T4 when narrative context is actually required. Pulling
project state and routing decisions through engine commands rather than
free-form file reads is what keeps fresh sessions from re-loading
irrelevant history.

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

## Install

NightClaw is an overlay on top of an existing OpenClaw workspace. The install
path is: install OpenClaw, create the workspace, copy NightClaw on top, run
`install.sh` from the workspace root, then complete the post-install checklist.

### Requirements

```text
OpenClaw 2026.4.5+   (the runtime — install this first)
Python 3.10+
PyYAML
pytest               (for test/gate runs)
```

### Step 1 — Install OpenClaw and create a workspace

Follow the upstream OpenClaw install for your platform, then create the
workspace directory NightClaw will live in (default: `~/.openclaw/workspace`).

### Step 2 — Copy NightClaw into the OpenClaw workspace

Copy or unpack the NightClaw repo contents directly into your OpenClaw
workspace root — the NightClaw files and folders sit alongside whatever
OpenClaw already created there. Do not nest them in a `nightclaw/`
subdirectory.

### Step 3 — Run `install.sh` from the workspace root

```bash
# Run from: the OpenClaw workspace root (where SOUL.md now lives)
bash scripts/install.sh
```

`install.sh` is the install entrypoint. It substitutes placeholders across
the workspace, writes `MODEL-TIERS.md` values when provided, generates the
initial SHA-256 hashes for protected files, and creates required
directories. The script is interactive — it prompts for owner, workspace
root, cron/logs paths, platform, and the three model tier IDs.

### Step 4 — Post-install checklist

Work through these in order, from the workspace root:

1. **Set the SOUL domain anchor.** Open `SOUL.md`, replace `{DOMAIN_ANCHOR}`
   with 2–3 sentences describing your domain focus, then re-sign:
   ```bash
   bash scripts/resign.sh SOUL.md
   ```
2. **Confirm `USER.md`.** Fill in name, timezone, and any domain
   restrictions. If you change it, re-sign:
   ```bash
   bash scripts/resign.sh USER.md
   ```
3. **Confirm `MODEL-TIERS.md`.** If you skipped any tier during install, edit
   the file directly and set the model IDs. `MODEL-TIERS.md` is not a
   protected file, so no re-sign is needed.
4. **Verify integrity and validate the workspace:**
   ```bash
   bash scripts/verify-integrity.sh        # must show 11/11 PASS
   bash scripts/validate.sh
   python3 scripts/nightclaw-ops.py schema-lint
   python3 scripts/nightclaw-ops.py scr-verify
   python3 scripts/nightclaw-ops.py validate-bundles
   python3 scripts/nightclaw-ops.py integrity-check
   pytest tests/ -q
   ```
5. **Continue to `DEPLOY.md` for runtime setup.** Cron creation, model
   provider configuration, heartbeat tuning, and emergency stop live there:
   - `DEPLOY.md` § Step 5 — Configure Two Crons
   - `DEPLOY.md` § Model Configuration
   - `DEPLOY.md` § Heartbeat Configuration
   - `DEPLOY.md` § Uninstall & Emergency Stop

The cron/runtime details deliberately are not duplicated here. If you skip
the `DEPLOY.md` handoff, NightClaw will not run on its own — there will be
no scheduled worker or manager.

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

## Smoke test

Run the smoke test against a packaged copy, not the working repo. The
checkout directory name is not assumed — replace `<repo-dir>` with whatever
your local checkout is named (commonly `nightclaw`):

```bash
# Run from: inside your NightClaw checkout
REPO_DIR=$(basename "$PWD")
cd ..
zip -rq /tmp/nightclaw-smoke.zip "$REPO_DIR" \
  -x "$REPO_DIR/.git/*" \
     "$REPO_DIR/__pycache__/*" \
     "$REPO_DIR/**/__pycache__/*" \
     "$REPO_DIR/.pytest_cache/*" \
     "$REPO_DIR/**/.pytest_cache/*"

cd "$REPO_DIR"
bash scripts/smoke-test.sh /tmp/nightclaw-smoke.zip
```

`scripts/smoke-test.sh` itself extracts the zip into a `mktemp -d` and
locates `SOUL.md` to find the workspace root, so the top-level folder name
inside the zip does not matter.

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
