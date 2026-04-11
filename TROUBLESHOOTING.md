# TROUBLESHOOTING.md
<!-- Common issues, diagnostics, and recovery procedures for NightClaw operators. -->

---

## Quick Diagnostics

```bash
# Check workspace health
cd ~/.openclaw/workspace && bash scripts/validate.sh

# Check lock state
cat LOCK.md

# Check what the crons are doing
openclaw cron list

# Check recent pass history
tail -20 audit/SESSION-REGISTRY.md

# Check for escalations
cat NOTIFICATIONS.md | grep -E "CRITICAL|HIGH|MEDIUM"

# Check recent memory log
cat memory/$(date +%Y-%m-%d).md
```

---

## Issue: Worker/Manager pass deferred — "lock held"

**Symptom:** Cron run shows "startup deferred — lock held by session X."

**Cause:** A previous pass acquired the lock and either:
- Is still running (legitimate active lock)
- Crashed before T9 (stale lock)

**Diagnosis:**
```bash
cat ~/.openclaw/workspace/LOCK.md
```

Check `expires_at`. If it is in the past, the lock is stale.

**Recovery:**

Run the following command to reset LOCK.md to its released state:

```bash
cat > ~/.openclaw/workspace/LOCK.md << 'ENDOFFILE'
# LOCK.md — Session Lock
<!-- Prevents concurrent cron overlap between worker and manager sessions. -->
<!-- Read at STARTUP before T0. Write at STARTUP if released. Release at BUNDLE:session_close. -->
<!-- Expiry window: 20 minutes from locked_at. A lock older than 25 min is always stale (orphan guard). -->
<!-- STANDARD tier. Not in INTEGRITY-MANIFEST. -->

---

status: released
holder: —
run_id: —
locked_at: —
expires_at: —
consecutive_pass_failures: 0
ENDOFFILE
```

**Note:** The system auto-clears stale locks (locks older than 20 minutes or 25+ minutes old regardless of expires_at) on the next scheduled pass. Manual clearing is only needed if you want to run immediately rather than wait.

---

## Issue: Passes keep failing — "consecutive_pass_failures" rising

**Symptom:** NOTIFICATIONS.md shows MEDIUM or HIGH alert about consecutive pass failures. `consecutive_pass_failures` in LOCK.md is 3 or higher.

**Diagnosis:**
```bash
# Check recent audit log for failure pattern
tail -30 ~/.openclaw/workspace/audit/AUDIT-LOG.md

# Check OpenClaw logs for model errors
tail -100 /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep -i "error\|fail\|rate_limit"
```

**Common causes:**
- Model rate limit (Gemini RPM cap) → wait 60 seconds, or switch model
- Model quota exhausted → add billing or switch provider
- API key invalid/expired → `openclaw models status` to check auth
- Workspace file corruption → run `bash scripts/validate.sh`

**Recovery after fixing root cause:**
```bash
# Reset the failure counter
sed -i 's/consecutive_pass_failures: [0-9]*/consecutive_pass_failures: 0/' \
  ~/.openclaw/workspace/LOCK.md
```

---

## Issue: Integrity check fails at first cron (T0 HALT)

**Symptom:** Worker halts on the very first cron pass with a hash mismatch. Nothing runs.

**Most common cause:** You edited a protected file during setup but did not re-sign it. The three files most commonly edited during setup are all protected:
- `SOUL.md` — required edit for Domain Anchor
- `USER.md` — required edit for name, timezone, domain restrictions
- `orchestration-os/OPS-PREAPPROVAL.md` — required edit to activate PA-001 and PA-002

**Recovery — find and re-sign whichever file you edited:**
```bash
cd ~/.openclaw/workspace

# Check which file has a stale hash
bash scripts/verify-integrity.sh

# Re-sign each file that shows FAIL
bash scripts/resign.sh SOUL.md
bash scripts/resign.sh USER.md
bash scripts/resign.sh orchestration-os/OPS-PREAPPROVAL.md

# Confirm all pass before starting crons
bash scripts/verify-integrity.sh
```

## Issue: Integrity check fails after upgrade

**Symptom:** Worker halts at T0 with "CRITICAL — hash mismatch."

**Cause:** Protected files were updated but manifest hashes were not updated.

**Recovery:**
```bash
cd ~/.openclaw/workspace

# Check which file has a stale hash
bash scripts/verify-integrity.sh

# Re-sign each mismatched file
bash scripts/resign.sh orchestration-os/CRON-WORKER-PROMPT.md
bash scripts/resign.sh orchestration-os/CRON-MANAGER-PROMPT.md
# etc.

# Verify
bash scripts/verify-integrity.sh
```

---

## Verifying a Clean Setup — Smoke Test

Before starting crons for the first time, run the smoke test to confirm the full setup
flow was completed correctly:

