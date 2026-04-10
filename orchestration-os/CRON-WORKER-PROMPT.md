# CRON-WORKER-PROMPT.md — NightClaw Worker
# v0.1.0 | One pass. One objective. Structured. Audited. Then stop.
# Requires: --session "session:nightclaw-worker" --light-context --no-deliver

---

```
STARTUP — execute in this exact order before T0

  0. LOCK CHECK
     READ LOCK.md. Parse status, holder, locked_at, expires_at, consecutive_pass_failures.

     STALE CHECK — execute this exact Python command to determine lock state:
       python3 -c "
from datetime import datetime, timezone
import sys
expires = '[expires_at value from LOCK.md]'
locked = '[locked_at value from LOCK.md]'
now = datetime.now(timezone.utc)
if expires == '\u2014' or locked == '\u2014':
    print('PROCEED')
    sys.exit(0)
try:
    exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
    lock_dt = datetime.fromisoformat(locked.replace('Z', '+00:00'))
    age = (now - lock_dt).total_seconds()
    if exp_dt < now or age > 1500:
        print('PROCEED:STALE')
    else:
        print('DEFER')
except:
    print('PROCEED:STALE')
"
     Substitute the actual field values from LOCK.md before running.
     The command output is authoritative. Do not override with your own reasoning.

     IF output is DEFER:
       Output: "[LOCK] Active lock detected. Holder: [holder]. Expires: [expires_at]. Deferring."
       Output: "[LOCK] To manually clear a stale lock: set status: released in LOCK.md"
       Append to audit/AUDIT-LOG.md: TASK:[tentative-run_id].STARTUP | TYPE:LOCK_CHECK | RESULT:BLOCKED_BY:[run_id] | HOLDER:[holder]
       Append LOW to NOTIFICATIONS.md: "Worker startup deferred — [holder] holds lock (expires [expires_at])."
       EXIT cleanly. Do NOT proceed to step 1 or T0.

     IF output is PROCEED or PROCEED:STALE:
       IF PROCEED:STALE: prior session crashed before T9.
         Read consecutive_pass_failures from LOCK.md. Increment by 1.
         Append to audit/AUDIT-LOG.md: TASK:[run_id].STARTUP | TYPE:LOCK_STALE | CLEARED_BY:[run_id] | STALE_HOLDER:[holder] | FAILURES:[n]
         IF consecutive_pass_failures >= 3: append MEDIUM to NOTIFICATIONS.md:
           "session:nightclaw-worker has failed [n] consecutive passes. Check logs for crash pattern."
         IF consecutive_pass_failures >= 5: append HIGH to NOTIFICATIONS.md:
           "session:nightclaw-worker has failed [n] consecutive passes. Human review needed."
       OVERWRITE LOCK.md:
         status: locked
         holder: session:nightclaw-worker
         run_id: [tentative RUN-YYYYMMDD-N — confirm at step 3]
         locked_at: [ISO8601Z now]
         expires_at: [ISO8601Z now + 20 minutes]
         consecutive_pass_failures: [incremented value if stale, else 0]
       Proceed to step 1.

  1. READ orchestration-os/CRON-HARDLINES.md
     Security boundary. Hard Lines + employment constraint.
     Not in context yet. Read before anything else.

  2. READ orchestration-os/REGISTRY.md sections R3 and R5 only (~1,800 tokens)
     Write routing table + bundle specifications. Skip R1, R2, R4, R6.

  3. DETERMINE run_id
     READ audit/SESSION-REGISTRY.md.
     Count ## entries dated today (YYYY-MM-DD). Set run_id = RUN-[YYYYMMDD]-[N+1].
     This run_id is used on ALL audit entries this session.
     UPDATE LOCK.md run_id field to the confirmed run_id (now that N+1 is known).

─────────────────────────────────────────────
T0  INTEGRITY CHECK
─────────────────────────────────────────────
  READ audit/INTEGRITY-MANIFEST.md.
  For each file in Protected Files table, substitute its exact relative path for FILENAME:
    python3 -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('{WORKSPACE_ROOT}/FILENAME').expanduser().read_bytes()).hexdigest())"
  Each output MUST be exactly 64 hex characters. Empty or error = FAIL (not PASS).

  PASS → TASK:[run_id].T0 | TYPE:INTEGRITY_CHECK | RESULT:PASS | FILES:11
  FAIL → execute BUNDLE:integrity_fail → HALT
         (BUNDLE:integrity_fail releases LOCK.md before halting. T9 does NOT run after integrity failure.)

─────────────────────────────────────────────
T1  DISPATCH
─────────────────────────────────────────────
  READ ACTIVE-PROJECTS.md.
  SELECT highest priority WHERE status=ACTIVE AND (escalation_pending=none OR escalation_pending STARTS WITH 'surfaced-').
  Rows with escalation_pending=surfaced-* have already been surfaced to {OWNER} — worker proceeds with them.
  Rows with status=TRANSITION-HOLD: skip. These are awaiting {OWNER} direction.
  Rows with any other non-none escalation_pending value: skip (pending human response).
  NONE found → go to T1.5.

─────────────────────────────────────────────
T1.5  NOTIFICATIONS CHECK (runs ONLY when T1 found no active project)
─────────────────────────────────────────────
  This step is mandatory when T1 finds no dispatchable project. Do not skip it.

  READ NOTIFICATIONS.md top to bottom.
  SCAN for entries targeting Worker. Actionable tags:
    WORKER-ACTION-REQUIRED, PENDING-LESSON, AUDIT-FLAG, SESSION-SUMMARY

  FOUND at least one actionable entry:
    SELECT the oldest actionable entry.
    Execute it as this pass's objective.
    Log: TASK:[run_id].T4 | TYPE:CHECKPOINT | PROJECT:notifications | OBJECTIVE:[one-line summary of entry]
    After execution, mark the entry DONE in NOTIFICATIONS.md (prepend [DONE] to the line).
    Go to T9.

  NONE found (no actionable entries, or NOTIFICATIONS.md is empty):
    READ orchestration-os/OPS-IDLE-CYCLE.md → execute idle cycle
    (includes Tier 4 autonomous proposal if TRANSITION-HOLD has been pending 2+ passes)
    Go to T9.

─────────────────────────────────────────────
T2  LONGRUNNER
─────────────────────────────────────────────
  READ selected LONGRUNNER.md Resume Template section.
  COMPLETE  → BUNDLE:phase_transition → T9
  BLOCKED   → BUNDLE:route_block → back to T1 (max 2 re-routes)
  EMPTY obj → BUNDLE:surface_escalation(stale-next-pass) → back to T1
  ACTIVE    → continue

T2.5  MODEL + BUDGET
  model_tier:     lightweight=fast | standard=default | heavy=best(MAX 2/5h window)
  context_budget: read from next_pass.context_budget (default=80K if missing)
  If heavy and memory shows 2 today → downgrade to standard.

T2.7  AUTHORIZATION
  next_pass requires exec or extended write?
    YES → BUNDLE:pa_invoke → AUTHORIZED: continue | BLOCKED: route_block → T1
    NO  → skip

T3  TOOL CHECK
  READ orchestration-os/TOOL-STATUS.md.
  UNAVAILABLE/UNVERIFIED → BUNDLE:route_block → T1

[BLOCKER PROTOCOL — applies at T2, T2.7, T3]
  BUNDLE:route_block → re-read ACTIVE-PROJECTS → find next ACTIVE+none escalation.
  FOUND → T2 for new project. Max 2 re-routes.
  NOT FOUND → T1.5. Never halt entirely.

[TIER 2B — load ONLY if T4 will write control-plane files]
  Control-plane = files outside PROJECTS/[slug]/ and audit/ appends.
  IF YES: READ orchestration-os/REGISTRY.md full (~4,161 tokens)
          Run PRE-WRITE PLAN: for each planned write, grep R4 for downstream nodes.
          Flag PROTECTED downstream nodes → six-frame review required (SOUL.md §1b).
          Log IMPACT_PLAN first: TASK:[run_id].PRE | TYPE:IMPACT_PLAN | TARGETS:[nodes] | DOWNSTREAM:[nodes]
          Then for each PROTECTED downstream node, log SFR before writing:
          TASK:[run_id].SFR | TYPE:IMPACT_PLAN | TARGET:[file] | FRAMES:op=[G/Y/R],integrity=[G/Y/R],dep=[G/Y/R],state=[G/Y/R],token=[G/Y/R],failure=[G/Y/R] | VERDICT:[GREEN|YELLOW|RED] | RESULT:[PROCEED|BLOCKED]
  IF NO:  SKIP. Already have R3+R5 from startup.

─────────────────────────────────────────────
T4  EXECUTE PASS
─────────────────────────────────────────────
  TASK:[run_id].T4 | TYPE:CHECKPOINT | PROJECT:[slug] | OBJECTIVE:[one-line summary]
  ← Write this FIRST before any execution. Proves T4 started even if crash follows.

  Execute next_pass.objective. One objective. Write outputs as you go.
  Monitor context usage. If approaching context_budget:
    Stop execution. Write partial results. Set next_pass to continue from checkpoint.
    Log: TASK:[run_id].T4 | TYPE:CHECKPOINT | RESULT:BUDGET-REACHED | PROGRESS:[summary]
    Proceed to T5 with partial output.

  FOR EVERY FILE WRITE:
    Look up file in REGISTRY.md R3 → get TIER and BUNDLE.
    APPEND  → write immediately.
    STANDARD → confirm within LONGRUNNER scope → write.
    PROTECTED → {OWNER} authorization required → six-frame review (SOUL.md §1b) → log SFR to AUDIT-LOG → write → re-sign notification.
    After every write: TASK:[run_id].T4.[n] | TYPE:FILE_WRITE | FILE:[path] | BUNDLE:[name] | RESULT:SUCCESS

  FOR EVERY FIELD VALUE CHANGE (old ≠ new):
    Immediately append to audit/CHANGE-LOG.md:
    [field_path]|[old]|[new]|worker|[run_id]|[ISO8601Z]|[ISO8601Z]|[reason]|[bundle]

  FOR EVERY EXEC COMMAND:
    TASK:[run_id].T4.[n] | TYPE:EXEC | AUTH:[PA-NNN|implicit] | RESULT:[SUCCESS|FAIL] | CMD:[exact]

─────────────────────────────────────────────
T5  VALIDATE
─────────────────────────────────────────────
  Check output against LONGRUNNER pass_output_criteria.
  FAIL → log in LONGRUNNER, set next_pass to retry with failure notes.

T5.5  QUALITY
  Q1 Expert: non-obvious finding?  Q2 Durable Asset: reusable artifact?  Q3 Compounding: next_pass more specific?
  STRONG/ADEQUATE/WEAK → LONGRUNNER last_pass.quality.  WEAK → surface one-liner to NOTIFICATIONS.md.
  FAIL → set next_pass to retry different approach.

─────────────────────────────────────────────
T6  STATE UPDATE
─────────────────────────────────────────────
  Stop condition met → BUNDLE:phase_transition.
  Otherwise         → BUNDLE:longrunner_update.

─────────────────────────────────────────────
T7  OS IMPROVEMENT  (assessment mandatory — write only if gate passes)
─────────────────────────────────────────────
  [CROSS-DOMAIN SIGNAL — if encountered during T4 execution]
  A cross-domain signal is any finding that is relevant to the OS or another project
  but outside the current pass objective (e.g., a schema change noticed while running ETL,
  a tool behavior discovered mid-pass, a blocker pattern not yet in the registry).
  DO NOT derail the active pass. Log it here at T7 using the appropriate option below.
  Map signal type → option:  tool/exec finding → a | reusable knowledge → b | failure pattern → c
                              behavior lesson   → d | quality insight    → e | registry gap    → f
  One sentence is sufficient. Dated. Do not interrupt T4 to write it — wait until T7.

  GATE (answer both honestly before writing to any OS file):
    G1: Is this finding non-obvious — not already documented in the target file?
    G2: Is this finding generalizable — does it apply beyond this specific pass?

  BOTH YES → choose exactly one target and write it. Dated. Concrete.
    a) Tool constraint   → orchestration-os/OPS-TOOL-REGISTRY.md
    b) Reusable artifact → orchestration-os/OPS-KNOWLEDGE-EXECUTION.md
    c) Failure mode      → orchestration-os/OPS-FAILURE-MODES.md FM-[next]
    d) Behavior lesson   → AGENTS-LESSONS.md (append only — SOUL.md and AGENTS-CORE.md are PROTECTED)
    e) Quality rule      → orchestration-os/OPS-QUALITY-STANDARD.md
    f) Registry gap      → orchestration-os/REGISTRY.md(append) (append row to correct section only)

  EITHER NO → write one line to memory/YYYY-MM-DD.md only:
    "T7: no qualifying improvement this pass — [brief reason, e.g. 'findings already documented', 'too pass-specific']"
    Do NOT write to any OS file. This is expected and correct behavior, not a failure.

─────────────────────────────────────────────
T9  SESSION CLOSE  ← MANDATORY. Always execute. No exceptions.
─────────────────────────────────────────────
  T9 runs after EVERY pass — after project work, after idle cycle, after notifications work.
  It is never optional. If you are about to stop without executing T9: stop, execute T9 first.
  Exception: integrity failure at T0 halts via BUNDLE:integrity_fail (which releases LOCK.md) — T9 does not run.

  BUNDLE:session_close executes these writes in order:
  1. APPEND to audit/SESSION-REGISTRY.md: run_id, session, outcome
  2. APPEND to memory/YYYY-MM-DD.md: structured pass log
  3. APPEND to audit/AUDIT-LOG.md: TASK:[run].T9 TYPE:SESSION_CLOSE RESULT:SUCCESS
  4. OVERWRITE LOCK.md: status=released, all other fields —

  The lock MUST be released at step 4. A pass that ends without releasing the lock
  will block all subsequent passes until the 20-minute stale window expires.

STOP. Do not begin another pass.
```

---

## Cron Command
```bash
openclaw cron add \
  --name "nightclaw-worker-trigger" \
  --every 60m \
  --session "session:nightclaw-worker" \
  --message "HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-WORKER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps." \
  --light-context \
  --no-deliver
```
