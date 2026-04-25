# OPS-IDLE-CYCLE.md
<!-- Read when: ACTIVE-PROJECTS.md has no actionable rows (all paused, blocked, or transition-hold) -->
<!-- Purpose: turn idle cron cycles into compounding value instead of wasted tokens -->

## Pre-check: NOTIFICATIONS.md (mandatory before entering ladder)

Execute: python3 scripts/nightclaw-ops.py scan-notifications
Output: FOUND:line=<n>:<summary> entries, or NONE.

FOUND at least one:
  Take the first (oldest) FOUND entry.
  Execute it as this pass's objective.
  Log: TASK:[run_id].T4 | TYPE:CHECKPOINT | PROJECT:notifications | OBJECTIVE:[one-line summary]
  After execution, mark the entry DONE in NOTIFICATIONS.md (prepend [DONE] to the line).
  RETURN to caller (T1.5 or BLOCKER PROTOCOL). Do NOT enter the priority ladder below.

NONE:
  Proceed to the priority ladder below.

---

## The Rule

An idle cycle is not a failed cycle. It is a cycle with no active project work — which means it is available for autonomous OS improvement. The system runs nonstop. When project work pauses, the OS improves.

**Never write "nothing to do" and stop.** Always select from the ranked list below.

---

## Idle Cycle Priority Ladder

Work through this list in order. Execute the first item that has actionable work. Do one bounded pass. Stop.

### Tier 1 — Active Intelligence (highest value, time-sensitive)

> **Prerequisite:** Tier 1 requires a configured `[knowledge-repo]` directory in your workspace.
> If `[knowledge-repo]` has not been set up (no directory exists at that path), **skip Tier 1 entirely** and proceed directly to Tier 2.
> To enable Tier 1: create the knowledge-repo directory structure, configure its path in `USER.md`, and update the `[knowledge-repo]` references throughout this file to match your chosen path.
> A fresh install with no knowledge-repo configured is a valid state — Tier 2 provides full value on its own.

**1a. Opportunity-intel inbox scan**
- Check whether `[knowledge-repo]/00-inbox/` exists. If not: skip to 1b.
- If directory exists and contains files: process up to 3, route to the correct `02-opportunities/` or `04-demand-signals/` directory, update `07-index/index.md`
- Log each routing decision in `07-index/routing-log.md`
- If inbox is empty or directory absent: move to 1b

**1b. Staleness check**
- Check whether `[knowledge-repo]/07-index/staleness-log.md` exists. If not: skip to 1c.
- If file exists and any opportunity is flagged >90 days stale: append a staleness note and surface to {OWNER} via `NOTIFICATIONS.md`
- If nothing stale or file absent: move to 1c

**1c. Demand signal scan**
- One targeted web search per idle cycle (within tool budget)
- Query pattern: `"[top opportunity domain] [problem keyword] consulting demand 2026"`
- If a signal found and `[knowledge-repo]` is configured: append to `[knowledge-repo]/04-demand-signals/demand-log.md` with URL and date
- If a signal found but `[knowledge-repo]` is not configured: append finding to `NOTIFICATIONS.md` as a MEDIUM entry for {OWNER} to route manually
- If nothing found: move to Tier 2

---

### Tier 2 — Knowledge Base Maintenance

**2a. Research source freshness**
- Read `[knowledge-repo]/07-index/index.md` (skip if [knowledge-repo] is not configured)
- Identify any source marked trend-sensitive that is older than 60 days
- Flag in `[knowledge-repo]/07-index/index.md` as `stale — review needed`
- Surface to {OWNER} if a stale source affects active project direction

**2b. OPS file review**
- Scan `orchestration-os/OPS-FAILURE-MODES.md` for entries marked OPEN
- If any OPEN entry has been idle >7 days without resolution: surface to {OWNER} via `NOTIFICATIONS.md`
- If none: move to 2c

**2c. TOOL-STATUS.md sync**
- Compare `TOOL-STATUS.md` quick-reference against `OPS-TOOL-REGISTRY.md` for any entries that differ
- If out of sync: update `TOOL-STATUS.md`
- If in sync: move to Tier 3

---

### Tier 3 — Memory and OS Improvement

**3a. Memory dream pass (if triggered)**
- Check trigger: count dated files in `memory/` (files named YYYY-MM-DD.md). If 5 or more exist, trigger.
- If triggered: read recent memory/ files → write consolidated summary to today's memory/YYYY-MM-DD.md → append one-line consolidation marker. See `HEARTBEAT.md` Memory Consolidation section.
- NEVER write to `MEMORY.md` — that is a PROTECTED bootstrap file. All dream pass writes go to dated files in memory/.
- If not triggered (fewer than 5 files): move to 3b

