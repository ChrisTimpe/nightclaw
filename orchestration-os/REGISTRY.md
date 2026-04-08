# REGISTRY.md — System Catalog
# v0.1.0 | Single source of truth for object structure, write routing, and dependency edges.
# v0.1.0 consolidated four prior files into this one (see orchestration-os/ deprecated stubs)
# Reader: Worker Tier 2B (conditional — only when control-plane writes planned)
#         Manager T8 (schema self-consistency check)
# Writer: Manager T8 appends new rows when gaps discovered. {OWNER} modifies structure.
# Cost: ~2,500 tokens. Read once. Zero redundancy with any other file.
#
# Governance principle: every file in this workspace has one job, one reader, one writer.
# This file is the map. The prompts are the instructions. The audit files are the record.
# These three layers never overlap.
#
# Design model: NightClaw is an object model with cascade integrity, not a file collection.
# This file is the schema. R1–R2 = object definitions and field contracts.
# R3 = write-routing table (tier + bundle per file). R4 = dependency graph — the cascade
# mechanism. R5 = bundles (named atomic multi-file write operations). R6 = integrity rules.
#
# The pre-write protocol (SOUL.md §1a, PW-2) traverses R4 before every write to surface
# downstream dependents. The integrity guarantee holds ONLY as far as R4 declares.
# If a relationship between files is not in R4, PW-2 cannot surface it and the cascade
# terminates early. Add R4 edges before adding new file relationships — the edge is the contract.

---

## R1 — OBJECT REGISTRY
# Every object type: what it is, where it lives, who reads it, who writes it.
# Format: OBJ | FILE | PK | READER | WRITER | APPEND-ONLY

OBJ:DISPATCH    | ACTIVE-PROJECTS.md                          | slug         | worker:T1,manager:T2 | worker:bundles,manager:T6 | NO
OBJ:PROJ        | PROJECTS/[slug]/LONGRUNNER.md               | singleton    | worker:T2            | worker:bundles            | NO
OBJ:RUN         | audit/SESSION-REGISTRY.md                   | RUN-YYYYMMDD-NNN | worker:startup,manager:T0 | worker:T9,manager:T9 | YES
OBJ:TASK        | audit/AUDIT-LOG.md                          | RUN-ID.Tstep | manager:T8           | worker:T0/T4/T9,manager:T1/T8/T9 | YES
OBJ:CHANGELOG   | audit/CHANGE-LOG.md                         | none         | manager:T8           | worker:T4                 | YES
OBJ:MANIFEST    | audit/INTEGRITY-MANIFEST.md                 | filepath     | worker:T0,manager:T1 | manager:T1(timestamps),{OWNER}(hashes) | NO
OBJ:PA          | orchestration-os/OPS-PREAPPROVAL.md         | PA-NNN       | worker:T2.7          | {OWNER}                     | NO
OBJ:CHAIN       | audit/APPROVAL-CHAIN.md                     | PA-NNN-INV-NNN | manager:T8         | worker:T2.7               | YES
OBJ:FM          | orchestration-os/OPS-FAILURE-MODES.md       | FM-NNN(seq)  | -                    | worker:T7c                | NO
OBJ:NOTIFY      | NOTIFICATIONS.md                            | none         | manager:T2,{OWNER}     | worker:bundles,manager     | YES
OBJ:MEMORY      | memory/YYYY-MM-DD.md                        | none         | manager:T4           | worker:T9,manager:T9      | YES
OBJ:REGISTRY    | PROJECTS/MANAGER-REVIEW-REGISTRY.md         | slug+date    | manager:T3           | manager:T7                | NO
OBJ:TOOLREG     | orchestration-os/OPS-TOOL-REGISTRY.md       | tool+date    | -                    | worker:T7a                | NO
OBJ:LESSONS     | AGENTS-LESSONS.md                           | none         | agent:on-demand      | worker:T7d                | YES
OBJ:LOCK        | LOCK.md                                     | none         | worker:STARTUP,manager:STARTUP | worker:STARTUP+T9,manager:STARTUP+T9 | NO

---

## R2 — FIELD CONTRACTS
# Per-object field definitions. Format: OBJ | FIELD | TYPE | REQ | ENUM/FORMAT | FK/CONSTRAINT
# REQ: Y=required N=nullable. Enum values UPPERCASE for attention efficiency.

