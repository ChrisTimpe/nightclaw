# CRON-WORKER-PROMPT.md — NightClaw Worker
# v0.2.2 | One pass. One objective. Structured. Audited. Then stop.
# Requires: --session isolated --light-context --no-deliver

---

```
STARTUP — execute in this exact order before T0

  0. LOCK CHECK
     Execute: python3 scripts/check-lock.py session:nightclaw-worker
     The command output is authoritative. Do not override with your own reasoning.

     Output format: PROCEED, PROCEED:STALE_HOLDER=X:STALE_RUN=Y:FAILURES=N, or DEFER:holder=X:run_id=Y:expires=Z
     Parse the colon-delimited fields from the output. Do not read LOCK.md yourself.

     IF output starts with DEFER:
       Parse holder, run_id, expires from the output.
       Output: "[LOCK] Active lock detected. Holder: [holder]. Expires: [expires]. Deferring."
       Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[tentative-run_id].STARTUP | TYPE:LOCK_CHECK | RESULT:BLOCKED_BY:[run_id] | HOLDER:[holder]
       Execute: python3 scripts/nightclaw-ops.py append NOTIFICATIONS.md [ISO8601Z now] | Priority: LOW | Project: system | Status: WORKER-DEFERRED \nWorker startup deferred — [holder] holds lock (expires [expires]).
       EXIT cleanly. Do NOT proceed to step 1 or T0.

     IF output starts with PROCEED:
       IF output contains STALE_HOLDER: prior session crashed before T9.
         Parse STALE_HOLDER, STALE_RUN, FAILURES from the output.
         Set consecutive_pass_failures = FAILURES + 1.
         Execute: python3 scripts/nightclaw-ops.py crash-context [STALE_RUN]
         Parse the crash context output. Note PROJECT, LAST_OBJECTIVE, RECOMMENDATION.
         Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].STARTUP | TYPE:LOCK_STALE | CLEARED_BY:[run_id] | STALE_HOLDER:[holder] | FAILURES:[n] | CRASHED_PROJECT:[project] | CRASHED_OBJECTIVE:[objective]
         IF RECOMMENDATION=ESCALATE:
           Execute: python3 scripts/nightclaw-ops.py append NOTIFICATIONS.md [ISO8601Z now] | Priority: HIGH | Project: [project] | Status: REPEAT-CRASH \nRepeat crash on [project]. Objective: [objective]. Human review needed.
         IF consecutive_pass_failures >= 3:
           Execute: python3 scripts/nightclaw-ops.py append NOTIFICATIONS.md [ISO8601Z now] | Priority: MEDIUM | Project: system | Status: CONSECUTIVE-FAILURES \nsession:nightclaw-worker has failed [n] consecutive passes. Check logs for crash pattern.
         IF consecutive_pass_failures >= 5:
           Execute: python3 scripts/nightclaw-ops.py append NOTIFICATIONS.md [ISO8601Z now] | Priority: HIGH | Project: system | Status: CONSECUTIVE-FAILURES \nsession:nightclaw-worker has failed [n] consecutive passes. Human review needed.
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
     Execute: python3 scripts/nightclaw-ops.py next-run-id
     The output is the run_id (e.g. RUN-20260410-003). Use it on ALL audit entries this session.
     UPDATE LOCK.md run_id field to the confirmed run_id.

─────────────────────────────────────────────
T0  INTEGRITY CHECK
─────────────────────────────────────────────
  Execute: python3 scripts/nightclaw-ops.py integrity-check
  Output is one line per file (PASS/FAIL/MISSING) plus a summary line.
  The script output is authoritative. Do not recompute hashes yourself.

  RESULT:PASS → Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T0 | TYPE:INTEGRITY_CHECK | RESULT:PASS | FILES:[count from script output]
  RESULT:FAIL → execute BUNDLE:integrity_fail → HALT
         (BUNDLE:integrity_fail releases LOCK.md before halting. T9 does NOT run after integrity failure.)

─────────────────────────────────────────────
T1  DISPATCH
─────────────────────────────────────────────
  Execute: python3 scripts/nightclaw-ops.py dispatch
  Output: DISPATCH:<slug> (proceed with that project) or IDLE (go to T1.5).
  The script applies all filtering rules (status, escalation_pending, priority sort).
  DISPATCH:<slug> → proceed to T2 with that slug.
  IDLE → go to T1.5.

─────────────────────────────────────────────
T1.5  NOTIFICATIONS CHECK + IDLE TRIAGE (runs ONLY when T1 found no active project)
─────────────────────────────────────────────
  This step is mandatory when T1 finds no dispatchable project. Do not skip it.

  STEP A: Check notifications.
  Execute: python3 scripts/nightclaw-ops.py scan-notifications
  Output: FOUND:line=<n>:priority=<p>:<summary> entries, or NONE.

  FOUND at least one:
    Take the first (oldest) FOUND entry. Note the line number.
    READ NOTIFICATIONS.md at that line to get the full entry content.
    Execute the entry's action as this pass's objective.
    Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T4 | TYPE:CHECKPOINT | PROJECT:notifications | OBJECTIVE:[one-line summary of entry]
    After execution, mark the entry DONE in NOTIFICATIONS.md (prepend [DONE] to the line).
    Go to T9.

  NONE:
    STEP B: Determine idle cycle tier.
    Execute: python3 scripts/nightclaw-ops.py idle-triage
    Output: IDLE:TIER=<tier>:ACTION=<action> or IDLE:NONE.

    The script checks all idle cycle tier prerequisites deterministically.
    Do NOT read OPS-IDLE-CYCLE.md to determine which tier to execute.
    The script output tells you exactly which tier has actionable work.

    IDLE:TIER=<tier>:ACTION=<action>:
      READ only the relevant tier section from OPS-IDLE-CYCLE.md for execution instructions.
      Execute that tier's action. Go to T9.
    IDLE:NONE:
      Write one line to memory/YYYY-MM-DD.md:
        "[IDLE CYCLE — timestamp] All tiers checked. No actionable work found. System current."
      Go to T9.

─────────────────────────────────────────────
T2  LONGRUNNER
─────────────────────────────────────────────
  Execute: python3 scripts/nightclaw-ops.py longrunner-extract <slug>
  The script extracts all routing-critical fields. Do not read the full LONGRUNNER file.
  Parse the key=value output lines.

  routing=COMPLETE  → BUNDLE:phase_transition → T9
  routing=BLOCKED   → BUNDLE:route_block → back to T1 (max 2 re-routes)
  routing=STALE_OBJECTIVE → BUNDLE:surface_escalation(stale-next-pass) → back to T1
  routing=ACTIVE    → continue

  READ the full LONGRUNNER.md ONLY at T4 if execution requires narrative context
  (e.g., pass_output_criteria, decision log, open questions). The extracted fields
  are sufficient for all routing decisions at T2, T2.5, T2.7, and T3.

T2.5  MODEL + BUDGET
  model_tier:     from longrunner-extract output: next_pass.model_tier
  context_budget: from longrunner-extract output: next_pass.context_budget (default=80K)
  If model_tier=heavy and memory shows 2 heavy passes today → downgrade to standard.

T2.7  AUTHORIZATION
  next_pass requires exec or extended write?
    YES → BUNDLE:pa_invoke → AUTHORIZED: continue | BLOCKED: route_block → T1
    NO  → skip

T3  TOOL CHECK
  READ orchestration-os/TOOL-STATUS.md.
  UNAVAILABLE/UNVERIFIED → BUNDLE:route_block → T1

[BLOCKER PROTOCOL — applies at T2, T2.7, T3]
  BUNDLE:route_block → Execute: python3 scripts/nightclaw-ops.py dispatch
  The script re-scans ACTIVE-PROJECTS.md for the next eligible project.
  DISPATCH:<slug> → T2 for new project. Max 2 re-routes.
  IDLE → T1.5. Never halt entirely.

[TIER 2B — load ONLY if T4 will write control-plane files]
  Control-plane = files outside PROJECTS/[slug]/ and audit/ appends.
  IF YES: READ orchestration-os/REGISTRY.md full (~4,161 tokens)
          Run PRE-WRITE PLAN: for each planned write, grep R4 for downstream nodes.
          Flag PROTECTED downstream nodes → six-frame review required (SOUL.md §1b).
          Log IMPACT_PLAN first: Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].PRE | TYPE:IMPACT_PLAN | TARGETS:[nodes] | DOWNSTREAM:[nodes]
          Then for each PROTECTED downstream node, log SFR before writing:
          Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].SFR | TYPE:IMPACT_PLAN | TARGET:[file] | FRAMES:op=[G/Y/R],integrity=[G/Y/R],dep=[G/Y/R],state=[G/Y/R],token=[G/Y/R],failure=[G/Y/R] | VERDICT:[GREEN|YELLOW|RED] | RESULT:[PROCEED|BLOCKED]
  IF NO:  SKIP. Already have R3+R5 from startup.

─────────────────────────────────────────────
T4  EXECUTE PASS
─────────────────────────────────────────────
  Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T4 | TYPE:CHECKPOINT | PROJECT:[slug] | OBJECTIVE:[one-line summary]
  ← Execute this FIRST before any execution. Proves T4 started even if crash follows.

  Execute next_pass.objective. One objective. Write outputs as you go.
  Monitor context usage. If approaching context_budget:
    Stop execution. Write partial results. Set next_pass to continue from checkpoint.
    Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T4 | TYPE:CHECKPOINT | RESULT:BUDGET-REACHED | PROGRESS:[summary]
    Proceed to T5 with partial output.

  FOR EVERY FILE WRITE:
    Look up file in REGISTRY.md R3 → get TIER and BUNDLE.
    APPEND  → write immediately.
    STANDARD → confirm within LONGRUNNER scope → write.
    PROTECTED → {OWNER} authorization required → six-frame review (SOUL.md §1b) → log SFR to AUDIT-LOG → write → re-sign notification.
    After every write: Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T4.[n] | TYPE:FILE_WRITE | FILE:[path] | BUNDLE:[name] | RESULT:SUCCESS

  FOR EVERY FIELD VALUE CHANGE (old ≠ new):
    Execute: python3 scripts/nightclaw-ops.py append audit/CHANGE-LOG.md [field_path]|[old]|[new]|worker|[run_id]|[ISO8601Z]|[ISO8601Z]|[reason]|[bundle]

  FOR EVERY EXEC COMMAND:
    Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T4.[n] | TYPE:EXEC | AUTH:[PA-NNN|implicit] | RESULT:[SUCCESS|FAIL] | CMD:[exact]

─────────────────────────────────────────────
T5  VALIDATE
─────────────────────────────────────────────
  Check output against LONGRUNNER pass_output_criteria.
  FAIL → log in LONGRUNNER, set next_pass to retry with failure notes.

T5.5  QUALITY
  Q1 Expert: non-obvious finding?  Q2 Durable Asset: reusable artifact?  Q3 Compounding: next_pass more specific?
  STRONG/ADEQUATE/WEAK → LONGRUNNER last_pass.quality.
  WEAK → Execute: python3 scripts/nightclaw-ops.py append NOTIFICATIONS.md [ISO8601Z now] | Priority: MEDIUM | Project: [slug] | Status: QUALITY-WEAK \n[one-liner quality note]
  FAIL → set next_pass to retry different approach.

─────────────────────────────────────────────
T6  STATE UPDATE
─────────────────────────────────────────────
  STOP CONDITION GATE — execute before any state write.
  Read phase.stop_condition from the longrunner-extract output.
  Decompose the stop condition into individual clauses.
  Evaluate each clause as TRUE or FALSE against the artifacts produced this pass
  and any artifacts already present from prior passes.

  Output the evaluation:
    STOP_EVAL: clause="[text]" result=TRUE|FALSE
    (one line per clause)

  IF ALL clauses are TRUE:
    Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T6 | TYPE:STOP_EVAL | RESULT:ALL_TRUE | CLAUSES:[count]
    → BUNDLE:phase_transition. Do not write next_pass.
    The stop condition is met. Quality improvements belong in the next phase, not this one.

  IF ANY clause is FALSE:
    Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T6 | TYPE:STOP_EVAL | RESULT:INCOMPLETE | FALSE_CLAUSES:[list]
    → BUNDLE:longrunner_update. Set next_pass.objective to address the FALSE clause(s).

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

  GATE:
    G1: Is this finding generalizable — does it apply beyond this specific pass?
         NO → skip to EITHER NO below.
    G2: Dedup check — is it already documented?
         Map your signal type to the target file (a–f below).
         Execute: python3 scripts/nightclaw-ops.py t7-dedup <target-file> <signal summary>
         Output: DUPLICATE:<entry_id>:<score>:<preview> or NOVEL
         DUPLICATE → skip to EITHER NO below.
         NOVEL → proceed to write.

  BOTH PASS → choose exactly one target and write it. Dated. Concrete.
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
  1. Execute: python3 scripts/nightclaw-ops.py append audit/SESSION-REGISTRY.md [session registry entry]
  2. Execute: python3 scripts/nightclaw-ops.py append memory/YYYY-MM-DD.md [structured pass log]
  3. Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run].T9 | TYPE:SESSION_CLOSE | RESULT:SUCCESS
  4. OVERWRITE LOCK.md: status=released, all other fields —

  The lock MUST be released at step 4. A pass that ends without releasing the lock
  will block all subsequent passes until the 20-minute stale window expires.

  APPEND-ONLY FILES — MANDATORY TOOL USAGE:
  Never use the Edit tool or WriteFile tool for APPEND-ONLY files.
  Always use: python3 scripts/nightclaw-ops.py append <file> <line>
  Or for multiple lines: python3 scripts/nightclaw-ops.py append-batch <file> <line1> ||| <line2>
  The script enforces the allowlist — only APPEND-tier files in REGISTRY.md R3 are accepted.
  This applies to: audit/AUDIT-LOG.md, audit/SESSION-REGISTRY.md, audit/CHANGE-LOG.md,
  audit/APPROVAL-CHAIN.md, NOTIFICATIONS.md, NOTIFICATIONS-ARCHIVE.md, AGENTS-LESSONS.md,
  and memory/YYYY-MM-DD.md.

STOP. Do not begin another pass.
```

---

## Cron Command
```bash
openclaw cron add \
  --name "nightclaw-worker-trigger" \
  --every 3h \
  --session isolated \
  --message "HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-WORKER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps." \
  --light-context \
  --no-deliver \
  --model anthropic/claude-haiku-3-5
```
