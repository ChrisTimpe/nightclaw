# CRON-WORKER-PROMPT.md — NightClaw Worker
# One pass. One objective. Structured. Audited. Then stop.
# Requires: --session "session:nightclaw-worker" --light-context --no-deliver

---

```
STARTUP — execute in this exact order before T0

  TOOL CONSTRAINT: Never use cd in commands. Never chain commands with && or ;.
  Never use heredoc (<<) syntax. Never use pipes (|). For multi-line args, write JSON to a temp file and use --file=<path>.
  The working directory is already the workspace root. Execute scripts directly:
  python3 scripts/nightclaw-ops.py <command>
  python3 scripts/nightclaw-ops.py --run-id=[run_id] <command>   ← use this form after step 4
  bash scripts/resign.sh <file>

  0. INTEGRITY CHECK (must be first — before lock, before reading any file)
     Execute: python3 scripts/nightclaw-ops.py integrity-check
     Output is one line per file (PASS/FAIL/MISSING) plus a summary line.
     The script output is authoritative. Do not recompute hashes yourself.

     RESULT:PASS → continue to step 1.
     RESULT:FAIL → STOP IMMEDIATELY. Do not acquire lock. Do not read any file.
       Do not write anything. Do not run T9. Just stop.
       The integrity check should never fail under normal operation.
       A failure means governance files were modified outside the system.
       The {OWNER} must investigate before any session can proceed.

  1. LOCK CHECK
     Execute: python3 scripts/check-lock.py session:nightclaw-worker
     The command output is authoritative. Do not override with your own reasoning.

     Output format: PROCEED, PROCEED:STALE_HOLDER=X:STALE_RUN=Y:FAILURES=N, or DEFER:holder=X:run_id=Y:expires=Z
     Parse the colon-delimited fields from the output. Do not read LOCK.md yourself.

     IF output starts with DEFER:
       Parse holder, run_id, expires from the output.
       Output: "[LOCK] Active lock detected. Holder: [holder]. Expires: [expires]. Deferring."
       Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[tentative-run_id].STARTUP | TYPE:LOCK_CHECK | RESULT:BLOCKED_BY:[run_id] | HOLDER:[holder]
       Execute: python3 scripts/nightclaw-ops.py append NOTIFICATIONS.md [ISO8601Z now] | Priority: LOW | Project: system | Status: WORKER-DEFERRED \nWorker startup deferred — [holder] holds lock (expires [expires]).
       EXIT cleanly. Do NOT proceed to step 2 or T0.

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
         run_id: [tentative RUN-YYYYMMDD-N — confirm at step 4]
         locked_at: [ISO8601Z now]
         expires_at: [ISO8601Z now + 20 minutes]
         consecutive_pass_failures: [incremented value if stale, else 0]
       Proceed to step 2.

  2. READ orchestration-os/CRON-HARDLINES.md
     Security boundary. Hard Lines + employment constraint.
     Not in context yet. Read before anything else.

  3. READ orchestration-os/REGISTRY.md sections R3 and R5 only (~2,500 tokens)
     Write routing table + bundle specifications. Skip R1, R2, R4, R6, R7.

  4. DETERMINE run_id
     Execute: python3 scripts/nightclaw-ops.py next-run-id
     The output is the run_id (e.g. RUN-20260410-003). Use it on ALL audit entries this session.
     UPDATE LOCK.md run_id field to the confirmed run_id.
     IMPORTANT: From this point forward, pass --run-id=[run_id] as the FIRST argument on EVERY
     nightclaw-ops.py call so telemetry is correlated to this session (not a transient CLI id).
     Example: python3 scripts/nightclaw-ops.py --run-id=RUN-20260410-003 append audit/AUDIT-LOG.md ...

─────────────────────────────────────────────
T0  AUDIT LOG — INTEGRITY RESULT
─────────────────────────────────────────────
  Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T0 | TYPE:INTEGRITY_CHECK | RESULT:PASS | FILES:[count from step 0 output]

─────────────────────────────────────────────
T1  DISPATCH
─────────────────────────────────────────────
  Execute: python3 scripts/nightclaw-ops.py dispatch
  The script applies all filtering rules (status, escalation_pending, priority sort).
  Output:
    DISPATCH:<slug> → proceed to T2 with that slug.
    ADVANCE:<slug>  → proceed to T2-ADVANCE with that slug.
    IDLE            → go to T1.5.

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
T2-ADVANCE  PHASE ADVANCE (runs ONLY when T1 returned ADVANCE:<slug>)
─────────────────────────────────────────────
  The {OWNER} has approved a phase transition (via nightclaw-admin done or
  via PA-003 phase-auto-advance pre-approval).

  READ PROJECTS/[slug]/LONGRUNNER.md — extract phase.successor.
  IF successor is empty →
    Execute: python3 scripts/nightclaw-ops.py bundle-exec surface_escalation slug=[slug] run_id=[run_id] priority=HIGH action_text="No successor defined for [slug]" context="phase_advance attempted but successor field is empty" reason="no-successor-defined"
    Go to T9.

  PA BOUNDARY CHECK (only if PA-triggered, not owner-approved):
    READ orchestration-os/OPS-PREAPPROVAL.md.
    Find the PA entry with action_class=phase-auto-advance.
    Read its Boundary field. Evaluate whether advancing to [successor] violates
    the boundary (e.g., "Do not advance to implementation or deployment phases").
    IF boundary violated →
      Execute: python3 scripts/nightclaw-ops.py bundle-exec surface_escalation slug=[slug] run_id=[run_id] priority=HIGH action_text="PA boundary prevents advance to [successor]" context="PA-003 boundary violation" reason="pa-boundary-violated"
      Go to T9.
    IF boundary OK → log PA invocation:
      Execute: python3 scripts/nightclaw-ops.py append audit/APPROVAL-CHAIN.md PA-003-INV-[NNN] | action=phase-advance | slug=[slug] | successor=[successor] | result=AUTHORIZED

  Construct the bootstrap objective string for the new phase:
    init_objective = "Initialize [successor] phase: review prior phase outputs, define phase objective and stop conditions for [successor]."

  Execute: python3 scripts/nightclaw-ops.py bundle-exec phase_advance slug=[slug] successor=[successor] run_id=[run_id] init_objective="[the init_objective string you constructed]"

  The executor handles all field writes, CHANGE-LOG entries, and AUDIT-LOG entry.

  After phase_advance completes, continue to T2 with the same slug.
  (The project is now ACTIVE with a bootstrap objective. Normal T2→T4→T6 flow.)

─────────────────────────────────────────────
T2  LONGRUNNER
─────────────────────────────────────────────
  Execute: python3 scripts/nightclaw-ops.py longrunner-extract <slug>
  The script extracts all routing-critical fields. Do not read the full LONGRUNNER file.
  Parse the key=value output lines.

  routing=COMPLETE  →
    Determine the recommended successor phase (from context of mission + what was accomplished).
    Write phase.successor in the LONGRUNNER with the recommended phase name.
    Execute: python3 scripts/nightclaw-ops.py bundle-exec phase_transition slug=[slug] successor=[successor] run_id=[run_id] escalation_text="phase-complete-[phase_name]" action_text="Confirm phase transition to [successor]"
    Go to T9.
  routing=BLOCKED   →
    Execute: python3 scripts/nightclaw-ops.py bundle-exec route_block slug=[slug] run_id=[run_id] reason="[reason]"
    Then re-dispatch: Execute: python3 scripts/nightclaw-ops.py dispatch (max 2 re-routes)
  routing=STALE_OBJECTIVE →
    Execute: python3 scripts/nightclaw-ops.py bundle-exec surface_escalation slug=[slug] run_id=[run_id] priority=MEDIUM action_text="Stale next_pass objective" context="next_pass.objective is empty" reason="stale-next-pass"
    Then re-dispatch (back to T1).
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
    NO  → skip. Continue to T3.
    YES → BUNDLE:pa_invoke:

  BUNDLE:pa_invoke (inline expansion):
    READ orchestration-os/OPS-PREAPPROVAL.md.
    Find the PA entry whose action_class matches the next_pass requirement:
      - pass_type=execution → action_class=file-write-extended or idle-cycle-autonomy
      - tools_required contains exec-capable tool → match by scope
    IF no matching PA found → BUNDLE:surface_escalation("No pre-approval covers exec/extended write for [slug]") → BUNDLE:route_block → T1.

    VALIDATE the matched PA entry:
      - Status: must be ACTIVE (not INACTIVE, not EXPIRED)
      - Expiry: expires field must be > now
      - Scope: PA scope must cover the target project slug and planned write paths
      - Boundary: planned action must not violate the PA boundary field
    IF any check fails → BUNDLE:surface_escalation("PA-[NNN] validation failed: [reason]") → BUNDLE:route_block → T1.

    ALL CHECKS PASS → log PA invocation:
      Execute: python3 scripts/nightclaw-ops.py append audit/APPROVAL-CHAIN.md PA-[NNN]-INV-[NNN] | [ISO8601Z] | run=[run_id] | action_class=[class] | slug=[slug] | scope=[PA scope] vs [planned scope] → MATCH | boundary=[PA boundary] vs [planned action] → OK | expires=[date] → WITHIN_BOUNDS | result=AUTHORIZED
      Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T2.7 | TYPE:BUNDLE | BUNDLE:pa_invoke | PA:[NNN] | RESULT:SUCCESS
    Continue to T3.

T3  TOOL CHECK
  READ orchestration-os/TOOL-STATUS.md.
  UNAVAILABLE/UNVERIFIED → BUNDLE:route_block → T1

[BLOCKER PROTOCOL — applies at T2, T2.7, T3]
  After any bundle-exec route_block call, re-dispatch:
  Execute: python3 scripts/nightclaw-ops.py dispatch
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
    PROJECTS/*/outputs/* → before writing, check if file already exists.
      If it exists AND current phase ≠ phase that created it: NEVER overwrite.
      Create a new file instead. Use phase-namespaced naming: <descriptive-name>-<phase>.md
      Example: discovery-landscape-exploration.md, correlation-model-correlation-design.md
      Prior phase outputs are audit artifacts — overwriting them destroys evidence of completed work.
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

  T6.1 — RECORD PASS (always, every pass):
    Execute: python3 scripts/nightclaw-ops.py bundle-exec longrunner_update slug=[slug] run_id=[run_id] quality=[quality] objective="[this pass objective]" output_files="[comma-separated files produced this pass]" next_objective="[see below]" model_tier=[tier] context_budget=[budget] tools="[tools]"

    For next_objective:
      IF ALL clauses are TRUE: next_objective = "Phase complete — transitioning to [successor]"
      IF ANY clause is FALSE: next_objective = "[objective addressing FALSE clauses]"

  T6.2 — STOP CONDITION GATE:
    IF ALL clauses are TRUE:
      Determine the recommended successor phase. Consider:
        - The project mission (## Mission section of LONGRUNNER)
        - What was accomplished in this phase
        - What logically comes next in the project lifecycle
      Write phase.successor in the LONGRUNNER with the recommended phase name.
      Use descriptive names (e.g., full-scale-run, quality-assurance, publish-prep, deployment).

      Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T6 | TYPE:STOP_EVAL | RESULT:ALL_TRUE | CLAUSES:[count]

      Construct the escalation and notification text:
        escalation_text = "phase-complete-[phase_name]"
        action_text = "Confirm phase transition from [phase_name] to [successor]"

      Execute: python3 scripts/nightclaw-ops.py bundle-exec phase_transition slug=[slug] successor=[successor] run_id=[run_id] escalation_text="[escalation_text]" action_text="[action_text]"

      Go to T7.

    IF ANY clause is FALSE:
      Execute: python3 scripts/nightclaw-ops.py append audit/AUDIT-LOG.md TASK:[run_id].T6 | TYPE:STOP_EVAL | RESULT:INCOMPLETE | FALSE_CLAUSES:[list]

      Go to T7.

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
  Exception: integrity failure at step 0 halts the session before lock acquisition — T9 does not run.

  BUNDLE:session_close — construct the three entry strings, then call the executor:
    session_entry = "[RUN-ID] | [session type] | [model] | [token count] | [integrity result] | [outcome summary]"
    memory_entry = "[structured pass log — project, phase, objective, result, next_pass]"
    audit_entry = "TASK:[run_id].T9 | TYPE:SESSION_CLOSE | RESULT:SUCCESS"

  Write the session_close JSON to a temp file, then execute:
    1. Write file: /tmp/session_close_[run_id].json containing {"run_id":"...", "session_entry":"...", "memory_entry":"...", "audit_entry":"..."}
    2. Execute: python3 scripts/nightclaw-ops.py bundle-exec session_close --file=/tmp/session_close_[run_id].json

  The executor writes all entries and releases LOCK.md. Verify output contains RETURNS:SUCCESS.
  If the executor fails, manually release LOCK.md as fallback:
    OVERWRITE LOCK.md: status=released, all other fields —

  APPEND-ONLY FILES — MANDATORY TOOL USAGE:
  Never use the Edit tool or WriteFile tool for APPEND-ONLY files.
  Always use: python3 scripts/nightclaw-ops.py append <file> <line>
  Or for multiple lines: python3 scripts/nightclaw-ops.py append-batch <file> <line1> ||| <line2>
  The script enforces the allowlist — only APPEND-tier files in REGISTRY.md R3 are accepted.
  This applies to: audit/AUDIT-LOG.md, audit/SESSION-REGISTRY.md, audit/CHANGE-LOG.md,
  audit/APPROVAL-CHAIN.md, NOTIFICATIONS.md, NOTIFICATIONS-ARCHIVE.md, AGENTS-LESSONS.md,
  and memory/YYYY-MM-DD.md.

T9.5  MODEL TIER SWITCH  ← runs after session_close, before STOP
─────────────────────────────────────────────
  Purpose: configure the platform default model for the NEXT worker session.
  The worker cron carries no --model flag — it inherits the platform default.
  This step sets that default to the model mapped to the dispatched project's
  next_pass.model_tier.

  Guard condition — run T9.5 ONLY IF all of the following are true:
    1. longrunner-extract ran this session (a slug was dispatched at T1)
    2. longrunner-extract returned a next_pass.model_tier value in its output
    3. That value is one of: lightweight, standard, heavy

  Skip T9.5 (silently) in all other cases:
    - IDLE pass (T1 returned IDLE → T1.5, no longrunner-extract ran)
    - Notifications-only pass (T1.5 actioned a notification entry, no slug dispatched)
    - routing=BLOCKED or routing=STALE_OBJECTIVE at T2 with no re-dispatch resolving
    - routing=COMPLETE at T2: longrunner-extract DID run, so next_pass.model_tier
      IS available in context from the T2 extract output — DO run T9.5 in this case.
      (T2.5 is skipped for COMPLETE routing, but the extracted value is still present.)
    - T2-ADVANCE boundary violation or no-successor path that went directly to T9
      without a successful longrunner-extract returning a model_tier value.

  If guard passes:
    Execute: python3 scripts/nightclaw-ops.py set-model-tier [model_tier]
    Where [model_tier] is the next_pass.model_tier value from the longrunner-extract output.
    Example: python3 scripts/nightclaw-ops.py set-model-tier standard

  Output: SET_MODEL_TIER:OK:tier=standard:model=<id>  — switch confirmed
          WARN:SET_MODEL_TIER:*  — non-fatal, next session uses previous model
          (skipped silently if MODEL-TIERS.md is absent — feature not configured)

  This step never aborts the session. Any failure is a WARN, not an ERROR.
  The manager cron is unaffected — it carries a hardcoded --model flag.

STOP. Do not begin another pass.
```

---

## Cron Command
```bash
openclaw cron add \
  --name "nightclaw-worker-trigger" \
  --every 3h \
  --session "session:nightclaw-worker" \
  --message "HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-WORKER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps." \
  --light-context \
  --no-deliver
# Note: no --model flag. The worker inherits the platform default, which NightClaw
# manages automatically via MODEL-TIERS.md. Set initial model with:
#   openclaw models set <your-starting-model-id> && openclaw config apply
```
