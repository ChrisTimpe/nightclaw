# OPS-CRON-SETUP.md
<!-- The exact cron configuration for the always-on system. -->
<!-- Deploy these two crons. Everything else is file-driven. -->
<!-- Update cadence here when you observe actual pass durations. -->

---

## The System Runs on Two Crons

That's it. Two. Not one per project. Not one per phase. Two crons total, running always.

```
CRON 1: WORKER PULSE     — fires every N minutes, executes bounded project work
CRON 2: MANAGER PULSE    — fires every M minutes (M > N), governs direction and value
```

When you add a new project, you add a row to ACTIVE-PROJECTS.md. You do not add a cron.
When a project completes, it exits the dispatch table. You do not delete a cron.
The crons are permanent. The dispatch table is dynamic.

---

## Cron 1: Worker Pulse

**Purpose:** Execute one bounded project pass per cycle. Self-routing via ACTIVE-PROJECTS.md.

**Task description to configure:**

> The full task text lives in `orchestration-os/CRON-WORKER-PROMPT.md` v0.1.0.
> The `--message` is a short routing stub — the agent reads CRON-WORKER-PROMPT.md for full instructions.
> Do not embed the full prompt here — this file would become stale on every version bump.
> Copy the exact `--message` from the **Create Command** section of CRON-WORKER-PROMPT.md.

```
HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-WORKER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps.
```

**Recommended starting cadence:** Every 3 hours
**Rate limit note ($20 OAuth plan):** Community reports show autonomous agents exhaust the 5-hour window in 2–5 tasks. A 3-hour cadence (~8 passes/day) keeps token spend well within the $20/month OAuth budget. After observing 3–5 real pass durations in `memory/YYYY-MM-DD.md`, tighten if passes are consistently short (< 10 min) and budget allows.
**Adjust after observing:** Check `memory/YYYY-MM-DD.md` pass logs after 3 cycles. If passes average < 15 min and you have budget headroom, shorten to 1h. If passes run heavy or hit rate limits, widen to 6h.

**Name this cron:** `nightclaw-worker-trigger`
**Session flag:** `--session "session:nightclaw-worker" --light-context`
**Interval flag:** `--every 3h`
**Model flag:** `--model anthropic/claude-haiku-3-5`
**Delivery flag:** `--no-deliver`

> **Format change in 2026.4.1:** `--every` now takes human-readable strings (`60m`, `1h`, `1d`). Millisecond values (e.g. `3600000`) are no longer valid and will error.
> **`--no-deliver` is required** for custom session crons (`session:xxx`). Without it, OpenClaw defaults to `delivery.channel: last`, which fails with "Channel is required" because custom sessions have no prior chat history to resolve against.

---

## Cron 2: Manager Pulse

**Purpose:** Govern direction, value, priority, and escalations across all active projects.

**Task description to configure:**

> The full task text lives in `orchestration-os/CRON-MANAGER-PROMPT.md` v0.1.0.
> The `--message` is a short routing stub — the agent reads CRON-MANAGER-PROMPT.md for full instructions.
> Do not embed the full prompt here — this file would become stale on every version bump.
> Copy the exact `--message` from the **Create Command** section of CRON-MANAGER-PROMPT.md.

```
HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-MANAGER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps.
```

**Recommended starting cadence:** Every 24 hours (1 pass/day — the manager governs direction, not execution)
**Name this cron:** `nightclaw-manager-trigger`
**Session flag:** `--session "session:nightclaw-manager" --light-context`
**Interval flag:** `--every 1d`
**Model flag:** `--model anthropic/claude-sonnet-4-6`
**Delivery flag:** `--no-deliver`

> **Format change in 2026.4.1:** `--every` now takes human-readable strings. Use `1d` not milliseconds.
> **`--no-deliver` is required** — same reason as worker cron above.

---

## Setup Checklist

```
□ Cron 1 created: nightclaw-worker-trigger, every 3h, --model anthropic/claude-haiku-3-5, session:nightclaw-worker, --light-context
□ Cron 2 created: nightclaw-manager-trigger, every 1d, --model anthropic/claude-sonnet-4-6, session:nightclaw-manager, --light-context
□ ACTIVE-PROJECTS.md exists in workspace root with at least one active row
□ Each active project has a valid LONGRUNNER.md with:
    □ phase.status = "active"
    □ next_pass objective defined (not blank, not "awaiting confirmation")
    □ pass_output_criteria defined
    □ dispatch LONGRUNNER path exists on disk and matches ACTIVE-PROJECTS.md exactly
    □ next_pass input/output paths resolve to real repo locations (no stale path references)
□ orchestration-os/OPS-TOOL-REGISTRY.md reviewed — tools used in first pass are AVAILABLE
□ For script-based next_pass objectives, command executable paths are host-valid (prefer PATH-resolved commands like `python3` over hardcoded absolute paths unless verified)
□ memory/ directory exists (created automatically if not)
□ PROJECTS/MANAGER-REVIEW-REGISTRY.md exists (create minimal version if not)
```