OBJ:DISPATCH | priority           | INT    | Y | unique per ACTIVE row             | -
OBJ:DISPATCH | slug               | TOKEN  | Y | PK → PROJECTS/[slug]/ must exist  | FK→OBJ:PROJ
OBJ:DISPATCH | status             | ENUM   | Y | ACTIVE|BLOCKED|PAUSED|TRANSITION-HOLD|COMPLETE|ABANDONED | -
OBJ:DISPATCH | last_worker_pass   | DATETIME | N | YYYY-MM-DD HH:MM TZ             | -
OBJ:DISPATCH | escalation_pending | STRING | Y | none OR surfaced-YYYY-MM-DD OR [reason] | -

OBJ:PROJ | phase.status          | ENUM   | Y | ACTIVE|BLOCKED|COMPLETE           | -
OBJ:PROJ | phase.objective       | TEXT   | Y | NOT EMPTY                          | -
OBJ:PROJ | next_pass.objective   | TEXT   | Y | NOT EMPTY — empty triggers stale-halt | -
OBJ:PROJ | next_pass.model_tier  | ENUM   | Y | lightweight|standard|heavy         | default=standard
OBJ:PROJ | next_pass.context_budget | ENUM | Y | 40K|80K|120K|200K               | default=80K
OBJ:PROJ | last_pass.quality     | ENUM   | N | STRONG|ADEQUATE|WEAK|FAIL          | -

OBJ:TASK | task_id               | TOKEN  | Y | PK RUN-YYYYMMDD-NNN.Tstep         | composite PK
OBJ:TASK | type                  | ENUM   | Y | INTEGRITY_CHECK|CHECKPOINT|EXEC|FILE_WRITE|BUNDLE|SESSION_CLOSE|MANAGER_REVIEW|IMPACT_PLAN|SFR | -
# SFR = Six-Frame Review result. Logged to AUDIT-LOG before any PROTECTED-tier or R4-SOURCE write.
# Format: TASK:[run_id].SFR | TYPE:IMPACT_PLAN | TARGET:[file] | FRAMES:op=[G/Y/R],integrity=[G/Y/R],dep=[G/Y/R],state=[G/Y/R],token=[G/Y/R],failure=[G/Y/R] | VERDICT:[GREEN|YELLOW|RED] | RESULT:[PROCEED|BLOCKED]
# See SOUL.md §1b for frame definitions. A write with no preceding SFR entry is a protocol violation.
OBJ:TASK | result                | ENUM   | Y | PASS|FAIL|SUCCESS|BLOCKED|PARTIAL  | -

OBJ:RUN  | run_id                | TOKEN  | Y | PK RUN-YYYYMMDD-NNN               | unique per day
OBJ:RUN  | session               | ENUM   | Y | worker|manager                    | -
OBJ:RUN  | integrity_check       | ENUM   | Y | PASS|FAIL                         | -
OBJ:RUN  | outcome               | TEXT   | Y | NOT EMPTY                          | -

OBJ:CHANGELOG | field_path       | PATH   | Y | FILE:[path]#[field]               | -
OBJ:CHANGELOG | old_value        | STRING | Y | prior value or NONE               | -
OBJ:CHANGELOG | new_value        | STRING | Y | new value                         | -
OBJ:CHANGELOG | run_id           | TOKEN  | Y | FK→OBJ:RUN                        | -
OBJ:CHANGELOG | t_written        | ISO8601Z | Y | when agent wrote it             | -
OBJ:CHANGELOG | bundle           | TOKEN  | N | BUNDLE:[name] or none             | -

OBJ:PA   | pa_id                 | TOKEN  | Y | PK PA-NNN                         | -
OBJ:PA   | status                | ENUM   | Y | ACTIVE|EXPIRED|REVOKED            | -
OBJ:PA   | expires               | DATETIME | Y | YYYY-MM-DD HH:MM TZ             | -

OBJ:NOTIFY | priority            | ENUM   | Y | LOW|MEDIUM|HIGH|CRITICAL          | -
OBJ:NOTIFY | action_needed       | TEXT   | Y | NOT EMPTY                          | -

OBJ:MANIFEST | filepath          | PATH   | Y | PK relative to workspace root     | -
OBJ:MANIFEST | sha256            | HASH   | Y | exactly 64 hex chars              | -
OBJ:MANIFEST | verified_by       | STRING | Y | {OWNER}-re-signed-vNN|nightclaw-manager | -

