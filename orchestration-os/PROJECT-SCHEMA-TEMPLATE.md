# PROJECT-SCHEMA-TEMPLATE.md
<!-- Template for project-level schema files. Copy to PROJECTS/[slug]/SCHEMA.md on project creation. -->
<!-- Applies the same framework as orchestration-os/SCHEMA.md but scoped to one project. -->
<!-- Agent validates project file writes against this before executing BUNDLE:longrunner_update. -->

---

## Why Projects Have Their Own Schema

The OS SCHEMA.md governs control-plane files. Project files have their own structure:
output CSVs, demand logs, scoring files, research artifacts. Without a schema, the agent
re-derives structure from whatever it finds — inconsistent formats, missing fields, broken
downstream reads. With a schema, every project file has a defined contract.

Same principle as the OS. One level down.

---

## PS1 — PROJECT FILE REGISTRY
<!-- What files this project owns, where they live, what identifies them. -->
<!-- Format: FILE | PATH-PATTERN | PK | APPEND-ONLY? -->

<!-- Replace with project-specific entries. Examples: -->
FILE:LONGRUNNER      | PROJECTS/[slug]/LONGRUNNER.md                  | singleton    | NO
FILE:DEMAND-LOG      | [slug]/04-demand-signals/demand-log.md          | date+source  | YES
FILE:DIFF-OUTPUT     | PROJECTS/[slug]/outputs/eia860m-diff-YYYY-MM-DD.csv | date      | NO
FILE:SCORED-LIST     | PROJECTS/[slug]/outputs/scored-shortlist-YYYY-MM-DD.md | date   | NO
FILE:ROUTING-LOG     | [slug]/07-index/routing-log.md                  | date         | YES
FILE:CHANGE-LOG      | PROJECTS/[slug]/audit/CHANGE-LOG.md             | none         | YES

---

## PS2 — FIELD CONTRACTS
<!-- Format: FILE | FIELD | TYPE | REQ | VALUES/FORMAT | CONSTRAINT -->
<!-- Source of truth: orchestration-os/schema/fields.yaml OBJ:PROJ entries. -->
<!-- Keep this table in sync with fields.yaml when adding new fields. -->

<!-- LONGRUNNER fields — all projects share these. Written by OS bundles. -->
<!-- phase.* fields -->
FILE:LONGRUNNER | phase.status                   | ENUM     | Y | ACTIVE\|BLOCKED\|COMPLETE                      | -
FILE:LONGRUNNER | phase.name                     | TOKEN    | Y | current phase name                             | -
FILE:LONGRUNNER | phase.objective                | TEXT     | Y | NOT EMPTY                                      | -
FILE:LONGRUNNER | phase.stop_condition           | TEXT     | N | testable stop condition                        | -
FILE:LONGRUNNER | phase.started                  | DATE     | N | YYYY-MM-DD                                     | -
FILE:LONGRUNNER | phase.successor                | TEXT     | N | next phase name                                | worker proposes at T6 phase_transition
FILE:LONGRUNNER | transition_triggered_at        | ISO8601Z | N | timestamp when phase_transition bundle fired   | set by BUNDLE:phase_transition
FILE:LONGRUNNER | transition_expires             | ISO8601Z | N | deadline for {OWNER} direction                 | triggered_at + transition_timeout_days
FILE:LONGRUNNER | transition_reescalation_count  | INT      | N | 0–3                                            | default=0; auto-pauses at 3

<!-- last_pass.* fields — written by BUNDLE:longrunner_update at T6 -->
FILE:LONGRUNNER | last_pass.date                 | DATE     | N | YYYY-MM-DD                                     | -
FILE:LONGRUNNER | last_pass.objective            | TEXT     | N | prior pass objective                           | -
FILE:LONGRUNNER | last_pass.output_files         | TEXT     | N | comma-separated file paths                     | -
FILE:LONGRUNNER | last_pass.quality              | ENUM     | N | STRONG\|ADEQUATE\|WEAK\|FAIL                   | -
FILE:LONGRUNNER | last_pass.validation_passed    | BOOL     | N | true\|false                                    | did output meet pass_output_criteria?
FILE:LONGRUNNER | last_pass.weak_pass            | BOOL     | N | true\|false                                    | true if all 4 value tests failed

