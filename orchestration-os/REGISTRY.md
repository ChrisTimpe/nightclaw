# REGISTRY.md — System Catalog
# Single source of truth for object structure, write routing, and dependency edges.
# Reader: Worker Tier 2B (conditional — only when control-plane writes planned)
#         Manager T8 (schema self-consistency check)
# Writer: Manager T8 appends new rows when gaps discovered. {OWNER} modifies structure.
# Cost: ~2,500 tokens. Read once. Zero redundancy with any other file.
#
# Governance principle: every file in this workspace has one job, one reader, one writer.
# This file is the map. The prompts are the instructions. The audit files are the record.
# These three layers never overlap.
#
# Deterministic operations: scripts/nightclaw-ops.py replaces LLM reasoning with code
# for all structured checks (integrity, dispatch, crash detection, pruning, SCR rules,
# LONGRUNNER field extraction, idle cycle triage, strategic context pre-digestion,
# T7 dedup matching, crash recovery context, and safe file appends).
# Prompts call the script and act on its machine-parseable output. The LLM never does
# computation that code can do — hashing, date math, set comparison, table parsing, grep,
# YAML field extraction, file existence checks, or fuzzy text matching.
#
# Design model: NightClaw is an object model with cascade integrity, not a file collection.
# This file is the schema. R1–R2 = object definitions and field contracts.
# R3 = write-routing table (tier + bundle per file). R4 = dependency graph — the cascade
# mechanism. R5 = bundles ( named atomic multi-file write operations ). R6 = integrity rules.
#
# The pre-write protocol (SOUL.md §1a, PW-2) traverses R4 before every write to surface
# downstream dependents. The integrity guarantee holds ONLY as far as R4 declares.
# If a relationship between files is not in R4, PW-2 cannot surface it and the cascade
# terminates early. Add R4 edges before adding new file relationships — the edge is the contract.

---

## R1 — OBJECT REGISTRY
<!-- nightclaw:render section="R1" source="orchestration-os/schema" schema_fingerprint="ab0fa02fcad6ac7018841d7eaed200581f9242c11b3acb97453ea108ebea3d2c" -->
# Every object type: what it is, where it lives, who reads it, who writes it.
# Format: OBJ | FILE | PK | READER | WRITER | APPEND-ONLY