---

## R3 — WRITE ROUTING
# File → tier → bundle. The complete routing table for all write decisions.
# Format: FILE-PATTERN | TIER | BUNDLE | NOTE
# TIER: APPEND=write immediately | STANDARD=scope+gate | PROTECTED={OWNER}-auth | MANIFEST-VERIFY=manager-timestamp-only

ACTIVE-PROJECTS.md(update)        | STANDARD        | BUNDLE:longrunner_update  | T6 state sync after pass
ACTIVE-PROJECTS.md(block)         | STANDARD        | BUNDLE:route_block        | T2/T2.7/T3 blocking
ACTIVE-PROJECTS.md(transition)    | STANDARD        | BUNDLE:phase_transition   | Phase complete
ACTIVE-PROJECTS.md(escalation)    | STANDARD        | BUNDLE:surface_escalation | Surfacing to {OWNER}
PROJECTS/*/LONGRUNNER.md          | STANDARD        | BUNDLE:longrunner_update  | Always via bundle, never raw
NOTIFICATIONS.md                  | APPEND          | BUNDLE:surface_escalation | Always via bundle
audit/AUDIT-LOG.md                | APPEND          | inline                    | Every step writes its own entry
audit/SESSION-REGISTRY.md         | APPEND          | BUNDLE:session_close      | T9 only
audit/CHANGE-LOG.md               | APPEND          | inline                    | Immediately after each field change in T4
audit/APPROVAL-CHAIN.md           | APPEND          | BUNDLE:pa_invoke          | T2.7 only
audit/INTEGRITY-MANIFEST.md       | MANIFEST-VERIFY | BUNDLE:manifest_verify    | Manager: timestamps only. {OWNER}: hashes.
memory/YYYY-MM-DD.md              | APPEND          | BUNDLE:session_close      | T9 only
PROJECTS/MANAGER-REVIEW-REGISTRY.md | STANDARD      | standalone                | Manager T7 only
orchestration-os/OPS-TOOL-REGISTRY.md | STANDARD    | standalone                | Worker T7a only
AGENTS.md                         | STANDARD        | standalone                | Navigation index — auto-injected by OpenClaw. {OWNER} edits only. Do not write behavioral content here.
AGENTS-CORE.md                    | PROTECTED       | none                      | {OWNER} only. Contains session contracts and behavioral rules. Re-sign after any edit.
AGENTS-LESSONS.md                 | APPEND          | standalone                | Worker T7d only — append behavior lessons. Never overwrite.
LOCK.md                           | STANDARD        | standalone                | Worker/manager STARTUP (write) and BUNDLE:session_close (release). Overwrite-in-place only.
orchestration-os/REGISTRY.md(append)     | STANDARD   | standalone                | Worker T7f — append new rows only. Never modify existing rows, never delete.
orchestration-os/REGISTRY.md(structural) | PROTECTED  | none                      | Any modification to existing rows, deletion, or section restructuring. {OWNER} only. Re-sign after.
orchestration-os/OPS-FAILURE-MODES.md | STANDARD    | standalone                | Worker T7c — NEVER delete entries
orchestration-os/OPS-QUALITY-STANDARD.md | STANDARD  | standalone               | Worker T7e
orchestration-os/OPS-KNOWLEDGE-EXECUTION.md | STANDARD | standalone             | Worker T7b
SOUL.md                           | PROTECTED       | none                      | {OWNER} only. Six-frame review.
USER.md                           | PROTECTED       | none                      | {OWNER} only.
IDENTITY.md                       | PROTECTED       | none                      | {OWNER} only.
MEMORY.md                         | PROTECTED       | none                      | {OWNER} only.
orchestration-os/CRON-WORKER-PROMPT.md  | PROTECTED  | none                     | {OWNER} only. Re-sign after.
orchestration-os/CRON-MANAGER-PROMPT.md | PROTECTED  | none                     | {OWNER} only. Re-sign after.
orchestration-os/OPS-PREAPPROVAL.md     | PROTECTED  | none                     | {OWNER} only. Re-sign after.
orchestration-os/OPS-AUTONOMOUS-SAFETY.md | PROTECTED | none                    | {OWNER} only. Re-sign after.
orchestration-os/CRON-HARDLINES.md      | PROTECTED  | none                     | {OWNER} only. Re-sign after.
[any unlisted file]               | STANDARD        | standalone                | Default. When in doubt.

---

## R4 — DEPENDENCY EDGES
# Typed edges for impact traversal. Format: SOURCE → TYPE → TARGET
# Types: READS|WRITES|VALIDATES|TRIGGERS|REFERENCES
# Read forward (grep SOURCE) to find what a change affects.
# Read reverse (grep TARGET) to find what depends on a file.

ACTIVE-PROJECTS.md    → READS      → PROJECTS/*/LONGRUNNER.md
ACTIVE-PROJECTS.md    → TRIGGERS   → BUNDLE:longrunner_update
ACTIVE-PROJECTS.md    → TRIGGERS   → BUNDLE:phase_transition
ACTIVE-PROJECTS.md    → TRIGGERS   → BUNDLE:route_block
PROJECTS/*/LONGRUNNER.md → WRITES  → ACTIVE-PROJECTS.md (via bundles)
PROJECTS/*/LONGRUNNER.md → WRITES  → audit/CHANGE-LOG.md (via T4)
BUNDLE:longrunner_update → WRITES  → PROJECTS/*/LONGRUNNER.md
BUNDLE:longrunner_update → WRITES  → ACTIVE-PROJECTS.md
BUNDLE:longrunner_update → WRITES  → audit/CHANGE-LOG.md
BUNDLE:longrunner_update → WRITES  → audit/AUDIT-LOG.md
BUNDLE:phase_transition  → WRITES  → PROJECTS/*/LONGRUNNER.md
BUNDLE:phase_transition  → WRITES  → ACTIVE-PROJECTS.md
BUNDLE:phase_transition  → WRITES  → NOTIFICATIONS.md
BUNDLE:phase_transition  → WRITES  → audit/CHANGE-LOG.md
BUNDLE:phase_transition  → WRITES  → audit/AUDIT-LOG.md
BUNDLE:route_block       → WRITES  → ACTIVE-PROJECTS.md
BUNDLE:route_block       → WRITES  → audit/CHANGE-LOG.md
BUNDLE:route_block       → WRITES  → audit/AUDIT-LOG.md
BUNDLE:surface_escalation → WRITES → NOTIFICATIONS.md
BUNDLE:surface_escalation → WRITES → ACTIVE-PROJECTS.md
BUNDLE:surface_escalation → WRITES → audit/AUDIT-LOG.md
BUNDLE:integrity_fail    → WRITES  → NOTIFICATIONS.md
BUNDLE:integrity_fail    → WRITES  → audit/AUDIT-LOG.md
BUNDLE:integrity_fail    → WRITES  → LOCK.md (release — releases lock before halting)
BUNDLE:pa_invoke         → WRITES  → audit/APPROVAL-CHAIN.md
BUNDLE:pa_invoke         → WRITES  → audit/AUDIT-LOG.md
BUNDLE:manifest_verify   → WRITES  → audit/INTEGRITY-MANIFEST.md (timestamps only)
BUNDLE:manifest_verify   → WRITES  → audit/AUDIT-LOG.md
BUNDLE:session_close     → WRITES  → audit/SESSION-REGISTRY.md
BUNDLE:session_close     → WRITES  → memory/YYYY-MM-DD.md
BUNDLE:session_close     → WRITES  → audit/AUDIT-LOG.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → SOUL.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → USER.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → IDENTITY.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → MEMORY.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → orchestration-os/CRON-WORKER-PROMPT.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → orchestration-os/CRON-MANAGER-PROMPT.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → orchestration-os/OPS-PREAPPROVAL.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → orchestration-os/OPS-AUTONOMOUS-SAFETY.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → orchestration-os/CRON-HARDLINES.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → orchestration-os/REGISTRY.md
audit/INTEGRITY-MANIFEST.md → VALIDATES → AGENTS-CORE.md
AGENTS-CORE.md              → REFERENCES → AGENTS-LESSONS.md
AGENTS-CORE.md              → REFERENCES → AGENTS.md
LOCK.md                     → READS      → worker:STARTUP
LOCK.md                     → READS      → manager:STARTUP
BUNDLE:session_close        → WRITES     → LOCK.md (release)
orchestration-os/OPS-PREAPPROVAL.md → AUTHORIZES → BUNDLE:pa_invoke
orchestration-os/OPS-PREAPPROVAL.md → REFERENCES → audit/APPROVAL-CHAIN.md
# Documentation cross-reference edges.
# These are structural facts, not value-level rules. When a SOURCE file changes,
# PW-2 surfaces the TARGET(s) for the agent to inspect for content consistency
# (matching paths, matching labels, matching protocol steps). The agent applies
# judgment about WHAT to check — these edges only record THAT a dependency exists.
README.md                              → REFERENCES → INSTALL.md
README.md                              → REFERENCES → DEPLOY.md
README.md                              → REFERENCES → orchestration-os/ORCHESTRATOR.md
INSTALL.md                             → REFERENCES → DEPLOY.md
orchestration-os/START-HERE.md         → REFERENCES → orchestration-os/CRON-WORKER-PROMPT.md

