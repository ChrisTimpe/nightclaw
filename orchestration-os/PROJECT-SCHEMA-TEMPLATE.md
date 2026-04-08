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

<!-- LONGRUNNER fields (all projects share these) -->
FILE:LONGRUNNER | phase.status      | ENUM   | Y | ACTIVE|BLOCKED|COMPLETE      | -
FILE:LONGRUNNER | next_pass.objective | TEXT | Y | NOT EMPTY                    | stale-halt if empty
FILE:LONGRUNNER | next_pass.model_tier | ENUM| Y | lightweight|standard|heavy   | -
FILE:LONGRUNNER | last_pass.quality | ENUM   | N | STRONG|ADEQUATE|WEAK|FAIL    | -
FILE:LONGRUNNER | last_pass.date    | DATE   | N | YYYY-MM-DD                   | -

<!-- Add project-specific output file field contracts below -->
<!-- Example for a diff output: -->
<!-- FILE:DIFF-OUTPUT | plant_id | INT | Y | 5-7 digit [data-source] plant code | FK→[external-data-source] -->
<!-- FILE:DIFF-OUTPUT | generator_id | STRING | Y | [data-source] generator identifier | - -->
<!-- FILE:DIFF-OUTPUT | change_type | ENUM | Y | ADDED|REMOVED|MODIFIED | - -->

---

## PS3 — WRITE BUNDLES
<!-- Project-level named write operations. Same concept as OS SCHEMA.md S3. -->
<!-- Format: BUNDLE:[name] | TRIGGER | WRITES | VALIDATES -->

BUNDLE:project-state-update
  TRIGGER: Pass completes (T6 of worker pass)
  WRITES:
    PROJECTS/[slug]/LONGRUNNER.md → last_pass.*, next_pass.*
    PROJECTS/[slug]/audit/CHANGE-LOG.md → field-level entries for changed fields
  VALIDATES: next_pass.objective NOT EMPTY | last_pass.quality IN ENUM

BUNDLE:signal-append
  TRIGGER: New demand signal discovered and validated
  WRITES:
    [slug]/04-demand-signals/demand-log.md → one dated non-duplicate row
    [slug]/07-index/routing-log.md → routing entry
  VALIDATES: signal not already in log (dedup check) | source URL present

---

## PS4 — PROJECT CONSTRAINT INDEX
<!-- Format: FILE | CONSTRAINTS THAT APPLY -->

FILE:LONGRUNNER    | C1(next_pass.objective NOT EMPTY) C2(phase.status IN ENUM) C3(model_tier IN ENUM)
FILE:DEMAND-LOG    | C4(append-only) C5(no duplicate date+source combinations)
FILE:DIFF-OUTPUT   | C6(date-stamped filename) C7(at least one data row beyond header)
FILE:CHANGE-LOG    | C8(append-only) C9(run_id present on every entry)

---

## Maintenance

This file is maintained by:
- {OWNER}: structural changes (add/remove files, change field contracts)
- Worker T7f: add new field contract or constraint discovered during a pass
- Manager T8: verify this schema is consistent with actual project file structures

When this file changes: append to PROJECTS/[slug]/audit/CHANGE-LOG.md.