OBJ:DISPATCH    | ACTIVE-PROJECTS.md                          | slug              | worker:T1,manager:T2/T3/T3.5 | worker:bundles,manager:T6 | NO
OBJ:PROJ        | PROJECTS/[slug]/LONGRUNNER.md               | singleton         | worker:T2,manager:T3.5 | worker:bundles | NO
OBJ:PROJ-DRAFT  | PROJECTS/[slug]/LONGRUNNER-DRAFT.md         | singleton         | manager:T3.5 | worker:idle-cycle(Tier4) | NO
OBJ:RUN         | audit/SESSION-REGISTRY.md                   | RUN-YYYYMMDD-NNN  | worker:startup,manager:T0 | worker:T9,manager:T9 | YES
OBJ:TASK        | audit/AUDIT-LOG.md                          | RUN-ID.Tstep      | manager:T8 | worker:T0/T4/T9,manager:T1/T8/T9 | YES
OBJ:CHANGELOG   | audit/CHANGE-LOG.md                         | none              | manager:T8 | worker:T4 | YES
OBJ:MANIFEST    | audit/INTEGRITY-MANIFEST.md                 | filepath          | worker:T0,manager:T1 | manager:T1(timestamps),{OWNER}(hashes) | NO
OBJ:PA          | orchestration-os/OPS-PREAPPROVAL.md         | PA-NNN            | worker:T2.7 | {OWNER} | NO
OBJ:CHAIN       | audit/APPROVAL-CHAIN.md                     | PA-NNN-INV-NNN    | manager:T8 | worker:T2.7 | YES
OBJ:FM          | orchestration-os/OPS-FAILURE-MODES.md       | FM-NNN(seq)       | - | worker:T7c | NO
OBJ:NOTIFY      | NOTIFICATIONS.md                            | none              | manager:T2/T3.5,worker:T1.5,{OWNER} | worker:bundles,manager | YES
OBJ:NOTIFY-ARCH | NOTIFICATIONS-ARCHIVE.md                    | none              | {OWNER} | manager:T8.3 | YES
OBJ:MEMORY      | memory/YYYY-MM-DD.md                        | none              | manager:T4,manager:T3.5 | worker:T9,manager:T3/T3.5/T9 | YES
OBJ:REGISTRY    | PROJECTS/MANAGER-REVIEW-REGISTRY.md         | slug+date         | manager:T3 | manager:T7 | NO
OBJ:TOOLREG     | orchestration-os/OPS-TOOL-REGISTRY.md       | tool+date         | - | worker:T7a | NO
OBJ:LESSONS     | AGENTS-LESSONS.md                           | none              | agent:on-demand | worker:T7d | YES
OBJ:LOCK        | LOCK.md                                     | none              | worker:STARTUP,manager:STARTUP | worker:STARTUP+T9,manager:STARTUP+T9 | NO
OBJ:PKG-ENGINE  | nightclaw_engine/                           | module_path       | scripts/nightclaw-ops.py,tests/ | {OWNER}:via-PR | NO
OBJ:PKG-BRIDGE  | nightclaw_bridge/                           | module_path       | apps/monitor/*.html (via WebSocket),tests/ | {OWNER}:via-PR | NO
OBJ:PKG-MONITOR | nightclaw_monitor/                          | module_path       | apps/monitor/*.html (import at runtime),tests/ | {OWNER}:via-PR | NO
OBJ:PKG-OPS     | nightclaw_ops/                              | module_path       | scripts/nightclaw-ops.py (lifecycle wrapper),tests/ | {OWNER}:via-PR | NO
OBJ:UI-MONITOR  | apps/monitor/                               | filename          | browser:via-WebSocket | {OWNER}:via-PR | NO
OBJ:FM-ARCH     | orchestration-os/OPS-FAILURE-MODES-ARCHIVE.md | FM-NNN(seq)       | {OWNER} | manager:T8(archival) | YES
OBJ:LESSONS-ARCH | AGENTS-LESSONS-ARCHIVE.md                   | none              | {OWNER} | manager:T8(archival) | YES
OBJ:TOOLREG-ARCH | orchestration-os/OPS-TOOL-REGISTRY-ARCHIVE.md | tool+date         | {OWNER} | manager:T8(archival) | YES
<!-- /nightclaw:render -->

## R2 — FIELD CONTRACTS
<!-- nightclaw:render section="R2" source="orchestration-os/schema" schema_fingerprint="ab0fa02fcad6ac7018841d7eaed200581f9242c11b3acb97453ea108ebea3d2c" -->
# Per-object field definitions. Format: OBJ | FIELD | TYPE | REQ | ENUM/FORMAT | FK/CONSTRAINT
# REQ: Y=required N=nullable. Enum values UPPERCASE for attention efficiency.

OBJ:DISPATCH | priority                            | INT       | Y | unique per ACTIVE row | -
OBJ:DISPATCH | slug                                | TOKEN     | Y | PK → PROJECTS/[slug]/ must exist | OBJ:PROJ
OBJ:DISPATCH | status                              | ENUM      | Y | ACTIVE|BLOCKED|PAUSED|TRANSITION-HOLD|COMPLETE|ABANDONED | -
OBJ:DISPATCH | last_worker_pass                    | DATETIME  | N | YYYY-MM-DD HH:MM TZ | -
OBJ:DISPATCH | escalation_pending                  | STRING    | Y | none OR surfaced-YYYY-MM-DD OR [reason] | -
OBJ:DISPATCH | phase                               | TOKEN     | N | current phase name | -
OBJ:DISPATCH | longrunner_path                     | PATH      | N | path to LONGRUNNER.md | default=PROJECTS/{slug}/LONGRUNNER.md

OBJ:PROJ     | phase.status                        | ENUM      | Y | ACTIVE|BLOCKED|COMPLETE | -
OBJ:PROJ     | phase.objective                     | TEXT      | Y | NOT EMPTY | -
OBJ:PROJ     | next_pass.objective                 | TEXT      | Y | NOT EMPTY — empty triggers stale-halt | -
OBJ:PROJ     | next_pass.model_tier                | ENUM      | Y | lightweight|standard|heavy | default=standard
OBJ:PROJ     | next_pass.context_budget            | ENUM      | Y | 40K|80K|120K|200K | default=80K
OBJ:PROJ     | phase.successor                     | TEXT      | N | next phase name — worker proposes at T6 phase_transition | -
OBJ:PROJ     | phase.name                          | TOKEN     | Y | current phase name | -
OBJ:PROJ     | phase.started                       | DATE      | N | YYYY-MM-DD phase start date | -
OBJ:PROJ     | phase.stop_condition                | TEXT      | N | testable stop condition | -
OBJ:PROJ     | last_pass.date                      | DATE      | N | YYYY-MM-DD | -
OBJ:PROJ     | last_pass.objective                 | TEXT      | N | prior pass objective | -
OBJ:PROJ     | last_pass.output_files              | TEXT      | N | comma-separated file paths | -
OBJ:PROJ     | last_pass.quality                   | ENUM      | N | STRONG|ADEQUATE|WEAK|FAIL | -
OBJ:PROJ     | last_pass.validation_passed         | BOOL      | N | true|false — did output meet pass_output_criteria? | default=false
OBJ:PROJ     | last_pass.weak_pass                 | BOOL      | N | true if all 4 value tests failed; false otherwise | default=false
OBJ:PROJ     | next_pass.tools_required            | TEXT      | N | comma-separated tool names | -
OBJ:PROJ     | next_pass.pass_type                 | TOKEN     | N | build-iteration|research|... | -
OBJ:PROJ     | transition_triggered_at             | ISO8601Z  | N | when phase transition was triggered | -
OBJ:PROJ     | transition_expires                  | ISO8601Z  | N | when transition hold expires | -
OBJ:PROJ     | transition_reescalation_count       | INT       | N | 0-3 re-escalation counter | default=0

OBJ:TASK     | task_id                             | TOKEN     | Y | PK RUN-YYYYMMDD-NNN.Tstep | composite PK
OBJ:TASK     | type                                | ENUM      | Y | INTEGRITY_CHECK|CHECKPOINT|EXEC|FILE_WRITE|BUNDLE|SESSION_CLOSE|MANAGER_REVIEW|IMPACT_PLAN|SFR | -
OBJ:TASK     | result                              | ENUM      | Y | PASS|FAIL|SUCCESS|BLOCKED|PARTIAL | -

OBJ:RUN      | run_id                              | TOKEN     | Y | PK RUN-YYYYMMDD-NNN | unique per day
OBJ:RUN      | session                             | ENUM      | Y | worker|manager | -
OBJ:RUN      | integrity_check                     | ENUM      | Y | PASS|FAIL | -
OBJ:RUN      | outcome                             | TEXT      | Y | NOT EMPTY | -

OBJ:CHANGELOG | field_path                          | PATH      | Y | FILE:[path]#[field] | -
OBJ:CHANGELOG | old_value                           | STRING    | Y | prior value or NONE | -
OBJ:CHANGELOG | new_value                           | STRING    | Y | new value | -
OBJ:CHANGELOG | run_id                              | TOKEN     | Y | FK→OBJ:RUN | OBJ:RUN
OBJ:CHANGELOG | t_written                           | ISO8601Z  | Y | when agent wrote it | -
OBJ:CHANGELOG | bundle                              | TOKEN     | N | BUNDLE:[name] or none | -

OBJ:PA       | pa_id                               | TOKEN     | Y | PK PA-NNN | -
OBJ:PA       | status                              | ENUM      | Y | ACTIVE|EXPIRED|REVOKED | -
OBJ:PA       | expires                             | DATETIME  | Y | YYYY-MM-DD HH:MM TZ | -

OBJ:CHAIN    | inv_id                              | TOKEN     | Y | PK PA-NNN-INV-NNN | -
OBJ:CHAIN    | timestamp                           | ISO8601Z  | Y | invocation time | -
OBJ:CHAIN    | run_id                              | TOKEN     | Y | FK→OBJ:RUN | OBJ:RUN
OBJ:CHAIN    | action_class                        | TOKEN     | Y | from OPS-PREAPPROVAL classes | -
OBJ:CHAIN    | slug                                | TOKEN     | N | project slug | -
OBJ:CHAIN    | scope_match                         | TEXT      | Y | scope comparison result | -
OBJ:CHAIN    | boundary_check                      | TEXT      | Y | boundary evaluation result | -
OBJ:CHAIN    | result                              | ENUM      | Y | AUTHORIZED|BLOCKED | -

OBJ:NOTIFY   | priority                            | ENUM      | Y | LOW|MEDIUM|HIGH|CRITICAL | -
OBJ:NOTIFY   | action_needed                       | TEXT      | Y | NOT EMPTY | -

OBJ:MANIFEST | filepath                            | PATH      | Y | PK relative to workspace root | -
OBJ:MANIFEST | sha256                              | HASH      | Y | exactly 64 hex chars | -
OBJ:MANIFEST | verified_by                         | STRING    | Y | {OWNER}-re-signed-YYYY.M.D|nightclaw-manager | -
OBJ:MANIFEST | last_verified                       | DATE      | N | YYYY-MM-DD last verification date | -

OBJ:NOTIFY-ARCH | content                             | TEXT      | Y | verbatim copy from NOTIFICATIONS.md | -
OBJ:NOTIFY-ARCH | moved_by                            | STRING    | Y | manager:T8.3 | -
OBJ:NOTIFY-ARCH | moved_at                            | ISO8601Z  | Y | timestamp of prune action | -

OBJ:MEMORY   | date                                | DATE      | Y | YYYY-MM-DD (filename stem) | -
OBJ:MEMORY   | session_log                         | TEXT      | Y | structured pass log content | -
OBJ:MEMORY   | consolidation                       | BOOL      | N | true if this is a dream pass output | default=false

OBJ:REGISTRY | section                             | ENUM      | Y | R1|R2|R3|R4|R5|R6|R7|CL1-CL6 | -
OBJ:REGISTRY | entry_type                          | ENUM      | Y | OBJ|FIELD|ROUTE|EDGE|BUNDLE|SCR|CL | -

OBJ:TOOLREG  | date                                | DATE      | Y | YYYY-MM-DD discovery date | -
OBJ:TOOLREG  | tool                                | STRING    | Y | tool name or path | -
OBJ:TOOLREG  | constraint                          | TEXT      | Y | description of constraint | -
OBJ:TOOLREG  | evidence                            | TEXT      | Y | what triggered the discovery | -
OBJ:TOOLREG  | session                             | STRING    | Y | worker|manager|{OWNER} + context | -

OBJ:LESSONS  | date                                | DATE      | Y | YYYY-MM-DD | -
OBJ:LESSONS  | slug                                | TOKEN     | N | short identifier for the lesson | -
OBJ:LESSONS  | observation                         | TEXT      | Y | one sentence minimum | -

OBJ:LOCK     | status                              | ENUM      | Y | locked|released | -
OBJ:LOCK     | holder                              | STRING    | N | session:nightclaw-worker|session:nightclaw-manager|— | -
OBJ:LOCK     | run_id                              | TOKEN     | N | RUN-YYYYMMDD-NNN|— | OBJ:RUN (when locked)
OBJ:LOCK     | locked_at                           | ISO8601Z  | N | timestamp of lock acquisition | -
OBJ:LOCK     | expires_at                          | ISO8601Z  | N | locked_at + 20 minutes | -
OBJ:LOCK     | consecutive_pass_failures           | INT       | Y | 0 on clean release, incremented on stale clear | default=0

OBJ:FM       | fm_id                               | TOKEN     | Y | PK FM-NNN (sequential) | -
OBJ:FM       | name                                | STRING    | Y | kebab-case failure name | -
OBJ:FM       | symptom                             | TEXT      | Y | observable behavior | -
OBJ:FM       | root_cause                          | TEXT      | Y | why it happens | -
OBJ:FM       | detection_signal                    | TEXT      | Y | how to confirm the match | -
OBJ:FM       | fix                                 | TEXT      | Y | remediation steps | -
OBJ:FM       | prevention                          | TEXT      | N | how to prevent recurrence | -
OBJ:FM       | status                              | ENUM      | Y | OPEN|MITIGATED|RESOLVED | -
<!-- /nightclaw:render -->

## R3 — WRITE ROUTING
<!-- nightclaw:render section="R3" source="orchestration-os/schema" schema_fingerprint="ab0fa02fcad6ac7018841d7eaed200581f9242c11b3acb97453ea108ebea3d2c" -->
# File → tier → bundle. The complete routing table for all write decisions.
# Format: FILE-PATTERN | TIER | BUNDLE | NOTE
# TIER: APPEND=write immediately | STANDARD=scope+gate | PROTECTED={OWNER}-auth | MANIFEST-VERIFY=manager-timestamp-only

ACTIVE-PROJECTS.md(update)                    | STANDARD         | BUNDLE:longrunner_update     | T6 state sync after pass
ACTIVE-PROJECTS.md(block)                     | STANDARD         | BUNDLE:route_block           | T2/T2.7/T3 blocking
ACTIVE-PROJECTS.md(transition)                | STANDARD         | BUNDLE:phase_transition      | Phase complete
ACTIVE-PROJECTS.md(advance)                   | STANDARD         | BUNDLE:phase_advance         | Phase advance to successor
ACTIVE-PROJECTS.md(escalation)                | STANDARD         | BUNDLE:surface_escalation    | Surfacing to {OWNER}
ACTIVE-PROJECTS.md                            | STANDARD         | standalone                   | Canonical bare name; see suffixed rows above for bundle-specific routing
PROJECTS/*/LONGRUNNER.md                      | STANDARD         | BUNDLE:longrunner_update     | Always via bundle, never raw
PROJECTS/*/LONGRUNNER-DRAFT.md                | STANDARD         | standalone                   | Worker idle-cycle Tier 4 writes; manager T3.5 reads; {OWNER} renames to LONGRUNNER.md on approval
PROJECTS/*/outputs/*                          | STANDARD         | standalone                   | T4 only. NEVER overwrite files from a prior phase — use phase-namespaced filenames. Prior phase outputs are audit artifacts.
NOTIFICATIONS.md(append)                      | APPEND           | standalone                   | Manager appends at STARTUP/T0/T2/T3.5/T4/T8; worker via BUNDLE:surface_escalation
NOTIFICATIONS.md(prune)                       | STANDARD         | standalone                   | Manager T8.3 only — move resolved/stale entries to archive
NOTIFICATIONS.md                              | APPEND           | standalone                   | Canonical bare name; see suffixed rows above for bundle-specific routing
NOTIFICATIONS-ARCHIVE.md                      | APPEND           | standalone                   | Manager T8.3 only — receives pruned entries verbatim
audit/AUDIT-LOG.md                            | APPEND           | inline                       | Every step writes its own entry
audit/SESSION-REGISTRY.md                     | APPEND           | BUNDLE:session_close         | T9 only
audit/CHANGE-LOG.md                           | APPEND           | inline                       | Immediately after each field change in T4
audit/APPROVAL-CHAIN.md                       | APPEND           | BUNDLE:pa_invoke             | T2.7 only
audit/INTEGRITY-MANIFEST.md                   | MANIFEST-VERIFY  | BUNDLE:manifest_verify       | Manager: timestamps only. {OWNER}: hashes.
memory/YYYY-MM-DD.md                          | APPEND           | BUNDLE:session_close,inline  | T9 via bundle; manager T3/T3.5 inline one-liners; worker idle-cycle inline
memory/README.md                              | STANDARD         | standalone                   | Explains empty fresh-template daily-log directory versus protected MEMORY.md.
PROJECTS/MANAGER-REVIEW-REGISTRY.md           | STANDARD         | standalone                   | Manager T7 only
orchestration-os/OPS-TOOL-REGISTRY.md         | STANDARD         | standalone                   | Worker T7a only
AGENTS.md                                     | STANDARD         | standalone                   | Navigation index — auto-injected by OpenClaw. {OWNER} edits only. Do not write behavioral content here.
MODEL-TIERS.md                                | STANDARD         | standalone                   | {OWNER} edits only. Never written by the agent. Read by set-model-tier at T9 to resolve model ID for next session.
AGENTS-CORE.md                                | PROTECTED        | none                         | {OWNER} only. Contains session contracts and behavioral rules. Re-sign after any edit.
AGENTS-LESSONS.md                             | APPEND           | standalone                   | Worker T7d only — append behavior lessons. Never overwrite.
LOCK.md                                       | STANDARD         | standalone                   | Worker/manager STARTUP (write) and BUNDLE:session_close (release). Overwrite-in-place only.
orchestration-os/REGISTRY.md(append)          | STANDARD         | standalone                   | Worker T7f — append new rows only. Never modify existing rows, never delete.
orchestration-os/REGISTRY.md(structural)      | PROTECTED        | none                         | Any modification to existing rows, deletion, or section restructuring. {OWNER} only. Re-sign after.
orchestration-os/OPS-FAILURE-MODES.md         | STANDARD         | standalone                   | Worker T7c — NEVER delete entries
orchestration-os/OPS-QUALITY-STANDARD.md      | STANDARD         | standalone                   | Worker T7e
orchestration-os/OPS-KNOWLEDGE-EXECUTION.md   | STANDARD         | standalone                   | Worker T7b
SOUL.md                                       | PROTECTED        | none                         | {OWNER} only. Six-frame review.
USER.md                                       | PROTECTED        | none                         | {OWNER} only.
IDENTITY.md                                   | PROTECTED        | none                         | {OWNER} only.
MEMORY.md                                     | PROTECTED        | none                         | {OWNER} only.
orchestration-os/CRON-WORKER-PROMPT.md        | PROTECTED        | none                         | {OWNER} only. Re-sign after.
orchestration-os/CRON-MANAGER-PROMPT.md       | PROTECTED        | none                         | {OWNER} only. Re-sign after.
orchestration-os/OPS-PREAPPROVAL.md           | PROTECTED        | none                         | {OWNER} only. Re-sign after.
orchestration-os/OPS-AUTONOMOUS-SAFETY.md     | PROTECTED        | none                         | {OWNER} only. Re-sign after.
orchestration-os/CRON-HARDLINES.md            | PROTECTED        | none                         | {OWNER} only. Re-sign after.
nightclaw_engine/__init__.py                  | CODE             | -                            | Package marker; re-exports COMMANDS + main from commands/
nightclaw_engine/commands/__init__.py         | CODE             | -                            | COMMANDS table + STEP_CMD_MAP + main() dispatcher (Pass 6)
nightclaw_engine/commands/_shared.py          | CODE             | -                            | ROOT singleton, PROTECTED_PATHS, APPEND_ALLOWED, YAML/LONGRUNNER helpers (Pass 6)
nightclaw_engine/commands/append.py           | CODE             | -                            | append + append-batch (Pass 6)
nightclaw_engine/commands/audit.py            | CODE             | -                            | audit-spine, audit-anomalies, crash-*, timing-check, change-detect, transition-expiry, prune-candidates, t7-dedup (Pass 6)
nightclaw_engine/commands/bootstrap.py        | CODE             | -                            | bootstrap — LLM onboarding projection via declarative tracks + resolver registry (Pass 10)
nightclaw_engine/commands/model_tier.py       | CODE             | -                            | set-model-tier — platform model switching via MODEL-TIERS.md at T9.5 (Pass 11)
nightclaw_engine/commands/bundle.py           | CODE             | -                            | bundle-exec, validate-bundles, schema-render, schema-lint (Pass 6)
nightclaw_engine/commands/bundle_mutators.py  | CODE             | -                            | per-target mutators (longrunner/dispatch/manifest/lock) + do_append; split from bundle.py for ≤700 LOC ceiling (Pass 6)
nightclaw_engine/commands/dispatch.py         | CODE             | -                            | dispatch, dispatch-validate, scan-notifications, idle-triage (Pass 6)
nightclaw_engine/commands/integrity.py        | CODE             | -                            | integrity-check SHA256 manifest verifier (Pass 6)
nightclaw_engine/commands/lock.py             | CODE             | -                            | lock-acquire, lock-release, next-run-id (Pass 6)
nightclaw_engine/commands/longrunner.py       | CODE             | -                            | longrunner-extract, longrunner-render, phase-validate (Pass 6)
nightclaw_engine/commands/scr.py              | CODE             | -                            | scr-verify thin driver; predicates live in protocol/integrity.py (Pass 6)
nightclaw_engine/commands/validate.py         | CODE             | -                            | validate-field, registry-route, cascade-read, strategic-context (Pass 6)
nightclaw_engine/engine/__init__.py           | CODE             | -                            | Exports gates, longrunner, render
nightclaw_engine/engine/gates.py              | CODE             | -                            | Pure-function R2/R3/R4/CL5 validators
nightclaw_engine/engine/longrunner.py         | CODE             | -                            | LONGRUNNER field extraction and rendering
nightclaw_engine/engine/render.py             | CODE             | -                            | Deterministic REGISTRY.generated.md renderer
nightclaw_engine/mutators/__init__.py         | CODE             | -                            | Mutator entry points (call gates before writes)
nightclaw_engine/protocol/__init__.py         | CODE             | -                            | Protocol package marker
nightclaw_engine/protocol/integrity.py        | CODE             | -                            | SCR predicate registry + implementations
nightclaw_engine/schema/__init__.py           | CODE             | -                            | Exports SchemaModel, Phase, PhaseMachine, loaders
nightclaw_engine/schema/loader.py             | CODE             | -                            | Tier-A YAML loader; SchemaModel dataclass + fingerprint
nightclaw_engine/schema/phases.py             | CODE             | -                            | Tier-C per-project phase machine loader
nightclaw_bridge/__init__.py                  | CODE             | -                            | Package marker
nightclaw_bridge/__main__.py                  | CODE             | -                            | python -m nightclaw_bridge entry shim
nightclaw_bridge/client_handlers.py           | CODE             | -                            | WebSocket client dispatch
nightclaw_bridge/config.py                    | CODE             | -                            | Bridge config loader (ports, socket path)
nightclaw_bridge/main.py                      | CODE             | -                            | build_server factory + optional --serve CLI
nightclaw_bridge/protocol.py                  | CODE             | -                            | ALLOWED_TIERS + is_opsstepevent validator
nightclaw_bridge/repository.py                | CODE             | -                            | FileSessionRepository + MemorySessionRepository
nightclaw_bridge/runtime.py                   | CODE             | -                            | Optional LocalRuntime: HTTP+WS fan-out + admin allowlist
nightclaw_bridge/server.py                    | CODE             | -                            | BridgeServer: handle_ops_ingest, broadcast, snapshot
nightclaw_bridge/snapshot_contract.py         | CODE             | -                            | Session snapshot payload schema
nightclaw_bridge/sources.py                   | CODE             | -                            | Read-only parsers: NOTIFICATIONS, audit/*, OPS-PREAPPROVAL, ACTIVE-PROJECTS, scr-verify, longrunner-extract
nightclaw_bridge/state.py                     | CODE             | -                            | In-memory session state
nightclaw_monitor/__init__.py                 | CODE             | -                            | Package marker
nightclaw_monitor/handlers.py                 | CODE             | -                            | Payload-type handlers
nightclaw_monitor/selectors.py                | CODE             | -                            | Store state selectors
nightclaw_monitor/snapshot_adapter.py         | CODE             | -                            | Snapshot → store adapter
nightclaw_monitor/snapshot_contract.py        | CODE             | -                            | Client-side snapshot schema (mirrors bridge)
nightclaw_monitor/store.py                    | CODE             | -                            | MonitorStore (canonical) + Store (back-compat)
nightclaw_ops/__init__.py                     | CODE             | -                            | Package marker
nightclaw_ops/lifecycle.py                    | CODE             | -                            | step() context manager; reads NIGHTCLAW_RUN_ID
nightclaw_ops/telemetry.py                    | CODE             | -                            | emit_step(); UNIX socket fire-and-forget; never raises
apps/monitor/nightclaw-monitor.html           | CODE             | -                            | Unified operator monitor; live event stream + allowlisted admin controls over WS /ws
apps/monitor/nightclaw-sessions.html          | CODE             | -                            | Sessions feed UI; WS /sessions
apps/monitor/NightClaw-Data-Flow.html         | CODE             | -                            | Data Flow SVG diagram (iframe child of nightclaw-monitor.html); reacts to postMessage {type:'nc-highlight',step,nodes}
apps/monitor/owner.html                       | CODE             | -                            | Project-owner view; same WS /ws contract + additive RO frame types project_snapshot/session_replay routed by nightclaw_bridge.runtime
orchestration-os/OPS-FAILURE-MODES-ARCHIVE.md | APPEND           | standalone                   | Manager T8 archival only — receives RESOLVED entries moved from OPS-FAILURE-MODES.md. Never delete.
AGENTS-LESSONS-ARCHIVE.md                     | APPEND           | standalone                   | Manager T8 archival only — receives aged lessons moved from AGENTS-LESSONS.md. Never delete.
orchestration-os/OPS-TOOL-REGISTRY-ARCHIVE.md | APPEND           | standalone                   | Manager T8 archival only — receives superseded entries from OPS-TOOL-REGISTRY.md. Never delete.
README.md                                     | STANDARD         | standalone                   | User-facing README. {OWNER} edits only.
INSTALL.md                                    | STANDARD         | standalone                   | Install pointer. {OWNER} edits only; keep aligned with README § Install.
DEPLOY.md                                     | STANDARD         | standalone                   | Deploy guide. {OWNER} edits only.
internal_enhancement/README.md                | STANDARD         | standalone                   | Maintainer-only internal enhancement index. {OWNER} edits only.
internal_enhancement/ARCHITECTURE.md          | STANDARD         | standalone                   | Internal architecture and maintenance map. {OWNER} edits only.
internal_enhancement/LLM-BOOTSTRAP.yaml       | STANDARD         | standalone                   | Maintainer bootstrap tracks. Not read by cron prompts.
internal_enhancement/CURRENT-PASS.md          | STANDARD         | standalone                   | Maintainer handoff and live known-issues surface.
orchestration-os/START-HERE.md                | STANDARD         | standalone                   | Agent orientation entry. {OWNER} edits only.
scripts/nightclaw-ops.py                      | STANDARD         | standalone                   | Runtime entrypoint (~107-line forwarder). {OWNER} edits only; SCR-10 scopes CODE tier to nightclaw_*/ and apps/monitor/ only.
[any unlisted file]                           | STANDARD         | standalone                   | Default. When in doubt.
<!-- /nightclaw:render -->

