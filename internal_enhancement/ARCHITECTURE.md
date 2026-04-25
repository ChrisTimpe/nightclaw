# NightClaw Architecture

**Purpose:** Internal maintainer map. Where every file lives and how the runtime, telemetry, and data tiers wire together. For the **file-level contract** (objects, fields, routing, edges, bundles, predicates), see [`REGISTRY.md`](../orchestration-os/REGISTRY.md) / [`REGISTRY.generated.md`](../REGISTRY.generated.md).

**Scope of this document:** structural. It describes the runtime graph and file categories. It does **not** restate doctrine (`SOUL.md`, `AGENTS-CORE.md`), cron prompts (`orchestration-os/CRON-*-PROMPT.md`), or operational policies (`orchestration-os/OPS-*.md`) — those are canonical where they live.

---

## 0. Surfaces

NightClaw ships five Python artifacts that map to five technical surfaces. The dependency direction between them is one-way; the only thing that can stop a worker pass is a fault in surface 1.

| # | Surface | Files | Role | Required for cron pass? | Imports |
|---|---|---|---|---|---|
| 1 | **Core engine + admin CLI** | `scripts/nightclaw-ops.py` (~107-line forwarder), `nightclaw_engine/` (24 modules, 34 commands) | Authoritative runtime. Dispatches every typed command, executes every bundle, writes every audit row. The R1/R3/R4/R5/R6 object dependency model is built around this surface and the admin CLI workflows in `scripts/nightclaw-admin.sh`. | **Yes — essential.** | stdlib + PyYAML; optionally `nightclaw_ops` (try/except) |
| 2 | **Telemetry emitter** | `nightclaw_ops/telemetry.py`, `nightclaw_ops/lifecycle.py` (~250 LOC, two files) | Fire-and-forget JSON emitter to `/tmp/nightclaw-ops.sock`. Engine imports it behind `try/except`; if the socket has no listener (or the package is missing), `emit_step` silently no-ops and the engine continues. | No — fail-open adjunct. | stdlib only |
| 3 | **Bridge server** | `nightclaw_bridge/` (12 modules) | Separate process. Reads the ops socket, fans out to WebSocket clients, optionally serves `apps/monitor/*.html` over HTTP. **Does not import `nightclaw_engine`.** Spawns `scripts/nightclaw-admin.sh` and `scripts/nightclaw-ops.py` as subprocesses for admin commands. | No — optional Phase 2. | stdlib + `websockets`; reads ops socket |
| 4 | **Monitor UI** | `apps/monitor/*.html` (4 files), `nightclaw_monitor/` (6 modules) | Live reflection over WebSocket. Operator-facing console with token-authenticated RW admin panel that calls the bounded admin-script vocabulary in surface 3. Layout is hand-authored; activation/state is dynamic. | No — visualization only. | Browser only (UI); stdlib (UI store package) |
| 5 | **LLM bootstrap** | `internal_enhancement/LLM-BOOTSTRAP.yaml` + `nightclaw_engine/commands/bootstrap.py` (engine-registered command) | Engine-exposed command (`nightclaw-ops.py bootstrap [--track=…]`) that projects scoped repo context for a human or LLM working **on** NightClaw. The cron worker and cron manager never invoke it (CRON-*-PROMPT.md does not reference it). The YAML lives **outside** `orchestration-os/schema/` so edits do not rotate the schema fingerprint. | No — maintainer orientation. | engine command + PyYAML |

**Dependency direction is strictly:**

```
                    +----------------+      try/except       +----------------+
1. Core engine -----+ admin CLI      +-- (no-op on absence) -+ 2. Telemetry   |
                    |                |                       |    emitter     |
                    +----------------+                       +-------+--------+
                            ^                                        |
                            |                                        | UNIX socket
                            |                                        v
                    subprocess shell-out                     +----------------+
                    (admin commands only)                    | 3. Bridge      |
                            |                                |    server      |
                            +-- WebSocket / postMessage ---->+----------------+
                                                                     |
                                                                     v
                                                             +----------------+
                                                             | 4. Monitor UI  |
                                                             +----------------+
```

