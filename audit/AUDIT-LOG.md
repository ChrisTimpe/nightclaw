# AUDIT-LOG.md
<!-- APPEND-ONLY. Never edit or delete entries. Hard Line in SOUL.md. -->
<!-- Written by: worker (T0,T4,T6,T9) and manager (T1,T8,T9). -->
<!-- Two formats exist: v16 legacy (## [ISO8601Z] blocks) and v19 compact (TASK: pipe-delimited). -->
<!-- v19 compact format is current. Both are valid. Never delete legacy entries. -->

---

## v19 Compact Entry Format (current)

```
TASK:[RUN-YYYYMMDD-NNN].[T-step] | TYPE:[ACTION] | RESULT:[PASS|FAIL|SUCCESS|BLOCKED] | [key=value pairs]
```

Examples:
```
TASK:RUN-20260404-001.T0 | TYPE:INTEGRITY_CHECK | RESULT:PASS | FILES:10
TASK:RUN-20260404-001.T4.1 | TYPE:EXEC | AUTH:PA-001 | RESULT:SUCCESS | CMD:python3 fetch_data.py
TASK:RUN-20260404-001.T6 | TYPE:BUNDLE | BUNDLE:longrunner_update | FILE:PROJECTS/my-project/LONGRUNNER.md | RESULT:SUCCESS
TASK:RUN-20260404-001.T9 | TYPE:SESSION_CLOSE | RESULT:SUCCESS | TOKENS:in=12400,out=890
```

## v16 Legacy Format (genesis entry only)
<!-- Do not use for new entries. Preserved for audit continuity. -->

---

## [GENESIS] | {INSTALL_DATE}T00:00:00Z | Session: nightclaw-init | Run: nightclaw-bootstrap
**Action:** FILE_WRITE
**Detail:** audit/AUDIT-LOG.md created — NightClaw orchestration layer bootstrap
**Authorization:** {OWNER}-direct (install date: {INSTALL_DATE})
**Result:** SUCCESS — append-only audit ledger initialized
**Artifacts:** audit/AUDIT-LOG.md
**Tokens:** input=0 output=0
**Model:** nightclaw-init
