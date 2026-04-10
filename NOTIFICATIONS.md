# NOTIFICATIONS.md
<!-- APPEND-ONLY. Escalation surface for both sessions. Agents append; {OWNER} and Worker read. -->
<!-- Worker reads this file at T1.5 (idle dispatch) and actions entries tagged for it. -->
<!-- Actionable worker tags: WORKER-ACTION-REQUIRED, PENDING-LESSON, AUDIT-FLAG, SESSION-SUMMARY -->
<!-- Archival: {OWNER} manually moves resolved entries to NOTIFICATIONS-ARCHIVE.md as needed. -->
<!-- NOTIFICATIONS-ARCHIVE.md does not ship with NightClaw. Create it when you first archive entries. -->
<!-- There is no automated archival. Review and prune this file at your own cadence. -->

---

## Entry Formats

### Alert Entry
```
[YYYY-MM-DD HH:MM] | Priority: CRITICAL | HIGH | INFO | WARNING | Project: [slug] | Status: [status]
Context: [one-line description]
Action required: [what {OWNER} needs to do, or NONE]
```

### Phase Transition Entry (HIGH priority)
<!-- Used when a project completes a phase and needs owner confirmation to proceed. -->
```
[YYYY-MM-DD HH:MM] | Priority: HIGH | Project: [slug] | Status: TRANSITION-HOLD
Context: [phase] phase complete. Artifact: [path to output file]
Action required: Tell the agent to 'approve', 'pause', or 'pivot' this project.
  approve — advance to [successor phase] and continue autonomous work
  pause   — hold the project until you reactivate it manually
  pivot   — agent will ask for new direction before making changes
```

### Proposed Enhancement Entry
<!-- Use this format when the agent has identified an enhancement, schema change, new approach, -->
<!-- or improvement that warrants {OWNER} review. This is non-blocking — the agent continues -->
<!-- working on everything else. {OWNER} reviews at their next check-in. -->
```
[YYYY-MM-DD HH:MM] | Priority: PROPOSAL | Project: [slug] | Status: PENDING-REVIEW
Proposal: [one-line description of what was identified]
Proposed path: [what the agent would do if approved — specific, not vague]
Estimated cost: [STANDARD (routine model) | ENHANCED (model upgrade warranted) | UNKNOWN]
Blocking current work: YES | NO
If approved: [exact action that will be taken on next pass]
If declined: [fallback — what happens instead]
Model note: [if ENHANCED — why a more capable model is warranted for this specific task]
```

### Escalation Pending Entry
<!-- Use when blocked on something that cannot be resolved autonomously and is not a proposal. -->
```
[YYYY-MM-DD HH:MM] | Priority: ESCALATION | Project: [slug] | Status: ESCALATION-PENDING
Blocker: [what is blocking progress]
Attempted: [what was tried]
Needs: [specific question or decision required from {OWNER}]
```

---

## Current Alerts

[{INSTALL_DATE}] | Priority: INFO | Project: orchestration | Status: CLEAN
Context: NightClaw v0.1.0 installed successfully.
Next steps (in order):
  1. Configure SOUL.md §Domain Anchor with your focus area
     Then: bash scripts/resign.sh SOUL.md  (SOUL.md is protected — editing it without resigning causes T0 HALT)
  2. Update USER.md with your name, timezone, and any domain restrictions
     Then: bash scripts/resign.sh USER.md  (same reason)
  3. Run: bash scripts/verify-integrity.sh — must show 11 passed, 0 failed before starting crons
  4. Run: bash scripts/validate.sh — must show 0 failed (pass count varies by environment; warnings are non-blocking)
  5. Create two crons per DEPLOY.md §Step 5
  6. Before first overnight: activate PA-001 and PA-002 in OPS-PREAPPROVAL.md,
     then: bash scripts/resign.sh orchestration-os/OPS-PREAPPROVAL.md
  7. Start crons and open a main session — agent will brief you
What happens next (no action required):
  - On first idle cycle, the worker reads your Domain Anchor and proposes a first project
  - A MEDIUM notification will appear here with the draft and a one-word approval path
  - Say "approve" in the main session to begin, or describe what you want instead
Action required: NONE — system will propose work autonomously based on your Domain Anchor

---

## Append new entries below this line.