## R4 — DEPENDENCY EDGES
<!-- nightclaw:render section="R4" source="orchestration-os/schema" schema_fingerprint="ab0fa02fcad6ac7018841d7eaed200581f9242c11b3acb97453ea108ebea3d2c" -->
# Typed edges for impact traversal. Format: SOURCE → TYPE → TARGET
# Types: READS|WRITES|VALIDATES|TRIGGERS|REFERENCES|AUTHORIZES
# Read forward (grep SOURCE) to find what a change affects.
# Read reverse (grep TARGET) to find what depends on a file.

ACTIVE-PROJECTS.md                                      → READS       → PROJECTS/*/LONGRUNNER.md
ACTIVE-PROJECTS.md                                      → READS       → PROJECTS/*/LONGRUNNER-DRAFT.md (manager T3.5 — search for pending drafts)
ACTIVE-PROJECTS.md                                      → TRIGGERS    → BUNDLE:longrunner_update
ACTIVE-PROJECTS.md                                      → TRIGGERS    → BUNDLE:phase_transition
ACTIVE-PROJECTS.md                                      → TRIGGERS    → BUNDLE:route_block
PROJECTS/*/LONGRUNNER.md                                → WRITES      → ACTIVE-PROJECTS.md (via bundles)
PROJECTS/*/LONGRUNNER.md                                → WRITES      → audit/CHANGE-LOG.md (via T4)
BUNDLE:longrunner_update                                → WRITES      → PROJECTS/*/LONGRUNNER.md
BUNDLE:longrunner_update                                → WRITES      → ACTIVE-PROJECTS.md
BUNDLE:longrunner_update                                → WRITES      → audit/CHANGE-LOG.md
BUNDLE:longrunner_update                                → WRITES      → audit/AUDIT-LOG.md
BUNDLE:phase_transition                                 → WRITES      → PROJECTS/*/LONGRUNNER.md
BUNDLE:phase_transition                                 → WRITES      → ACTIVE-PROJECTS.md
BUNDLE:phase_transition                                 → WRITES      → NOTIFICATIONS.md
BUNDLE:phase_transition                                 → WRITES      → audit/CHANGE-LOG.md
BUNDLE:phase_transition                                 → WRITES      → audit/AUDIT-LOG.md
BUNDLE:route_block                                      → WRITES      → ACTIVE-PROJECTS.md
BUNDLE:route_block                                      → WRITES      → audit/CHANGE-LOG.md
BUNDLE:route_block                                      → WRITES      → audit/AUDIT-LOG.md
BUNDLE:surface_escalation                               → WRITES      → NOTIFICATIONS.md
BUNDLE:surface_escalation                               → WRITES      → ACTIVE-PROJECTS.md
BUNDLE:surface_escalation                               → WRITES      → audit/AUDIT-LOG.md
BUNDLE:surface_escalation                               → WRITES      → audit/CHANGE-LOG.md
NOTIFICATIONS.md                                        → READS       → worker:T1.5 (idle dispatch — worker scans for actionable entries)
NOTIFICATIONS.md                                        → WRITES      → NOTIFICATIONS-ARCHIVE.md (manager T8.3 prune — moves resolved/stale entries)
PROJECTS/*/LONGRUNNER-DRAFT.md                          → READS       → SOUL.md (manager T3.5-A — domain anchor alignment check)
PROJECTS/*/LONGRUNNER-DRAFT.md                          → READS       → USER.md (manager T3.5-A — constraint validation)
BUNDLE:pa_invoke                                        → WRITES      → audit/APPROVAL-CHAIN.md
BUNDLE:pa_invoke                                        → WRITES      → audit/AUDIT-LOG.md
BUNDLE:manifest_verify                                  → WRITES      → audit/INTEGRITY-MANIFEST.md (timestamps only)
BUNDLE:manifest_verify                                  → WRITES      → audit/AUDIT-LOG.md
BUNDLE:session_close                                    → WRITES      → audit/SESSION-REGISTRY.md
BUNDLE:session_close                                    → WRITES      → memory/YYYY-MM-DD.md
memory/README.md                                        → REFERENCES  → MEMORY.md
BUNDLE:session_close                                    → WRITES      → audit/AUDIT-LOG.md
BUNDLE:session_close                                    → WRITES      → audit/CHANGE-LOG.md
BUNDLE:session_close                                    → WRITES      → LOCK.md (release)
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → SOUL.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → USER.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → IDENTITY.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → MEMORY.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → orchestration-os/CRON-WORKER-PROMPT.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → orchestration-os/CRON-MANAGER-PROMPT.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → orchestration-os/OPS-PREAPPROVAL.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → orchestration-os/OPS-AUTONOMOUS-SAFETY.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → orchestration-os/CRON-HARDLINES.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → orchestration-os/REGISTRY.md
audit/INTEGRITY-MANIFEST.md                             → VALIDATES   → AGENTS-CORE.md
AGENTS-CORE.md                                          → REFERENCES  → AGENTS-LESSONS.md
AGENTS-CORE.md                                          → REFERENCES  → AGENTS.md
LOCK.md                                                 → READS       → worker:STARTUP
LOCK.md                                                 → READS       → manager:STARTUP
BUNDLE:phase_advance                                    → WRITES      → PROJECTS/*/LONGRUNNER.md
BUNDLE:phase_advance                                    → WRITES      → ACTIVE-PROJECTS.md
BUNDLE:phase_advance                                    → WRITES      → audit/CHANGE-LOG.md
BUNDLE:phase_advance                                    → WRITES      → audit/AUDIT-LOG.md
orchestration-os/OPS-PREAPPROVAL.md                     → AUTHORIZES  → BUNDLE:pa_invoke
orchestration-os/OPS-PREAPPROVAL.md                     → REFERENCES  → audit/APPROVAL-CHAIN.md
orchestration-os/REGISTRY.md                            → READS       → scripts/nightclaw-ops.py:bundle-exec (runtime R5 parsing)
README.md                                               → REFERENCES  → INSTALL.md
README.md                                               → REFERENCES  → DEPLOY.md
README.md                                               → REFERENCES  → orchestration-os/ORCHESTRATOR.md
README.md                                               → REFERENCES  → internal_enhancement/ARCHITECTURE.md
INSTALL.md                                              → REFERENCES  → DEPLOY.md
orchestration-os/START-HERE.md                          → REFERENCES  → orchestration-os/CRON-WORKER-PROMPT.md
scripts/nightclaw-ops.py                                → READS       → nightclaw_engine/commands/__init__.py (imports main + COMMANDS)
scripts/nightclaw-ops.py                                → READS       → nightclaw_ops/lifecycle.py (imports step context manager)
nightclaw_ops/telemetry.py                              → WRITES      → /tmp/nightclaw-ops.sock (UNIX socket; fire-and-forget JSON events)
nightclaw_bridge/server.py                              → READS       → /tmp/nightclaw-ops.sock (handle_ops_ingest; validates via is_opsstepevent)
nightclaw_bridge/server.py                              → WRITES      → apps/monitor/*.html (via WebSocket ws://127.0.0.1:${port}/ws and /sessions)
nightclaw_engine/schema/loader.py                       → READS       → orchestration-os/schema/*.yaml (Tier-A schema)
nightclaw_engine/schema/phases.py                       → READS       → PROJECTS/*/phases.yaml (Tier-C per-project)
nightclaw_engine/commands/model_tier.py                 → READS       → MODEL-TIERS.md (parses lightweight/standard/heavy model ID mappings at T9.5)
PROJECTS/*/LONGRUNNER.md                                → READS       → MODEL-TIERS.md (next_pass.model_tier resolved against MODEL-TIERS.md via set-model-tier at T9.5)
orchestration-os/CRON-WORKER-PROMPT.md                  → TRIGGERS    → nightclaw_engine/commands/model_tier.py (T9.5 — set-model-tier called after session_close)
apps/monitor/nightclaw-monitor.html                     → READS       → nightclaw_bridge/server.py (WebSocket /ws stream)
apps/monitor/nightclaw-sessions.html                    → READS       → nightclaw_bridge/server.py (WebSocket /sessions stream)
nightclaw_engine/commands/bootstrap.py                  → READS       → internal_enhancement/LLM-BOOTSTRAP.yaml
nightclaw_engine/commands/bootstrap.py                  → READS       → internal_enhancement/ARCHITECTURE.md
nightclaw_engine/commands/bootstrap.py                  → READS       → internal_enhancement/CURRENT-PASS.md
internal_enhancement/LLM-BOOTSTRAP.yaml                 → REFERENCES  → internal_enhancement/ARCHITECTURE.md
internal_enhancement/LLM-BOOTSTRAP.yaml                 → REFERENCES  → internal_enhancement/CURRENT-PASS.md
internal_enhancement/ARCHITECTURE.md                    → REFERENCES  → orchestration-os/REGISTRY.md
<!-- /nightclaw:render -->

## R5 — BUNDLE SPECIFICATIONS
<!-- nightclaw:render section="R5" source="orchestration-os/schema" schema_fingerprint="ab0fa02fcad6ac7018841d7eaed200581f9242c11b3acb97453ea108ebea3d2c" -->
# Named multi-file write operations. The executor (bundle-exec) reads these at runtime.
# Expression types (exactly four): LITERAL (bare), ARG ({name}), COMPUTED ({NOW}/{TODAY}/{NOW+field}), NULL (~).
# No TEMPLATE interpolation. LLM constructs full strings and passes as ARGs.
# CHANGE-LOG entries are emitted automatically by the executor for every MUTATE where old ≠ new.
# Format: BUNDLE:[name] → TRIGGER, ARGS, VALIDATES, WRITES (MUTATE), APPEND, NOTIFY, RETURNS.

BUNDLE:longrunner_update
  TRIGGER: T6 after pass completes (T5 PASS or WEAK)
  ARGS: slug, run_id, quality, objective, output_files, next_objective, model_tier, context_budget, tools
  VALIDATES:
    - LONGRUNNER:{slug}.phase.status EQUALS ACTIVE
    - next_objective NOT_EMPTY
    - quality IN STRONG,ADEQUATE,WEAK,FAIL
    - model_tier IN lightweight,standard,heavy
  WRITES:
    LONGRUNNER:{slug}:
      last_pass.date = {TODAY}
      last_pass.objective = {objective}
      last_pass.output_files = {output_files}
      last_pass.quality = {quality}
      next_pass.objective = {next_objective}
      next_pass.model_tier = {model_tier}
      next_pass.context_budget = {context_budget}
      next_pass.tools_required = {tools}
    DISPATCH:{slug}:
      last_worker_pass = {NOW}
  APPEND:
    audit/AUDIT-LOG.md: TASK:{run_id}.T6 | TYPE:BUNDLE | BUNDLE:longrunner_update | RESULT:SUCCESS
  RETURNS: SUCCESS

BUNDLE:phase_transition
  TRIGGER: T6 when LONGRUNNER stop_condition met
  ARGS: slug, run_id, successor, escalation_text, action_text
  VALIDATES:
    - LONGRUNNER:{slug}.phase.status EQUALS ACTIVE
  WRITES:
    LONGRUNNER:{slug}:
      phase.status = COMPLETE
      phase.successor = {successor}
      transition_triggered_at = {NOW}
      transition_expires = {NOW+transition_timeout_days}
      transition_reescalation_count = 0
    DISPATCH:{slug}:
      status = TRANSITION-HOLD
      escalation_pending = {escalation_text}
  APPEND:
    audit/AUDIT-LOG.md: TASK:{run_id}.T6 | TYPE:BUNDLE | BUNDLE:phase_transition | RESULT:SUCCESS
  NOTIFY:
    priority: HIGH
    action_text: {action_text}
    slug: {slug}
    status: PHASE-TRANSITION
  RETURNS: SUCCESS

BUNDLE:phase_advance
  TRIGGER: T2-ADVANCE when dispatch returns ADVANCE:<slug>
  ARGS: slug, run_id, successor, init_objective
  VALIDATES:
    - LONGRUNNER:{slug}.phase.successor NOT_EMPTY
    - LONGRUNNER:{slug}.phase.status EQUALS COMPLETE
  WRITES:
    LONGRUNNER:{slug}:
      phase.name = {successor}
      phase.status = ACTIVE
      phase.started = {TODAY}
      phase.successor = 
      phase.objective = 
      phase.stop_condition = 
      transition_triggered_at = ~
      transition_expires = ~
      transition_reescalation_count = 0
      next_pass.objective = {init_objective}
      next_pass.pass_type = build-iteration
    DISPATCH:{slug}:
      phase = {successor}
      status = ACTIVE
      escalation_pending = none
  APPEND:
    audit/AUDIT-LOG.md: TASK:{run_id}.T2 | TYPE:BUNDLE | BUNDLE:phase_advance | RESULT:SUCCESS
  RETURNS: SUCCESS

BUNDLE:route_block
  TRIGGER: T2 BLOCKED | T2.7 unauthorized | T3 tool unavailable
  ARGS: slug, run_id, reason
  VALIDATES:
    - reason NOT_EMPTY
  WRITES:
    DISPATCH:{slug}:
      status = BLOCKED
      escalation_pending = {reason}
  APPEND:
    audit/AUDIT-LOG.md: TASK:{run_id}.T2 | TYPE:BUNDLE | BUNDLE:route_block | RESULT:BLOCKED
  RETURNS: SUCCESS

BUNDLE:surface_escalation
  TRIGGER: Any condition requiring {OWNER} decision
  ARGS: slug, run_id, priority, action_text, context, reason
  VALIDATES:
    - action_text NOT_EMPTY
    - priority IN LOW,MEDIUM,HIGH,CRITICAL
  WRITES:
    DISPATCH:{slug}:
      escalation_pending = {reason}
  APPEND:
    audit/AUDIT-LOG.md: TASK:{run_id}.T2 | TYPE:BUNDLE | BUNDLE:surface_escalation | RESULT:SUCCESS
  NOTIFY:
    priority: {priority}
    action_text: {action_text}
    context: {context}
    slug: {slug}
    status: ESCALATION
  RETURNS: SUCCESS

BUNDLE:pa_invoke
  # STAYS INLINE — requires LLM judgment for scope/boundary evaluation.
  # Not handled by bundle-exec. The LLM reads OPS-PREAPPROVAL.md and evaluates.
  TRIGGER: T2.7 when exec/extended write needed
  VALIDATES FIRST: PA exists | status=ACTIVE | expires>now | all scope fields MATCH
  IF VALID:
    WRITES: audit/APPROVAL-CHAIN.md → PA-NNN-INV-NNN | scope verification | result
    WRITES: audit/AUDIT-LOG.md → APPEND: TASK:[run].T2.7 TYPE:BUNDLE RESULT:SUCCESS
  IF INVALID: calls BUNDLE:surface_escalation; then BUNDLE:route_block
  RETURNS: AUTHORIZED | BLOCKED

BUNDLE:manifest_verify
  TRIGGER: Manager T1 — all hashes match
  ARGS: run_id
  WRITES:
    MANIFEST:
      last_verified = {TODAY}
      verified_by = nightclaw-manager
  APPEND:
    audit/AUDIT-LOG.md: TASK:{run_id}.T1 | TYPE:INTEGRITY_CHECK | RESULT:PASS
  AUTHORITY: manager-authority standing auth covers timestamp-only writes. No PA required.
  RETURNS: SUCCESS

BUNDLE:session_close
  TRIGGER: T9 — end of every pass
  ARGS: run_id, session_entry, memory_entry, audit_entry
  VALIDATES:
    - session_entry NOT_EMPTY
  WRITES:
    LOCK:
      status = released
      run_id = —
      holder = —
      locked_at = —
      expires_at = —
      consecutive_pass_failures = 0
  APPEND:
    audit/SESSION-REGISTRY.md: {session_entry}
    memory/{TODAY}.md: {memory_entry}
    audit/AUDIT-LOG.md: {audit_entry}
  RETURNS: SUCCESS
<!-- /nightclaw:render -->

## R6 — SELF-CONSISTENCY RULES
<!-- nightclaw:render section="R6" source="orchestration-os/schema" schema_fingerprint="ab0fa02fcad6ac7018841d7eaed200581f9242c11b3acb97453ea108ebea3d2c" -->
# Rule IDs, severities and predicate names. Narrative bodies remain in REGISTRY.md doctrine.
# Format: ID | SEVERITY | PREDICATE | TITLE

SCR-01 | HIGH     | r3_bundles_exist_in_r5                     | Every BUNDLE: name in R3 exists as a BUNDLE: definition in R5
SCR-02 | HIGH     | r2_foreign_keys_resolve_to_r1              | Every FK→OBJ: in R2 resolves to an OBJ: entry in R1
SCR-03 | CRITICAL | r3_protected_files_are_in_manifest         | Every file in R3 PROTECTED tier is in audit/INTEGRITY-MANIFEST.md
SCR-04 | HIGH     | changelog_file_exists                      | audit/CHANGE-LOG.md exists
SCR-05 | HIGH     | session_registry_run_ids_unique            | audit/SESSION-REGISTRY.md run_ids are unique (no duplicate RUN-YYYYMMDD-N)
SCR-06 | MEDIUM   | r4_bundle_refs_resolve_to_r5               | Every BUNDLE: in R4 edges resolves to a definition in R5
SCR-07 | HIGH     | references_cross_doc_consistency           | REFERENCES edges: downstream targets remain consistent with source after source changes
SCR-08 | HIGH     | session_close_releases_lock                | LOCK.md status must be released at session close per BUNDLE:session_close
SCR-09 | HIGH     | prompt_bundle_args_match_r5                | For every Execute: bundle-exec <name> in prompts, arg names match R5 BUNDLE:{name} ARGS
SCR-10 | HIGH     | code_files_have_r3_rows                    | Every .py file in the four code packages (engine/bridge/monitor/ops) and every .html file in apps/monitor/ has a CODE-tier row in R3
SCR-11 | HIGH     | r3_code_rows_exist_on_disk                 | Every R3 row at tier CODE names a file that exists on disk (INV-13)
<!-- /nightclaw:render -->

## R7 — CHANGE-LOG FORMAT SPECIFICATION

<!-- Specifies the format of audit/CHANGE-LOG.md (append-only field-level change log). -->
<!-- NOT a replacement for audit/AUDIT-LOG.md (action-level). -->
<!-- AUDIT-LOG: what happened (action). CHANGE-LOG: what changed (field state). -->

---

## CL1 — PURPOSE AND SCOPE

<!-- AUDIT-LOG.md tracks: agent actions, bundle calls, task entries, auth events. -->
<!-- CHANGE-LOG.md tracks: field-value mutations with provenance and temporal context. -->
<!-- Enables: point-in-time reconstruction, field attribution, protected field audit. -->
<!-- Consumed by: manager T8 audit review, incident reconstruction, S5 rule checks. -->

SCOPE:STANDARD  → every field write that changes a value (old≠new)
SCOPE:PROTECTED → every field write to PROTECTED-tier files (even if agent={OWNER})
SCOPE:EXCLUDE   → APPEND-only files where no field changes (AUDIT-LOG entries, SESSION-REGISTRY new rows)
SCOPE:EXCLUDE   → integrity check timestamp-only updates to INTEGRITY-MANIFEST.md

---

## CL2 — ENTRY FORMAT

<!-- Bi-temporal model: t_written = when the agent wrote it; t_valid = when it became true in the domain. -->
<!-- In most cases t_written ≈ t_valid. They diverge when backfilling or correcting historical state. -->
<!-- Format: pipe-delimited single line. No spaces around pipes in data rows. -->

<!-- Header (reference only — do not write header to log file): -->
<!-- field_path|old_value|new_value|agent_id|run_id|t_written|t_valid|reason|bundle -->

FIELD-FORMAT:
  field_path  = FILE:relative/path#section.field_name   (e.g. FILE:ACTIVE-PROJECTS.md#nightclaw.status)
  old_value   = prior value as string | NONE (new field) | REDACTED (protected field, value omitted)
  new_value   = new value as string   | DELETED          | REDACTED (protected field, value omitted)
  agent_id    = worker|manager|{OWNER}|pa-NNN
  run_id      = RUN-YYYYMMDD-NNN (from current session)
  t_written   = ISO8601Z timestamp of write execution
  t_valid     = ISO8601Z timestamp the value became valid in the domain (= t_written unless backfill)
  reason      = one-line rationale slug (kebab-case, max 80 chars)
  bundle      = BUNDLE:[name] | standalone | none

EXAMPLE-ENTRY:
FILE:ACTIVE-PROJECTS.md#nightclaw.status|ACTIVE|BLOCKED|worker|RUN-20260403-001|2026-04-03T20:15:00Z|2026-04-03T20:15:00Z|blocker-detected-tool-unavailable|BUNDLE:route_block

EXAMPLE-PROTECTED:
FILE:orchestration-os/CRON-WORKER-PROMPT.md#header.version|REDACTED|REDACTED|{OWNER}|RUN-20260403-002|2026-04-03T21:00:00Z|2026-04-03T21:00:00Z|v0.001-architecture-update|none

---

## CL3 — APPEND PROTOCOL

<!-- audit/CHANGE-LOG.md is append-only. Same constraint as AUDIT-LOG.md. -->
<!-- Never delete or overwrite entries. Corrections = new entry with reason=correction-of-[run_id]. -->

WRITE-TRIGGER:
  1. Agent completes a STANDARD or PROTECTED write that changes field value (old≠new)
  2. Immediately after the write, before next action
  3. One CL entry per field changed (multi-field writes = multiple CL entries, same run_id)
  4. Batch writes (bundles): each field in the bundle gets its own CL entry with bundle=[name]

WRITE-OBLIGATION:
  Enforced at: TASK:worker.T4 (EXECUTE PASS) — every file write goes through REGISTRY.md R3 routing
  Enforced at: BUNDLE execution — bundle spec in REGISTRY.md R5 implies CL entries for its WRITES
  Not enforced: APPEND-only files (no field mutation, only row append)
  Not enforced: INTEGRITY-MANIFEST.md timestamp-only updates (value unchanged by BUNDLE:manifest_verify)

ATOMICITY:
  If a bundle write is interrupted: CL entries for completed fields remain
  Incomplete bundle = partial CL entries + AUDIT-LOG failure entry
  Never retroactively remove CL entries to "clean up" incomplete writes

---

## CL4 — POINT-IN-TIME RECONSTRUCTION

<!-- Query: what was field X at time T? -->
<!-- Algorithm: scan CHANGE-LOG.md, collect all entries where field_path=X and t_valid ≤ T -->
<!-- Return: entry with maximum t_valid ≤ T → its new_value is the state at time T -->

RECONSTRUCTION-STEPS:
  1. grep field_path from CHANGE-LOG.md
  2. filter: t_valid ≤ query_time
  3. sort by t_valid descending
  4. take first entry → new_value = field state at query_time
  5. if no entries → field was not tracked before query_time (value unknown or predates CHANGE-LOG)

EXAMPLE-QUERY: "What was ACTIVE-PROJECTS.md#nightclaw.priority at 2026-04-03T15:30:00Z?"
  grep "FILE:ACTIVE-PROJECTS.md#nightclaw.priority" audit/CHANGE-LOG.md
  filter t_valid ≤ 2026-04-03T15:30:00Z
  return max(t_valid).new_value

---

## CL5 — PROTECTED FIELD AUDIT RULE

<!-- Manager T8 checks CHANGE-LOG for unauthorized protected field changes. -->
<!-- Rule: any entry where field_path starts with a PROTECTED file path -->
<!--       must have a matching APPROVAL-CHAIN entry (agent_id={OWNER} OR pa-NNN in APPROVAL-CHAIN). -->

<!-- The PROTECTED-PATHS list below is schema-sourced. The entries between the -->
<!-- render markers are rewritten by `schema-sync` from orchestration-os/schema/. -->
<!-- nightclaw:render section="CL5" source="orchestration-os/schema" schema_fingerprint="ab0fa02fcad6ac7018841d7eaed200581f9242c11b3acb97453ea108ebea3d2c" -->
# Files requiring {OWNER} authorization. Enforced by the route gate and audited by manager T8.

FILE:SOUL.md
FILE:USER.md
FILE:IDENTITY.md
FILE:MEMORY.md
FILE:AGENTS-CORE.md
FILE:orchestration-os/CRON-WORKER-PROMPT.md
FILE:orchestration-os/CRON-MANAGER-PROMPT.md
FILE:orchestration-os/OPS-PREAPPROVAL.md
FILE:orchestration-os/OPS-AUTONOMOUS-SAFETY.md
FILE:orchestration-os/CRON-HARDLINES.md
FILE:orchestration-os/REGISTRY.md
<!-- /nightclaw:render -->

AUDIT-CHECK (manager T8):
  For each CL entry where field_path prefix IN PROTECTED-PATHS:
    IF agent_id NOT IN [{OWNER}] AND APPROVAL-CHAIN has no matching PA entry:
      flag CRITICAL → NOTIFICATIONS.md

---

## CL6 — FILE LOCATION AND GATE

FILE-PATH: audit/CHANGE-LOG.md
GATE-TIER: APPEND (same as audit/AUDIT-LOG.md)
CREATED-BY: First write that triggers a CL entry (auto-created if absent)
REGISTRY-REF: REGISTRY.md R1 OBJ:CHANGELOG
