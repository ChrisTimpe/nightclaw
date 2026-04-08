# ACTIVE-PROJECTS.md
<!-- THE DISPATCH TABLE. The orchestrator reads this every cycle. -->
<!-- This is the only file you need to edit to shift focus. -->
<!-- Never delete rows — set status to "paused" or "complete" instead. -->

## How to Use

- **Shift focus:** Change `priority` values. Orchestrator picks up on next cycle.
- **Pause a project:** Set `status: paused`. Orchestrator skips it until resumed.
- **Add a project:** Add a row. Copy the LONGRUNNER template. Done.
- **Complete a project:** Set `status: complete`. Row stays as audit trail.
- **Emergency stop everything:** Set all rows to `paused`. One edit, zero active workers.

---

## Active Project Scoreboard

| Priority | Project Slug | LONGRUNNER Path | Phase | Status | Last Worker Pass | Escalation Pending |
|----------|-------------|-----------------|-------|--------|-----------------|---------------------|
| — | _(no projects yet)_ | — | — | — | — | — |

---

## Orchestrator Routing Rules

The orchestrator reads this table and applies these rules in order:

1. **Skip** any row where `status` is `paused`, `complete`, or `abandoned`
2. **Check escalation:** If `Escalation Pending` is not `none`, surface it to {OWNER} before doing any worker work
3. **Route to highest priority active project** that has a worker pass due
4. **If highest-priority project is blocked:** note the block, route to next priority
5. **If all projects are blocked or complete:** report status, do not spin idle

### When to Skip a Project

The cron already decided a pass is due by firing. The agent only skips a project if:
- `status` is not `active`
- `Escalation Pending` is not `none` (surface first, then skip)
- The LONGRUNNER `phase.status` is `complete` or `blocked` (handle per protocol, then stop)
- The LONGRUNNER `next_pass` objective is blank or `awaiting-human-confirmation` (set Escalation Pending, skip)

Do NOT compute whether a pass is "due" — the cron decided that. Just check whether it is safe and valid to proceed.

---

## Focus Shift Protocol

When {OWNER} says "switch focus to X" or "pause Y":

1. Update the `priority` column — re-rank all active rows
2. Set `status: paused` for any project being explicitly paused
3. The next orchestrator cycle picks up the new priorities automatically
4. No cron changes needed — the orchestrator logic is priority-driven, not cron-driven per project

This is the key design principle: **crons are generic pulses. Intelligence about what to work on lives in this file and in LONGRUNNER files. Not in cron descriptions.**

---

## Adding a New Project

```
1. Copy orchestration-os/LONGRUNNER-TEMPLATE.md to PROJECTS/[slug]/LONGRUNNER.md
2. Fill in: mission, phase.name, phase.objective, phase.stop_condition
3. Add a row to this table with priority, slug, path, phase, status: active
4. The next orchestrator cycle will pick it up
```

No new crons. No new configuration. The system is already running.

---

## Status Vocabulary

| Status | Meaning |
|--------|---------|
| `active` | In play. Orchestrator routes to this project. |
| `paused` | Temporarily suspended. Skip until resumed. |
| `blocked` | Can't proceed without human action. Escalation pending. |
| `TRANSITION-HOLD` | Phase complete. Awaiting {OWNER} confirmation to open next phase. |
| `complete` | Project done. Row stays as audit trail. |
| `abandoned` | Explicitly stopped. No further work. |