**3b. AGENTS.md / OPS file improvement**
- Review most recent 3 memory entries for any lesson, pattern, or correction not yet encoded in AGENTS.md or an OPS file
- If found: add it (one sentence minimum)
- If nothing new to encode: move to 3c

**3c. MANAGER-REVIEW-REGISTRY.md housekeeping**
- Read `PROJECTS/MANAGER-REVIEW-REGISTRY.md`
- Prune rows for projects marked `complete` or `abandoned` older than 30 days (move to archive section)
- Verify all active rows have a `review_due` date that is current
- If all clean: proceed to Tier 4

---

### Tier 4 — New Project Identification (lowest priority, highest leverage when triggered)

**4a. Autonomous project proposal**

Run this ONLY when ALL of the following are true:
- All Tier 1–3 items are clean/current
- No new project is already staged as a `LONGRUNNER-DRAFT.md` anywhere in `PROJECTS/`
- ANY ONE of these conditions is met (OR logic — only one needs to be true):
  - CONDITION A: No active projects exist at all (fresh install, or all projects are complete/paused/blocked)
  - CONDITION B: A project completed in the last 30 days and no successor project is defined
  - CONDITION C: Any project has status=TRANSITION-HOLD as of the start of this pass

Evaluate each condition independently. If ANY ONE is true, proceed to Path A or Path B below.
Do NOT require all three conditions to be true simultaneously.

**Path A — knowledge-repo configured:**
1. Read `[knowledge-repo]/07-index/index.md` — identify the highest-ranked opportunity not yet in a LONGRUNNER
2. Read the opportunity file — confirm it passes the conflict-of-interest filter in `USER.md`
3. Draft a minimal LONGRUNNER for it (mission, phase 1 objective, stop condition, first next_pass)
4. Write to `PROJECTS/[slug]/LONGRUNNER-DRAFT.md`
5. Surface to `NOTIFICATIONS.md` as MEDIUM

**Path B — no knowledge-repo (fresh install or not yet configured):**
1. Read `SOUL.md` — extract the Domain Anchor
2. Read `USER.md` — note any domain restrictions or conflict-of-interest constraints
3. Derive a first research project from the Domain Anchor. It should be:
   - Directly relevant to the stated domain
   - Executable with web search + file writes only (no external posting, no exec approval needed)
   - Scoped to a single exploration phase deliverable (a structured discovery document)
   - Named with a clear, lowercase slug (e.g. `domain-landscape`, `tool-evaluation`, `market-signals`)
4. Draft a minimal LONGRUNNER: mission, conflict check, phase `exploration`, stop condition, next_pass objective
5. Write to `PROJECTS/[slug]/LONGRUNNER-DRAFT.md` (not LONGRUNNER.md — owner confirms before worker dispatches)
6. Append to `NOTIFICATIONS.md`:
   ```
   [timestamp] | Priority: MEDIUM | Project: [slug] | Status: PENDING-REVIEW
   Proposal: First project drafted from Domain Anchor in SOUL.md
   Proposed path: Begin exploration phase — web research, structured discovery document
   Estimated cost: STANDARD
   Blocking current work: NO
   If approved: rename LONGRUNNER-DRAFT.md to LONGRUNNER.md, add row to ACTIVE-PROJECTS.md, begin on next worker pass
   If declined: delete draft, owner defines project manually
   ```

**The owner's morning action (either path):**
- From terminal (zero tokens): `nightclaw-admin approve <slug>` or `nightclaw-admin decline <slug>`
- Or open main session — agent surfaces the draft, say "approve" or "decline".
- No response needed at all if owner wants to define projects manually — draft sits inert until reviewed.

---

## Idle Cycle Output Standard

Every idle cycle must produce at least one of:
- A file updated with new content (routing log, demand log, staleness flag, memory update)
- A NOTIFICATIONS.md entry with actionable content for {OWNER}
- A TOOL-STATUS.md or OPS file improvement

If none of these are achievable (every tier checked, nothing actionable):
- Write one line to `memory/YYYY-MM-DD.md`: `[IDLE CYCLE — timestamp] All tiers checked. No actionable work found. System current.`
- Stop

A clean system is a valid output. An idle cycle that confirms the system is current is not wasted — it is evidence of health.