---

## R5 — BUNDLE SPECIFICATIONS
# Named multi-file write operations. The agent calls by name — gets complete spec.
# Format: BUNDLE:[name] | TRIGGER | WRITES (file → fields) | VALIDATES

BUNDLE:longrunner_update
  TRIGGER: T6 after pass completes (T5 PASS or WEAK)
  WRITES: PROJECTS/[slug]/LONGRUNNER.md → last_pass.{date,objective,output_files,quality}, next_pass.{objective,model_tier,context_budget,tools}
          ACTIVE-PROJECTS.md → last_worker_pass=[timestamp]
          audit/CHANGE-LOG.md → one entry per changed field
          audit/AUDIT-LOG.md → APPEND: TASK:[run].T6 TYPE:BUNDLE RESULT:SUCCESS
  VALIDATES: next_pass.objective NOT EMPTY | model_tier IN ENUM | quality IN ENUM

BUNDLE:phase_transition
  TRIGGER: T6 when LONGRUNNER stop_condition met
  WRITES: PROJECTS/[slug]/LONGRUNNER.md → phase.status=COMPLETE,
            transition_triggered_at=[ISO8601Z now],
            transition_expires=[ISO8601Z now + transition_timeout_days],
            transition_reescalation_count=0
          ACTIVE-PROJECTS.md → status=TRANSITION-HOLD, escalation_pending=phase-complete-[name]
          NOTIFICATIONS.md → PRIORITY:HIGH action_needed="Confirm phase transition"
          audit/CHANGE-LOG.md → entries for phase.status, transition_triggered_at, transition_expires, status, escalation_pending
          audit/AUDIT-LOG.md → APPEND: TASK:[run].T6 TYPE:BUNDLE RESULT:SUCCESS
  VALIDATES: current phase.status=ACTIVE | slug exists in DISPATCH

