# START-HERE.md

<!-- Read this first. Every time. Takes 90 seconds. -->

## Three rules you must never violate

1. **Check phase before acting.** Read `LONGRUNNER.md`. If `phase.status == "complete"` → delete the scheduler, stop. Never do work on a completed phase.
2. **Check tools before starting.** If a pass needs more than file read/write, check `OPS-TOOL-REGISTRY.md` first. If a required tool is UNVERIFIED or UNAVAILABLE → surface the gap, do not begin.
3. **Write before you end.** Every pass ends with LONGRUNNER updated (`last_pass`, `next_pass`) and `memory/YYYY-MM-DD.md` updated. A pass that doesn't update state didn't happen.

---

## What to read for each situation

| Situation | Read this |
|---|---|
| Starting a new project | This file → `LONGRUNNER-TEMPLATE.md` (core section only) → `OPS-TOOL-REGISTRY.md` |
| Running a worker pass | `LONGRUNNER.md` (current project) → three rules above |
| Something went wrong | `OPS-FAILURE-MODES.md` — find the failure class before retrying |
| Phase feels complete | `ORCHESTRATOR.md` §Step 4B — phase transition protocol |
| Direction feels wrong | `CRON-MANAGER-PROMPT.md` T4–T5 (value check + direction check) → `OPS-QUALITY-STANDARD.md` §Manager Value Methodology |
| Need to write a script for a known system | `OPS-KNOWLEDGE-EXECUTION.md` → System Registry → field map → script template |
| Running multiple tasks in parallel | Not supported. Use sequential priority via `ACTIVE-PROJECTS.md` — highest priority runs first. |
| Best path needs approval | `OPS-PREAPPROVAL.md` (pre-authorize) → `OPS-AUTONOMOUS-SAFETY.md` §Authorization Model (runtime) |
| Running any autonomous/scheduled pass | `OPS-AUTONOMOUS-SAFETY.md` — pre-flight safety checklist |
| No active projects in dispatch table | `OPS-IDLE-CYCLE.md` — ranked autonomous value work |
| Encountered a cross-domain signal mid-pass | `CRON-WORKER-PROMPT.md` T7 — log the signal as an OS note, do not derail the active pass |
| Want to understand the full system | This file → `REGISTRY.md` (structural map) → `CRON-WORKER-PROMPT.md` (execution flow) |

---

## The always-on system in one paragraph

Two crons run permanently: a **worker pulse** (every 3h on a dynamically managed execution-class model, custom session) and a **manager pulse** (once per day on a more capable judgment-class model, custom session). Both are project-agnostic — they read `ACTIVE-PROJECTS.md` to determine what to work on. Adding a project = adding a row to that file. Shifting focus = changing priority numbers. Pausing = setting status to "paused". The crons never stop; the dispatch table controls what they do. See `orchestration-os/OPS-CRON-SETUP.md` for setup.

## Each long-running project in one paragraph

Every long-running project lives in a **LONGRUNNER.md** control file. It declares a **phase** with a verifiable stop condition. A **worker** executes bounded passes, validates output, and updates state. A **manager** runs every 3–5 passes and checks direction, value, and leverage. When a phase completes, the scheduler is deleted and {OWNER} confirms before the next phase opens. The system compounds: each project leaves behind field maps, script templates, and failure mode notes so the next project starts faster.

---

## The one thing that kills the system

Letting a scheduler outlive its phase. Every time a worker wakes, it reads the LONGRUNNER and checks phase.status. That check is the circuit breaker. Without it, stale wakes consume budget and produce nothing. With it, the loop always knows when to stop.

---

## File map (full system)

| File | Layer | One-line purpose |
|---|---|---|
| `START-HERE.md` | — | This file. Read first. |
| `ORCHESTRATOR.md` | Runtime | Multi-project dispatch logic + phase transition protocol |
| `CRON-WORKER-PROMPT.md` | Runtime | Worker cron session protocol (T0–T9 execution flow) |
| `CRON-MANAGER-PROMPT.md` | Runtime | Manager cron session protocol (orchestration + direction) |
| `CRON-HARDLINES.md` | Discipline | Distilled SOUL.md behavioral constraints for cron sessions |
| `REGISTRY.md` | Substrate | System catalog: objects, write routing, dependencies, bundles |
| `OPS-TOOL-REGISTRY.md` | Substrate | Tool constraint knowledge |
| `TOOL-STATUS.md` | Substrate | Fast pre-flight tool check (~200 tokens) |
| `OPS-KNOWLEDGE-EXECUTION.md` | Substrate | Field maps + script templates for known systems |
| `OPS-FAILURE-MODES.md` | Substrate | Indexed failure registry — diagnose before retrying |
| `OPS-QUALITY-STANDARD.md` | Substrate | Three-question quality test for every pass |
| `OPS-AUTONOMOUS-SAFETY.md` | Discipline | Behavioral discipline contract + blocker decision tree (self-healing core) |
| `OPS-PREAPPROVAL.md` | Approval | Pre-authorize action classes for overnight unattended runs |
| `OPS-CRON-SETUP.md` | Setup | Cron configuration guide + cadence management |
| `LONGRUNNER-TEMPLATE.md` | Runtime | Control file template — copy for each new project |
| `OPS-IDLE-CYCLE.md` | Runtime | Autonomous work when no active project exists |
| `OPS-PASS-LOG-FORMAT.md` | Runtime | Structured daily memory log format |
| `PROJECT-SCHEMA-TEMPLATE.md` | Runtime | Per-project schema template |