```bash
bash scripts/smoke-test.sh /path/to/nightclaw-v0.1.0-release-FINAL.zip
```

The smoke test simulates a new user's complete setup in an isolated temp directory —
extract, install, Domain Anchor edit + resign, USER.md edit + resign, PA activation + resign,
validate.sh, new-project creation, and T0 hash simulation. All checks must pass before
starting crons. If any check fails, the output names exactly which step failed and why.

---

## Safe Manual Testing Procedure

When testing NightClaw manually (crons disabled, force-running via `openclaw cron run`):

**Before each manual run:**
1. Check the lock is released:
   ```bash
   cat ~/.openclaw/workspace/LOCK.md | grep "^status"
   # Should show: status: released
   ```
2. If locked, check if stale (expires_at in the past) and clear if so.
3. Do not trigger a second run while the first is active.

**During a manual run:**
4. Watch the session in OpenClaw control UI.
5. Wait for the pass to complete (T9 must run — look for "Session closed" or "lock released" in output).

**After a manual run:**
5. Verify lock was released:
   ```bash
   cat ~/.openclaw/workspace/LOCK.md | grep "^status"
   # Should show: status: released
   ```
6. If the session crashed before T9, the lock will still show `status: locked`. Clear it manually (see above) before running again.

**Warning:** Do not trigger multiple manual runs in rapid succession. Each run acquires a 20-minute lock. If the first run crashes, the lock stays held for up to 20 minutes. Triggering a second run immediately will show "lock held" and exit without doing any work.

---

## Issue: Worker ran but no output in PROJECTS/ or memory/

**Symptom:** Cron shows `ok`, but no new files in project outputs and no memory entry.

**Possible causes:**
1. **All projects blocked/idle** — check ACTIVE-PROJECTS.md. If nightclaw-ecosystem has `escalation_pending` that is not `none`, the worker goes to idle cycle, not project work.
2. **Idle cycle Tier 4 not firing** — check that at least one of:
   - No active projects (blocked/complete/paused all count)
   - A project in TRANSITION-HOLD
   ...is true, and no `LONGRUNNER-DRAFT.md` already exists in `PROJECTS/`.
3. **Rate limit killed the pass mid-idle** — check OpenClaw logs for `rate_limit` errors.

**Diagnosis:**
```bash
cat ~/.openclaw/workspace/ACTIVE-PROJECTS.md
ls ~/.openclaw/workspace/PROJECTS/*/LONGRUNNER-DRAFT.md 2>/dev/null
tail -5 ~/.openclaw/workspace/memory/$(date +%Y-%m-%d).md
```

---

## Issue: Cron timing — manager and worker firing simultaneously

**This is expected behavior** when the LCM cycle aligns them (every 24 hours with default 3h worker / 24h manager settings). The lock protocol handles it: the first session to fire acquires the lock, the second defers cleanly and runs on its next scheduled cycle.

No action needed. A 1-cycle deferral (3h for worker, 24h for manager) is the designed outcome.

---

## nightclaw-admin CLI

The `nightclaw-admin` CLI handles all routine management without spending tokens. Run from your workspace root:

```bash
bash scripts/nightclaw-admin.sh --help    # show all commands
bash scripts/nightclaw-admin.sh status    # current state
bash scripts/nightclaw-admin.sh alerts    # unresolved notifications
```

**Common issues:**

- **"Cannot find NightClaw workspace"** — Run from your workspace root (`~/.openclaw/workspace/`) or set `NIGHTCLAW_ROOT` environment variable.
- **arm/disarm fails to re-sign** — Ensure `scripts/resign.sh` exists and is executable. Run `chmod +x scripts/resign.sh`.
- **approve says "No draft found"** — The draft must be at `PROJECTS/<slug>/LONGRUNNER-DRAFT.md`. Check the exact slug with `ls PROJECTS/`.
- **Status shows no projects but ACTIVE-PROJECTS.md has rows** — The status command reads only the "Active Project Scoreboard" table. Rows must have a valid LONGRUNNER path in column 3.

All admin commands log to `audit/AUDIT-LOG.md` and `audit/CHANGE-LOG.md` in the same format the cron sessions use.

---

## Emergency Stop

To halt all autonomous work immediately:

```bash
# Pause all projects at once
for slug in $(grep -oP '(?<=\| )[a-z0-9-]+(?= \| PROJECTS/)' ACTIVE-PROJECTS.md); do
  bash scripts/nightclaw-admin.sh pause "$slug"
done
```

Or edit directly:
```bash
nano ~/.openclaw/workspace/ACTIVE-PROJECTS.md
# Set all project rows to: status: paused
```

The next cron pass reads ACTIVE-PROJECTS.md at T1 and finds nothing actionable. All work stops at the next cycle boundary (within 3 hours at most).

To resume: `bash scripts/nightclaw-admin.sh unpause <slug>` or change status back to `active`.