<!-- next_pass.* fields — written by BUNDLE:longrunner_update at T6 -->
FILE:LONGRUNNER | next_pass.objective            | TEXT     | Y | NOT EMPTY                                      | stale-halt if empty
FILE:LONGRUNNER | next_pass.model_tier           | ENUM     | Y | lightweight\|standard\|heavy                   | default=standard
FILE:LONGRUNNER | next_pass.context_budget       | ENUM     | Y | 40K\|80K\|120K\|200K                           | default=80K; written by longrunner_update
FILE:LONGRUNNER | next_pass.tools_required       | TEXT     | N | comma-separated tool names                     | -
FILE:LONGRUNNER | next_pass.pass_type            | TOKEN    | N | build-iteration\|research\|...                 | -

<!-- Add project-specific output file field contracts below -->
<!-- Example for a diff output: -->
<!-- FILE:DIFF-OUTPUT | plant_id | INT | Y | 5-7 digit [data-source] plant code | FK→[external-data-source] -->
<!-- FILE:DIFF-OUTPUT | generator_id | STRING | Y | [data-source] generator identifier | - -->
<!-- FILE:DIFF-OUTPUT | change_type | ENUM | Y | ADDED|REMOVED|MODIFIED | - -->

---

## PS3 — WRITE BUNDLES
<!-- Project-level named write operations. Same concept as OS SCHEMA.md S3. -->
<!-- OS bundle names must exactly match entries in orchestration-os/schema/bundles.yaml. -->

<!-- OS bundle: fires at T6 after every completed pass. Writes last_pass.* and next_pass.* -->
BUNDLE:longrunner_update
  TRIGGER: Pass completes (T6, quality STRONG|ADEQUATE|WEAK)
  ARGS: slug, run_id, quality, objective, output_files, next_objective, model_tier, context_budget, tools
  GUARDS:
    phase.status EQUALS ACTIVE
    next_objective NOT_EMPTY
    quality IN STRONG,ADEQUATE,WEAK,FAIL
    model_tier IN lightweight,standard,heavy
  WRITES:
    PROJECTS/[slug]/LONGRUNNER.md → last_pass.date, last_pass.objective, last_pass.output_files,
                                     last_pass.quality, next_pass.objective, next_pass.model_tier,
                                     next_pass.context_budget, next_pass.tools_required
    ACTIVE-PROJECTS.md → DISPATCH row last_worker_pass
    audit/AUDIT-LOG.md → TASK:{run_id}.T6 row (append)

<!-- OS bundle: fires at T6 when stop_condition is met. Triggers phase transition hold. -->
BUNDLE:phase_transition
  TRIGGER: T6 when LONGRUNNER stop_condition met
  ARGS: slug, run_id, successor, escalation_text, action_text
  GUARDS:
    phase.status EQUALS ACTIVE
  WRITES:
    PROJECTS/[slug]/LONGRUNNER.md → phase.status=COMPLETE, phase.successor, transition_triggered_at, transition_expires, transition_reescalation_count
    ACTIVE-PROJECTS.md → DISPATCH row status=TRANSITION-HOLD, escalation_pending
    audit/AUDIT-LOG.md → TASK:{run_id}.T6 row (append)
    NOTIFICATIONS.md → HIGH priority escalation (append)

<!-- Project-specific bundle example — replace with actual project signal bundles if needed -->
<!-- BUNDLE:signal-append is not an OS bundle; declare project-specific bundles here -->
<!--
BUNDLE:signal-append
  TRIGGER: New demand signal discovered and validated
  WRITES:
    [slug]/04-demand-signals/demand-log.md → one dated non-duplicate row
    [slug]/07-index/routing-log.md → routing entry
  VALIDATES: signal not already in log (dedup check) | source URL present
-->

---

## PS4 — PROJECT CONSTRAINT INDEX
<!-- Format: FILE | CONSTRAINTS THAT APPLY -->

FILE:LONGRUNNER    | C1(next_pass.objective NOT EMPTY) C2(phase.status IN ENUM) C3(model_tier IN ENUM) C4(context_budget IN ENUM)
FILE:DEMAND-LOG    | C5(append-only) C6(no duplicate date+source combinations)
FILE:DIFF-OUTPUT   | C7(date-stamped filename) C8(at least one data row beyond header)
FILE:CHANGE-LOG    | C9(append-only) C10(run_id present on every entry)

---

## Maintenance

This file is maintained by:
- {OWNER}: structural changes (add/remove files, change field contracts)
- Worker T7f: add new field contract or constraint discovered during a pass
- Manager T8: verify this schema is consistent with actual project file structures

When field contracts change: verify against `orchestration-os/schema/fields.yaml` OBJ:PROJ entries.
When this file changes: append to PROJECTS/[slug]/audit/CHANGE-LOG.md.
