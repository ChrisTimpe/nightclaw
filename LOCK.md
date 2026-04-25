# LOCK.md — Session Lock
<!-- Prevents concurrent cron overlap between worker and manager sessions. -->
<!-- Read at STARTUP before T0. Write at STARTUP if released. Release at BUNDLE:session_close. -->
<!-- Expiry window: 20 minutes from locked_at. A lock older than 25 min is always stale (orphan guard). -->
<!-- STANDARD tier. Not in INTEGRITY-MANIFEST. -->

---

```yaml
status: released
holder: —
run_id: —
locked_at: —
expires_at: —
consecutive_pass_failures: 0
```

---

## Lock Protocol (summary — full protocol in CRON-WORKER-PROMPT.md and CRON-MANAGER-PROMPT.md STARTUP)

**STARTUP (before T0) — both worker and manager:**
1. Read this file.
2. Run stale check (BOTH conditions — either triggers stale treatment):
   - CONDITION A: `expires_at` is in the past (time-expired)
   - CONDITION B: `locked_at` is more than 25 minutes ago (orphan guard — catches crashes where
     expires_at was never written correctly, or manual test sessions left mid-run)
   Run: `python3 -c "from datetime import datetime,timezone; e='[expires_at]'; la='[locked_at]'; now=datetime.now(timezone.utc); print('stale' if e=='—' or la=='—' or datetime.fromisoformat(e.replace('Z','+00:00')) < now or (now - datetime.fromisoformat(la.replace('Z','+00:00'))).total_seconds() > 1500 else 'active')"`
3. IF status=locked AND stale=active:
   - Output: `[LOCK] Active lock detected. Holder: [holder]. Expires: [expires_at]. This pass is deferred.`
   - Output: `[LOCK] If testing manually, reset LOCK.md status to released before retrying.`
   - Log conflict to AUDIT-LOG. Append LOW notification. Exit cleanly. Do NOT proceed.
4. IF status=released OR stale=stale:
   - IF status=locked (stale): log `TYPE:LOCK_STALE | CLEARED_BY:[run_id] | STALE_HOLDER:[holder]`
   - Overwrite this file:
     status: locked
     holder: [session name — session:nightclaw-worker OR session:nightclaw-manager OR manual]
     run_id: [this run_id]
     locked_at: [ISO8601Z now]
     expires_at: [ISO8601Z now + 20 minutes]
     consecutive_pass_failures: [prior value if status was locked-stale, else 0]
   - Proceed to T0.

**BUNDLE:session_close (T9):**
- Overwrite this file:
  status: released
  holder: —
  run_id: —
  locked_at: —
  expires_at: —
  consecutive_pass_failures: 0
- This is the final write of every session. MANDATORY — never skip.

**Stale lock (either condition above):**
- Log to AUDIT-LOG: `TYPE:LOCK_STALE | CLEARED_BY:[run_id] | STALE_HOLDER:[holder]`
- Increment consecutive_pass_failures before overwriting (tracks crash loops)
- If consecutive_pass_failures >= 3: append MEDIUM notification:
  "Worker/manager has failed to complete 3+ consecutive passes. Check logs for crash pattern."
- Clear and proceed.

**Consecutive failure tracking:**
- consecutive_pass_failures increments each time a stale lock is cleared (indicates a crash)
- consecutive_pass_failures resets to 0 at T9 (successful pass)
- At 3+ failures: MEDIUM notification surfaced. Manager checks on next pass.
- At 5+ failures: HIGH notification. Likely persistent API error or broken environment.
