# WORKING.md — Session Entry Point
<!-- Read on first wake of a new main session, before waiting for user input. -->
<!-- This is the agent's standing order. No need to type anything — just wake up and orient. -->

You just woke up. Do this before waiting for {OWNER} to say anything:

1. Read `ACTIVE-PROJECTS.md` — one scan, ~30 seconds.
2. Check `NOTIFICATIONS.md` for any unresolved, unsurfaced items. If found: surface immediately.
3. Report status in one compact message:

```
Good [morning/afternoon/evening].

Active: [project slug] — [phase] — [next pass objective in one sentence]
[repeat for each active project, max 3 lines total]

Notifications: [none | N items — brief description]
Last worker pass: [date from ACTIVE-PROJECTS.md]
```

Then wait. Do not start working on anything until {OWNER} responds or directs.

**If all projects are paused or in transition-hold:**
Report that clearly, then ask: "Anything specific you want to work on, or should I run an idle cycle?"

**If NOTIFICATIONS.md has a HIGH entry about a phase transition:**
Surface it immediately in the briefing. The action required is simple:
- If {OWNER} says **"approve"** or **"continue"**: update `ACTIVE-PROJECTS.md` — change the project status from `TRANSITION-HOLD` to `active`, update the phase to the successor phase name, and clear the escalation field to `none`. Then update the LONGRUNNER `## Current Phase` block to reflect the new phase.
- If {OWNER} says **"stop"** or **"pause"**: update `ACTIVE-PROJECTS.md` — change status to `paused`. Worker will skip it until manually reactivated.
- If {OWNER} says **"pivot"**: ask for the new direction before making any changes.

Do not proceed with the transition autonomously. Wait for explicit confirmation.

**If NOTIFICATIONS.md has a MEDIUM entry for a LONGRUNNER-DRAFT (project proposal):**
Surface it immediately. Tell the owner what the proposed project is and what the first pass will do.
- If owner says **"approve [slug]"** or just **"approve"**: rename `PROJECTS/[slug]/LONGRUNNER-DRAFT.md` to `PROJECTS/[slug]/LONGRUNNER.md`, add a row to `ACTIVE-PROJECTS.md` (status: active, phase: exploration, escalation: none), mark the notification resolved. Worker picks it up on next pass.
- If owner says **"decline"**: delete the draft file, mark notification resolved, ask what to work on instead.
- If owner describes something new: create the project using `bash scripts/new-project.sh [slug]` logic inline, then brief on first pass.

**If this is the very first session (no ACTIVE-PROJECTS.md rows have any pass history):**
Check whether a LONGRUNNER-DRAFT exists in any PROJECTS/ subdirectory.
- If a draft exists: surface it as above.
- If no draft exists yet: say:
```
System is ready. No active projects running yet.

I'll propose a first project based on your Domain Anchor on the next idle cycle — usually within the hour.
Or tell me what you want to work on and I'll set it up now.
```

---

Keep this message under 6 lines. No filler. No preamble. Just the briefing.
