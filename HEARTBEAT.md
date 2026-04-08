# HEARTBEAT.md

## Cron Trigger Handling — Check This First
<!-- Injected on EVERY main session AND every heartbeat run. Keep lean. -->

If the system event contains `WORKER_PASS_DUE`:
  Read `orchestration-os/CRON-WORKER-PROMPT.md` and execute the full worker pass. Stop after.

If the system event contains `MANAGER_PASS_DUE`:
  Read `orchestration-os/CRON-MANAGER-PROMPT.md` and execute the full manager pass. Stop after.

If this is a routine heartbeat: continue with checks below.

---

## Heartbeat Checks (lightweight — no heavy searches)

1. **NOTIFICATIONS.md** — Read it. If any entry is unresolved and unsurfaced: surface it to {OWNER}. Add `[SURFACED YYYY-MM-DD HH:MM]` inline. One notification per heartbeat max.

2. **ACTIVE-PROJECTS.md** — Any rows with Escalation Pending not `none` and not surfaced? Append to NOTIFICATIONS.md and surface.

3. **[knowledge-repo]/00-inbox/** — Any files? Note count to {OWNER}. Do not process inline.

4. **Cron health** — If Last Worker Pass in ACTIVE-PROJECTS.md is more than 2 hours old with active projects: note it. Check `openclaw cron status` if able.

If nothing needs attention: reply `HEARTBEAT_OK`

---

## Memory Consolidation
Trigger: 7+ days since last consolidation OR 5+ dated memory files since last consolidation.
If triggered: read memory/YYYY-MM-DD.md files → write consolidated summary to memory/YYYY-MM-DD.md (today's file) → append consolidation marker.
Never write to MEMORY.md — that is a protected bootstrap file. All memory writes go to dated files in memory/.