5. **LLM bootstrap** is parallel: invoked by a human via `nightclaw-ops.py bootstrap`, never by surfaces 2–4.

**Reading the dependency direction the other way:** surfaces 2, 3, 4 know about surface 1; surface 1 knows nothing about surfaces 2, 3, 4 except for an optional, fail-open import of surface 2's emitter. INV-15 (`tests/core/test_reachability.py`) enforces this DAG at the Python-symbol level.

**Operational consequences:**

- The cron worker and cron manager run identical T0→T9 sequences whether the bridge is up or down.
- Disabling the monitor (delete `nightclaw_bridge/`, `nightclaw_monitor/`, `apps/monitor/`) does not affect any test in `tests/core/` or `tests/engine_e2e/`.
- The monitor admin panel is a thin remote control for `scripts/nightclaw-admin.sh` — every RW verb the panel can issue can also be run from a terminal by the owner. Privileged writes still flow through `audit/AUDIT-LOG.md` and `audit/CHANGE-LOG.md` in the same format the cron sessions use.

---

## 1. Runtime topology

The runtime is a closed loop: two crons invoke the executor, the executor reads governance and writes audited state, the state machine advances.

```
     +---------------------+        +---------------------+
     |   Cron: WORKER      |        |   Cron: MANAGER     |
     |   lightweight model |        |   capable model     |
     |   ~every 3h         |        |   ~once / day       |
     +----------+----------+        +----------+----------+
                |                              |
                |   reads CRON-HARDLINES.md    |
                |   reads CRON-*-PROMPT.md     |
                v                              v
     +--------------------------------------------------+
     |           scripts/nightclaw-ops.py               |
     |           (~107-line thin dispatcher)             |
     |   from nightclaw_engine import commands          |
     |   commands.main()                                |
     +----------------------+---------------------------+
                            |
                            v
     +--------------------------------------------------+
     |              nightclaw_engine                    |
     |                                                  |
     |   commands/    — 11 cmd modules + dispatcher     |
     |   engine/      — gates, longrunner, render       |
     |   schema/      — SchemaModel, PhaseMachine       |
     |   protocol/    — SCR predicates, integrity       |
     +------+--------------------+----------------------+
            |                    |
            | reads              | writes
            v                    v
  +------------------+   +-----------------------------+
  |  READS (Tier A)  |   |  WRITES (runtime state)     |
  |                  |   |                             |
  |  orchestration-  |   |  audit/AUDIT-LOG.md         |
  |    os/schema/    |   |  audit/CHANGE-LOG.md        |
  |    *.yaml (7)    |   |  audit/SESSION-REGISTRY.md  |
  |  REGISTRY.md     |   |  audit/INTEGRITY-MANIFEST.md|
  |  ACTIVE-PROJECTS |   |  NOTIFICATIONS.md           |
  |                  |   |  PROJECTS/*/LONGRUNNER.md   |
  |  Tier C:         |   |  memory/YYYY-MM-DD.md       |
  |  PROJECTS/*/     |   |  LOCK.md                    |
  |    phases.yaml   |   |                             |
  +------------------+   +-----------------------------+
```

**Invariants:**
- The LLM never composes raw writes. It invokes **bundles** (R5) by name; the engine evaluates VALIDATES, executes WRITES atomically, emits APPEND rows.
- Every session starts with `integrity-check` against `audit/INTEGRITY-MANIFEST.md`. SHA-256 divergence halts before the first governance read.
- The engine is pure Python. Schema and phase machines are YAML. Doctrine is Markdown. No code in doctrine; no doctrine in code.

---

## 2. Telemetry topology

A **parallel, side-channel** stream: every tier boundary in an engine run is emitted as a structured event. The monitor UIs subscribe via WebSocket and render live session state. **The worker path never blocks on telemetry** — the emitter is fire-and-forget with a bounded queue.