BUNDLE:route_block
  TRIGGER: T2 BLOCKED | T2.7 unauthorized | T3 tool unavailable
  WRITES: ACTIVE-PROJECTS.md → status=BLOCKED, escalation_pending=[reason]
          audit/CHANGE-LOG.md → entries for status, escalation_pending
          audit/AUDIT-LOG.md → APPEND: TASK:[run].T[step] TYPE:BUNDLE RESULT:BLOCKED
  VALIDATES: reason NOT EMPTY
  RETURNS: next eligible slug OR idle

BUNDLE:surface_escalation
  TRIGGER: Any condition requiring {OWNER} decision
  WRITES: NOTIFICATIONS.md → PRIORITY:[level] action_needed=[text] context=[text]
          ACTIVE-PROJECTS.md → escalation_pending=[reason]
          audit/AUDIT-LOG.md → APPEND: TASK:[run].T[step] TYPE:BUNDLE RESULT:SUCCESS
  VALIDATES: action_needed NOT EMPTY | priority IN ENUM

BUNDLE:integrity_fail
  TRIGGER: T0 hash mismatch or invalid output
  WRITES: NOTIFICATIONS.md → PRIORITY:CRITICAL action_needed="Re-sign manifest" context=[file,expected,computed]
          audit/AUDIT-LOG.md → APPEND: TASK:[run].T0 TYPE:INTEGRITY_CHECK RESULT:FAIL
          LOCK.md → OVERWRITE IN PLACE: status=released, run_id=—, holder=—, locked_at=—, expires_at=—
  NEVER WRITES: audit/INTEGRITY-MANIFEST.md ({OWNER} only)
  RETURNS: HALT (lock released before halt — T9 does not run on integrity failure)