---

## How to Add a New Project (No New Crons)

```
1. Copy orchestration-os/LONGRUNNER-TEMPLATE.md → PROJECTS/[slug]/LONGRUNNER.md
2. Fill in: mission, phase.name, phase.objective, phase.stop_condition, next_pass
3. Add one row to ACTIVE-PROJECTS.md: priority, slug, LONGRUNNER path, phase, status: active
4. Done. Next worker pulse picks it up automatically.
```

---

## How to Pause a Project (No Cron Changes)

```
1. In ACTIVE-PROJECTS.md: set status to "paused"
2. Done. Next worker pulse skips it. Current pass (if running) finishes naturally.
```

---

## How to Shift Focus (Zero Downtime)

```
1. In ACTIVE-PROJECTS.md: update the Priority column — renumber rows
2. Done. Next worker pulse routes to the new highest priority.
```

---

## How to Emergency Stop Everything

```
1. In ACTIVE-PROJECTS.md: set ALL rows to status: "paused"
2. Done. Both crons keep running but find nothing actionable. Zero project work happens.
3. Resume by setting rows back to "active" one at a time.
```

The crons never stop. The dispatch table controls what they do.

---

## Session Lock (LOCK.md)

The worker and manager crons share write access to ACTIVE-PROJECTS.md and project LONGRUNNERs.
LOCK.md prevents concurrent writes when both crons fire close together.

**Expiry:** A lock is stale if its `locked_at` timestamp is >20 minutes old.
Any cron session finding a stale lock clears it and proceeds normally.

**Normal operation:** The lock is acquired at STARTUP, held through T0–T8, and released
at T9 (BUNDLE:session_close). If a new cron fires while the lock is held by a valid
(non-stale) session: exit immediately with a LOW deferral note to NOTIFICATIONS.md.

**Cadence implication:** Do not run the worker cadence below 25 minutes. The 20-minute
stale threshold is designed for the 3-hour default cadence — at <25 minutes, a
legitimate in-progress pass could be incorrectly classified as stale. See FM-028 for the
full failure mode and detection signals.

---

## Observed Cadence Log

Update this table as you observe real pass durations:

| Date | Project | Avg Pass Duration | Cron Setting | Alignment |
|------|---------|------------------|--------------|-----------|
| 2026-04-02 | [project-slug] | unknown — first run | 3h (starting cadence) | TBD |
| — | — | — | — | — |

After 3–5 cycles, adjust cron cadence based on observed duration. Document it here.

---

## How to Change Cron Cadence ({OWNER} only — agents cannot do this)

The agent cannot modify its own cron schedule (SOUL.md Hard Line). {OWNER} makes cadence
changes via CLI. Two commands — delete the old cron, create the new one:

```bash
# Step 1 — Find the cron ID
openclaw cron list
# Note the ID next to "nightclaw-worker-trigger" or "nightclaw-manager-trigger"

# Step 2 — Delete and recreate with new cadence
# Example: tightening worker from 3h to 1h after observing short passes

openclaw cron delete [worker-cron-id]

openclaw cron add \
  --name "nightclaw-worker-trigger" \
  --every 1h \
  --model anthropic/claude-haiku-3-5 \
  --session "session:nightclaw-worker" \
  --message "HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-WORKER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps." \
  --light-context \
  --no-deliver
# Note: --tz is NOT valid with --every. Remove it.
# Note: --every uses human-readable strings as of 2026.4.1 (3h, 1h, 1d). Milliseconds no longer accepted.
# Note: --model is REQUIRED — without it, the cron uses the platform default model, which may be expensive.
# Note: --no-deliver required for all custom session crons to avoid channel resolution errors.
```

**Before tightening cadence:** confirm the average pass duration from `memory/YYYY-MM-DD.md`.
If passes average 12 minutes, a 1-hour cadence works. If passes average 25 minutes,
keep at 3 hours — overlapping crons corrupt LONGRUNNER state.

**Cadence decision rule:** cron interval ≥ (average pass duration × 1.5). Buffer matters.

**Rate limit guardrail:** At 1h cadence = ~24 passes/day. Community reports
show the $20 OAuth plan exhausting in 2-5 autonomous tasks. The default 3h cadence
(~8 passes/day) is calibrated for the $20/month budget. Tighten carefully.
Monitor `openclaw gateway status` for 429s in the first hour after tightening.

**Document every cadence change** in the Observed Cadence Log table above.