> **Deployment note — telemetry is optional.** Everything in this section
> (`nightclaw_bridge/`, `nightclaw_monitor/`, `apps/monitor/*.html`) is a
> Phase 2 add-on. The core runtime in §1 runs to completion without the
> bridge process present. If the UNIX socket is absent, `emit_step` drops
> the event and the tier continues — see §2 invariants below. First-time
> operators should install Phase 1 only; see
> [`INSTALL.md § Phased Install`](INSTALL.md#phased-install--what-you-need-vs-whats-optional).

```
  +------------------------------------+
  |   scripts/nightclaw-ops.py         |
  |   (per-run: sets NIGHTCLAW_RUN_ID) |
  +-------------------+----------------+
                      |
                      | nightclaw_ops.lifecycle.step()
                      | wraps each CLI tier execution
                      v
  +--------------------------------------------+
  |        nightclaw_ops.telemetry             |
  |                                            |
  |  emit_step(tier, cmd, run_id, slug,        |
  |            session, exit_code)             |
  |                                            |
  |  queue(512) -> daemon thread               |
  |  _SEND_TIMEOUT = 0.25s                     |
  |  atexit flush 0.050s                       |
  |  fire-and-forget; never raises             |
  +--------------------+-----------------------+
                       |  JSON lines
                       v
          /tmp/nightclaw-ops.sock   (UNIX socket;
              NIGHTCLAW_OPS_SOCK     override via env)
                       |
                       v
  +--------------------------------------------+
  |          nightclaw_bridge.server           |
  |                                            |
  |  handle_ops_ingest:                        |
  |    read line -> json.loads                 |
  |    is_opsstepevent(payload)                |
  |    repo.append_event(payload)              |
  |    await broadcast(payload)                |
  |                                            |
  |  ALLOWED_TIERS = {T0, T1, T1.5, T2, T2.5,  |
  |    T2.7, T3, T3.5, T4, T5, T5.5, T6, T7,   |
  |    T7a-d, T8, T8.3, T8.5, T9}              |
  |                                            |
  |  SessionRepository:                        |
  |    FileSessionRepository (default)         |
  |    MemorySessionRepository (tests)         |
  +--------------------+-----------------------+
                       |
                       |  WebSocket
                       v
       ws://127.0.0.1:${bridgePort}/ws        (event stream)
       ws://127.0.0.1:${bridgePort}/sessions  (sessions feed)
                       |
                       v
  +--------------------------------------------+
  |          nightclaw_monitor.store           |
  |                                            |
  |  MonitorStore (canonical) — consumes       |
  |    validated bridge payloads               |
  |  Store (legacy) — back-compat for older    |
  |    HTML clients                            |
  +--------------------+-----------------------+
                       |
                       v
  +--------------------------------------------+
  |              apps/monitor/                 |
  |                                            |
  |  nightclaw-monitor.html      (WS: /ws)     |
  |  nightclaw-sessions.html     (WS: /sessions)|
  |  owner.html                  (WS: /ws)     |
  |                                            |
  |  port config fetched from nc_config.json   |
  +--------------------------------------------+
```

**Invariants:**
- The bridge validates every payload with `is_opsstepevent` and rejects unknown tiers. Only tiers in `ALLOWED_TIERS` cross the boundary.
- The engine path does not import the bridge or monitor. If the socket is absent, `emit_step` drops the event and the tier continues. Telemetry is observational, never prescriptive.
- Test-time `BrokenPipeError` from the emitter is expected and harmless — tests pass green.

### 2.1 Event types carried over the WebSocket

The bridge→browser stream is a typed event protocol. The monitor clients dispatch on `ev.type`:

| Event type | Emitted at | Carries | Client effect |
|---|---|---|---|
| `connect_ack` / `read_connect_ack` | WS handshake | `privilege` (`rw` / `ro` / `none`), protocol version `v` | Sets the `AUTH:` badge and toggles read-only affordances |
| `ops_step` | Every T-step entry/exit | `run_id`, `tier`, `cmd`, `slug`, `t_emitted`, `exit_code?` | Advances the session-steps panel; pulses the active T-step |
| `t4_heartbeat` | While T4 EXECUTE is in flight | `elapsed_seconds` | Drives the live T4 wall-clock counter |
| `bundle_exec_result` | End of every bundle-exec | `bundle_name`, `mutation_count`, `diff_uri?` | Appends to the bundle history panel with `[diff]` affordance |
| `field_change` | Every state-file field mutation | `file`, `field`, `old_val`, `new_val` | Appends to the field-changes diff log |
| `notification` | T1 / T2 / T5 / T8 surfacing | `severity`, `body`, `ts` | Enqueues in the notifications panel |
| `session_open` | T0 entry | `run_id`, `agent_type` (worker/manager), `ts` | Resets step/bundle/SCR/diff panels for the new run |
| `session_close` | T9 entry | `run_id`, `outcome` (clean/crash/lock_error/escalated), `ts` | Stamps T9 + outcome; closes the run for the sessions tracker |
| `scr_verify_result` | T8 SCR-verify completion | `passed`, `failed`, `per_predicate` | Paints the SCR-01..SCR-11 + CL5 grid green/red (12 predicates) |

Unknown event types are ignored client-side. This lets the protocol grow without breaking older clients.

### 2.2 Operator surfaces

The browser layer is optional. The CLI/admin runtime in §1 remains the primary control path, and everything in `apps/monitor/` is a UI over that same state and allowlisted command surface.

| Surface | Path | WebSocket endpoint | Operator question it answers |
|---|---|---|---|
| Unified monitor | [`apps/monitor/nightclaw-monitor.html`](apps/monitor/nightclaw-monitor.html) | `/ws` | "What is the currently running session doing right now, which files is it touching, what state changed, and which allowlisted admin action do I need to take?" |
| Sessions | [`apps/monitor/nightclaw-sessions.html`](apps/monitor/nightclaw-sessions.html) | `/sessions` | "Across the last N runs, which completed clean, which escalated, how many mutations each, when did each T-step fire?" |
| Owner view | [`apps/monitor/owner.html`](apps/monitor/owner.html) | `/ws` | "What needs owner attention on this project, and how do I replay or act on it without leaving the monitor tier?" |

All three are pure static HTML + vanilla JS. No build step, no framework, no bundler. Port config is fetched from `nc_config.json` at the site root so the operator can retarget a different bridge without editing HTML.

The `privilege` returned in `connect_ack` is reflected in the `AUTH:` badge at the top of each app so the operator always knows whether the surface they are looking at is read-only or write-capable. Write-capable actions flow through the unified monitor and owner view when `privilege === 'rw'`.

### 2.3 Test coverage of the monitor tier

| File | Covers |
|---|---|
| `tests/test_protocol_payloads.py` | `is_opsstepevent` / `build_opsstepevent` contract |
| `tests/test_repository.py` | File + memory `SessionRepository` round-trip |
| `tests/test_server_sink_integration.py` | UNIX-socket ingest → `append_event` → broadcast path |
| `tests/test_bridge_server_snapshot.py` | `render_sessions_snapshot` against a folded event log |
| `tests/test_bridge_config.py` | `BridgeConfig` defaults + overrides |
| `tests/test_client_handlers.py` | `on_opsstepevent` store mutation (append + exit-code resolution) |
| `tests/test_monitor_handler_router.py` | Handler dispatch on event-type |
| `tests/test_monitor_selectors.py` | `timeline_for_run`, `open_steps`, `runs_index` |
| `tests/test_monitor_store.py` | Canonical `MonitorStore` semantics |
| `tests/test_bridge_runtime.py` | `LocalRuntime` adapter + admin-command allowlist |
| `tests/test_bridge_runtime_e2e.py` | End-to-end local runtime HTTP + WebSocket roundtrip |
| `tests/test_bridge_sources.py` | Read-only source parsers (NOTIFICATIONS, AUDIT-LOG, CHANGE-LOG, etc.) |
| `tests/test_snapshot_adapter.py` / `test_snapshot_contract.py` | Payload shape contract |
| `tests/test_state_replay.py` | Deterministic replay of an event log into a snapshot |

The tier is exercised at every layer: protocol parse, repository persistence, broadcast fan-out, client-side fold, snapshot render, replay determinism.

---

## 3. Package responsibilities

Four Python packages. Each has a single job. Names are the contract.

### `nightclaw_engine/` — the deterministic executor
**Owns:** every command the LLM invokes by name. Integrity verification, dispatch, bundle execution, longrunner rendering, audit append, schema rendering, phase-machine evaluation, SCR predicate enforcement.
**Public surface:**
- `commands/` — 11 focused command modules + `_shared.py` helpers + `__init__.py` dispatcher (`COMMANDS`, `STEP_CMD_MAP`, `main()`). Post-Pass-6 layout; largest modules are `bundle.py` (~931 LOC) and `bootstrap.py` (~752 LOC).
  - `lock.py` — lock-acquire, lock-release, next-run-id
  - `append.py` — append, append-batch
  - `integrity.py` — integrity-check
  - `validate.py` — validate-field, registry-route, cascade-read, strategic-context
  - `scr.py` — scr-verify thin driver
  - `longrunner.py` — longrunner-extract, longrunner-render, phase-validate
  - `dispatch.py` — dispatch, dispatch-validate, scan-notifications, idle-triage
  - `audit.py` — audit-spine, audit-anomalies, crash-detect, crash-context, prune-candidates, t7-dedup, os-file-sizes, change-detect, timing-check, transition-expiry
  - `bundle.py` — bundle-exec, validate-bundles, schema-render, schema-sync, schema-lint
  - `bundle_mutators.py` — per-target field mutators + `do_append` (split from bundle.py)
  - `bootstrap.py` — bootstrap (Pass 10 LLM bootstrap projection)
- `engine/` — gates, longrunner, render helpers.
- `schema/` — `SchemaModel`, `SchemaError`, `Phase`, `PhaseMachine`, `load_phase_machine_for_slug`.
- `protocol/` — integrity, SCR predicates.
- `mutators/` — stub subpackage (typed atomic writers; populated by future domain extensions).
**Depends on:** only the standard library + YAML files in `orchestration-os/schema/`. **Does not import** bridge, monitor, or ops.
**Tests:** 21 files under `tests/core/` and `tests/engine_e2e/` — schema contract, bundle atomicity, SCR predicates (incl. SCR-10 per-file R3 enforcement, SCR-01/SCR-06 typed-model queries, SCR-11 R3-CODE on-disk enforcement / INV-13), cascade resolution, REGISTRY↔render byte-equality (Pass 7), thesis-alignment invariants (Pass 8), security hardening (Pass 13), internal architecture doc-drift gate (Pass 14 / INV-14), reachability / dead-symbol gate (Pass 14.1 / INV-15), per-module unit coverage of the `commands/` split, the shipped monitor HTML `<script>` parse gate (Pass 15 / live-fix), R4-edge / R3-route graph-integrity invariants (2026-04-24 release-prep — endpoint-resolve, glob round-trip, entrypoint routing), and surface-boundary invariants (engine ↛ bridge/monitor, bridge ↛ engine, cron prompts ↛ LLM-BOOTSTRAP, step-map parity, admin-verb closed set).

### `nightclaw_bridge/` — the telemetry server (12 `.py` files)
**Owns:** the WebSocket + UNIX socket bridge that carries tier events from the engine to the UIs. Validates payloads, persists the event log, broadcasts to live subscribers, renders session snapshots. Also hosts an optional local runtime (`runtime.py`) that serves the shipped HTML monitor/sessions pages and a narrow, allowlisted admin-command surface; the runtime is opt-in and the engine does not depend on it.
**Public surface:**
- `protocol.py` — `ALLOWED_TIERS`, `build_opsstepevent`, `is_opsstepevent`.
- `server.py` — `BridgeServer`, `handle_ops_ingest`, `broadcast`, `render_sessions_snapshot`.
- `main.py` — `build_server(config, sessions_path, broadcast)` factory + `--serve` CLI entry.
- `client_handlers.py` — WebSocket client dispatch.
- `runtime.py` — optional `LocalRuntime` (HTTP + WS fan-out + admin-command allowlist).
- `sources.py` — read-only parsers for `NOTIFICATIONS.md`, `audit/AUDIT-LOG.md`, `audit/CHANGE-LOG.md`, `audit/APPROVAL-CHAIN.md`, `orchestration-os/OPS-PREAPPROVAL.md`, `ACTIVE-PROJECTS.md`, plus thin wrappers around `ops.py scr-verify` and `ops.py longrunner-extract`; used by `runtime.py` to populate the monitor's governance/audit/notification panes from authoritative repo state.
**Depends on:** the standard library; `websockets` only at runtime when `LocalRuntime.start()` is called with a non-zero bridge port. **Does not import** the engine. Contract with the engine is one direction: bridge reads the socket, engine writes to it.
**Tests:** 11 files — protocol validation, ingest fan-in, broadcast fan-out, bridge config parsing, runtime adapters, source parsers, and end-to-end sandbox roundtrip.

### `nightclaw_monitor/` — the UI-side store (6 `.py` files)
**Owns:** the in-browser data model that consumes bridge payloads and drives the shipped monitor HTML views.
**Public surface:**
- `store.py` — `MonitorStore` (canonical) + `Store` (back-compat).
**Depends on:** the bridge's published `snapshot_contract` module (shared payload validators) and the standard library. **Does not import** engine code. The import of `nightclaw_bridge.snapshot_contract` is deliberate: both sides of the seam validate against the same contract, so the wire format stays single-sourced.
**Tests:** 4 files — store reducers, back-compat snapshots, handler router, selectors.

### `nightclaw_ops/` — the engine-side telemetry emitter (3 `.py` files)
**Owns:** the one-way emitter that wraps each tier execution and ships events to the bridge socket. Never raises, never blocks.
**Public surface:**
- `telemetry.py` — `emit_step(...)`, `DEFAULT_OPS_SOCK`, queue + daemon thread.
- `lifecycle.py` — `step()` context manager reading `NIGHTCLAW_RUN_ID`.
**Depends on:** the standard library. **Does not import** bridge or monitor. Contract is the socket path + JSON payload shape.
**Tests:** 2 files — emit fire-and-forget semantics, queue overflow behavior, lifecycle wrapping.

**The import graph is a DAG.** Cross-package edges are limited and explicit:
- `scripts/nightclaw-ops.py` → `nightclaw_engine` (calls `nightclaw_engine.main()` directly; the old `_legacy.main` path was collapsed in Pass 6 — single code path for CLI and tests)
- `scripts/nightclaw-ops.py` → `nightclaw_ops.lifecycle`
- `nightclaw_monitor` → `nightclaw_bridge.snapshot_contract` (shared validators — single-sourced wire contract, see above)

Everything else is communication via filesystem (schema YAML, audit files) or UNIX socket (telemetry). Engine and bridge never import each other; ops never imports bridge or monitor.

---

## 4. Data-tier split

Three tiers, declared in the schema layer. Each answers a different question.

| Tier | Location | What it answers | Edited by |
|---|---|---|---|
| **A — Global schema** | `orchestration-os/schema/*.yaml` (7 files: `objects`, `fields`, `routing`, `edges`, `bundles`, `protected`, `scr_rules`) | *What are the object types, field contracts, write routes, dependency edges, bundle specs, protected files, self-consistency predicates for the system as a whole?* | Humans, versioned; rendered into `REGISTRY.generated.md` via `schema-render` and spliced in-place into `orchestration-os/REGISTRY.md` via `schema-sync` (byte-equality enforced by `tests/core/test_schema_sync.py`) |
| **B — Reserved** | — | *(Not yet used — placeholder for per-domain overlays)* | — |
| **C — Per-project phase machine** | `PROJECTS/[slug]/phases.yaml` | *What are the phases, transitions, and exit criteria for this specific project?* | Humans, per project; loaded via `load_phase_machine_for_slug` |

Tier A is global and slow-moving. Tier C is local and project-scoped. The engine reads both but writes neither — schema YAML is the source, `REGISTRY.generated.md` is the parallel render, and `orchestration-os/REGISTRY.md` sections R1-R6 + CL5 are kept byte-equal to that render via `schema-sync`. A failing byte-equality test blocks CI until sync is re-run, so schema and canonical REGISTRY can never silently drift.

---

## 5. File category table

Every file in the repo belongs to exactly one of these categories. No orphans.

| # | Category | Count | Location | Governing doc |
|---:|---|---:|---|---|
| 1 | Doctrine (LLM-authored) | 13 | Repo root `*.md` | `SOUL.md`, `AGENTS-CORE.md`, `AGENTS-LESSONS.md` |
| 2 | Cron prompts (shape-locked) | 2 | `orchestration-os/CRON-*-PROMPT.md` | `CRON-HARDLINES.md` |
| 3 | Ops policies | 9 | `orchestration-os/OPS-*.md` | `ORCHESTRATOR.md` |
| 4 | Schema (Tier A data) | 7 | `orchestration-os/schema/*.yaml` | `orchestration-os/schema/README.md` |
| 5 | Phase machines (Tier C data) | 1+N | `PROJECTS/*/phases.yaml` | `PROJECT-SCHEMA-TEMPLATE.md` |
| 6 | Engine code | 24 | `nightclaw_engine/` | This doc §3 + `REGISTRY.md` R3 CODE tier |
| 7 | Bridge code | 12 | `nightclaw_bridge/` | This doc §3 + `REGISTRY.md` R3 CODE tier |
| 8 | Monitor code | 6 | `nightclaw_monitor/` | This doc §3 + `REGISTRY.md` R3 CODE tier |
| 9 | Ops telemetry code | 3 | `nightclaw_ops/` | This doc §3 + `REGISTRY.md` R3 CODE tier |
| 10 | CLI scripts | 12 | `scripts/*.{py,sh}` | `README.md` §What NightClaw Ships |
| 11 | UI assets | 4 | `apps/monitor/*.html` | This doc §2 |
| 12 | Tests | 36 | `tests/**/*.py` | Test-as-contract; `pytest -q` |
| 13 | Runtime state (never hand-edited) | ~10 | `audit/*`, `LOCK.md`, `VERSION`, `memory/*` | `REGISTRY.md` R3 |
| 14 | Distribution mirror | — | `skills/` | `scripts/skills-sync.py` (auto-synced); contains `nightclaw_engine/` package copy + `nightclaw-ops.py` forwarder only — no shell scripts |

**Rules this table encodes:**
- Rows 1–3 are Markdown only; rows 6–9 are Python only; row 4 is YAML only. No mixing.
- Row 14 (`skills/`) is never edited directly. It contains exactly what `skills-sync.py` produces: `nightclaw_engine/` (byte-identical to the canonical package) and the `nightclaw-ops.py` forwarder. Shell scripts do not belong here — they depend on the full repo layout and are not part of the distribution bundle. Drift in `skills/nightclaw_engine/` is a bug fixed by running `skills-sync.py`.
- Row 13 is append-only or executor-managed. Manual edits trigger integrity-check failure on the next session.
- Rows 6–9 are the four packages; each has an R3 entry in `REGISTRY.md` at tier `CODE` (change-gated by tests rather than bundles). SCR-10 (`code_files_have_r3_rows`) enforces that every `.py` file under the four packages and every `.html` file under `apps/monitor/` has a CODE-tier row in R3.

---

## 6. Cross-references

- **File-level contract (objects, fields, routing, edges, bundles, predicates):** [`REGISTRY.md`](../orchestration-os/REGISTRY.md) / [`REGISTRY.generated.md`](../REGISTRY.generated.md)
- **Agent identity + hard lines:** [`SOUL.md`](../SOUL.md), [`AGENTS-CORE.md`](../AGENTS-CORE.md)
- **Session state machine (T0–T9):** [`README.md`](../README.md) §Session State Machine + [`orchestration-os/CRON-WORKER-PROMPT.md`](../orchestration-os/CRON-WORKER-PROMPT.md)
- **Multi-project dispatch + phase transitions:** [`orchestration-os/ORCHESTRATOR.md`](../orchestration-os/ORCHESTRATOR.md)
- **Schema layer:** [`orchestration-os/schema/README.md`](../orchestration-os/schema/README.md)
- **Current state + known issues:** [`CURRENT-PASS.md`](CURRENT-PASS.md)

---

## 7. What this document is not

- **Not a tutorial.** For public onboarding, read [`README.md`](../README.md) first.
- **Not a deploy guide.** See [`DEPLOY.md`](../DEPLOY.md).
- **Not the file-level contract.** Object/field/bundle specs live in `REGISTRY.md`. This doc shows the shape above them.
- **Not a change log.** See [`audit/CHANGE-LOG.md`](audit/CHANGE-LOG.md).

If you are looking for a specific file and can't find it in §5, that is a bug in this document — file an issue.

---

## 8. Navigation escape hatches

This document, the README, and `REGISTRY.md` deliberately describe *what is
under engine control*. For questions they cannot answer, use the following:

| Question | Where the answer lives |
|---|---|
| What is every file in the repo? | `git ls-files` or `find . -type f -name '*.md'`. R3 (`orchestration-os/schema/routing.yaml`) catalogs routed protocol, code, public docs, and internal enhancement surfaces; it is still not a replacement for a full filesystem inventory. |
| Which Python function writes file X? | `grep -rn "write_text\|open.*['\"][wa]" nightclaw_engine/` combined with `grep -rn "<filename>" nightclaw_engine/`. R3/R4 stop at file/bundle granularity; function-level write mapping is a code-inspection task, not a doctrine lookup. |
| What depends on file X (downstream) or what does X depend on (upstream)? | [`orchestration-os/schema/edges.yaml`](orchestration-os/schema/edges.yaml) — 74 typed edges (`READS`/`WRITES`/`VALIDATES`/`TRIGGERS`/`REFERENCES`/`AUTHORIZES`), bidirectionally queryable by source or target. The `dependency_graph` resolver projects this into bootstrap output for the `add_bundle` and `fix_bug` tracks. |
| Why is SOUL / USER / IDENTITY / AGENTS-CORE populated / sparse / blank here? | See `PROTECTED_PATHS` in `nightclaw_engine/commands/_shared.py` and the 2026.4.16 release note in [`audit/INTEGRITY-MANIFEST.md`](../audit/INTEGRITY-MANIFEST.md). These are owner-only; the engine refuses to write them. "Blank by design" and "missing" are not the same thing. |
| What did the last engineering pass change, and why? | [`audit/CHANGE-LOG.md`](../audit/CHANGE-LOG.md) for field-level change history, and `git log` for full commit history. Live-issue surface is [`CURRENT-PASS.md`](CURRENT-PASS.md). |
| How do I know if my change rotated the schema fingerprint? | `python3 scripts/nightclaw-ops.py schema-sync`. The fingerprint is SHA-256 over `orchestration-os/schema/*.yaml` only; edits anywhere else never rotate it. |

The rule of thumb: if a question is structural (files, deps, who-writes-what),
there is a schema answer. If it is behavioral (what does this function do,
why is this constant this value), grep the code. If it is historical (why did
we do it this way), check `audit/CHANGE-LOG.md` or `git log`.