BUNDLE:pa_invoke
  TRIGGER: T2.7 when exec/extended write needed
  VALIDATES FIRST: PA exists | status=ACTIVE | expires>now | all scope fields MATCH
  IF VALID:
    WRITES: audit/APPROVAL-CHAIN.md → PA-NNN-INV-NNN | scope verification | result
            audit/AUDIT-LOG.md → APPEND: TASK:[run].T2.7 TYPE:BUNDLE RESULT:SUCCESS
  IF INVALID: calls BUNDLE:surface_escalation then BUNDLE:route_block
  RETURNS: AUTHORIZED | BLOCKED

BUNDLE:manifest_verify
  TRIGGER: Manager T1 — all hashes match
  WRITES: audit/INTEGRITY-MANIFEST.md → last_verified=[date] verified_by=nightclaw-manager (TIMESTAMPS ONLY)
          audit/AUDIT-LOG.md → APPEND: TASK:[run].T1 TYPE:INTEGRITY_CHECK RESULT:PASS
  AUTHORITY: manager-authority standing auth covers timestamp-only writes. No P1 required.

BUNDLE:session_close
  TRIGGER: T9 — end of every pass
  WRITES: audit/SESSION-REGISTRY.md → APPEND new row: RUN-ID | session | model | tokens | integrity | outcome
          memory/YYYY-MM-DD.md → APPEND structured pass log (never overwrite existing content)
          audit/AUDIT-LOG.md → APPEND one line: TASK:[run].T9 TYPE:SESSION_CLOSE RESULT:SUCCESS (APPEND ONLY — never overwrite)
          LOCK.md → OVERWRITE IN PLACE: status=released, run_id=—, holder=—, locked_at=—, expires_at=—, consecutive_pass_failures: 0
  VALIDATES: outcome NOT EMPTY | run_id not already in SESSION-REGISTRY

---

## R6 — SELF-CONSISTENCY RULES
# Checked by manager T8. Format: RULE | ASSERTION | HOW TO VERIFY | SEVERITY

SCR-01 | Every BUNDLE: name in R3 exists as a BUNDLE: definition in R5              | grep R3 bundles vs R5 headers          | HIGH
SCR-02 | Every FK→OBJ: in R2 resolves to an OBJ: entry in R1                       | grep FK→OBJ values vs R1 OBJ entries   | HIGH
SCR-03 | Every file in R3 PROTECTED tier is in audit/INTEGRITY-MANIFEST.md          | grep PROTECTED vs manifest rows        | CRITICAL
SCR-04 | audit/CHANGE-LOG.md exists                                                 | file existence check                   | HIGH
SCR-05 | audit/SESSION-REGISTRY.md run_ids are unique (no duplicate RUN-YYYYMMDD-N) | scan for duplicate ## entries          | HIGH
SCR-06 | Every BUNDLE: in R4 edges resolves to a definition in R5                   | grep R4 BUNDLE: refs vs R5 headers     | MEDIUM
SCR-07 | For any file modified this cycle that has outbound REFERENCES edges in R4,     | grep SOURCE in R4 for REFERENCES edges; read each TARGET; verify cross-referenced | HIGH
        | content in all downstream REFERENCES targets remains consistent (matching paths, | content (paths, labels, protocol steps) is still consistent with SOURCE           |
        | labels, protocol steps). No value is hardcoded here — agent applies judgment.  |                                                                                   |
SCR-08 | LOCK.md status must be "released" at session close per BUNDLE:session_close.   | grep AUDIT-LOG for SESSION_CLOSE entries; confirm each has a corresponding        | HIGH
        | Any session in AUDIT-LOG without a LOCK.md release is a potential crash.       | LOCK.md overwrite in the session. Cross-ref LOCK_STALE entries for context.      |

---

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

PROTECTED-PATHS:
  FILE:SOUL.md
  FILE:USER.md
  FILE:IDENTITY.md
  FILE:MEMORY.md
  FILE:orchestration-os/CRON-WORKER-PROMPT.md
  FILE:orchestration-os/CRON-MANAGER-PROMPT.md
  FILE:orchestration-os/OPS-PREAPPROVAL.md
  FILE:orchestration-os/OPS-AUTONOMOUS-SAFETY.md
  FILE:orchestration-os/CRON-HARDLINES.md
  FILE:orchestration-os/REGISTRY.md

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
