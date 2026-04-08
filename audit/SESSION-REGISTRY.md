# SESSION-REGISTRY.md
<!-- APPEND-ONLY. One entry per cron run. Workers append at Step 9; managers append at Step 9. -->
<!-- Purpose: reconstruct exactly what any session did, cross-reference with AUDIT-LOG.md. -->
<!-- Entry written by the session itself at its own conclusion (Step 9 for workers, Step 9 for managers). -->

---

## v19 Entry Format (current — for run_id counting)
<!-- run_id = RUN-YYYYMMDD-NNN. Count lines starting with ## RUN- dated today to determine N. -->
<!-- Example: ## RUN-20260404-001 | 2026-04-04T... | worker -->
<!-- Old v16 format entries (## run:nightclaw-init etc.) do NOT count toward today's sequence. -->

TASK:RUN-[YYYYMMDD]-[NNN].T9 | TYPE:SESSION_CLOSE | SESSION:[worker|manager] | RESULT:SUCCESS | TOKENS:in=[n],out=[n] | PROJECTS:[slugs] | OUTCOME:[one sentence]

---

## v16 Legacy Format (historical entries only — do not use for new entries)

## Entry Format

```
## [run-id] | [ISO8601Z] | [session-name]
- **Model:** [model name]
- **Tokens:** input=[n] output=[n] (session total)
- **Projects touched:** [slug list or "none — idle cycle"]
- **Actions:** [N EXEC, N FILE_WRITE, N NOTIFICATION_APPEND, N PA_INVOCATION]
- **Quality rating:** [STRONG | ADEQUATE | WEAK | FAIL | N/A (manager pass)]
- **Authorization used:** [PA-xxx | none | manager-authority]
- **Integrity check:** [PASS | FAIL | SKIPPED-pre-v16]
- **Audit entries:** AUDIT-LOG.md lines [n]–[n]
- **Outcome:** [one sentence — what value was produced or why nothing was]
```

---

## Registry

<!-- Entries appended below. Most recent at bottom. -->

## run:nightclaw-init | {INSTALL_DATE}T00:00:00Z | nightclaw-bootstrap
- **Model:** nightclaw-init
- **Tokens:** input=0 output=0
- **Projects touched:** none — orchestration layer bootstrap
- **Actions:** 0 EXEC, 5 FILE_WRITE, 0 NOTIFICATION_APPEND, 0 PA_INVOCATION
- **Quality rating:** N/A
- **Authorization used:** {OWNER}-direct (install date: {INSTALL_DATE})
- **Integrity check:** SKIPPED-bootstrap (this run created the manifest)
- **Audit entries:** AUDIT-LOG.md genesis entry
- **Outcome:** NightClaw orchestration layer bootstrapped — audit/, INTEGRITY-MANIFEST.md, SESSION-REGISTRY.md, APPROVAL-CHAIN.md, CHANGE-LOG.md created.
