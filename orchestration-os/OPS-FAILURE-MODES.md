# OPS-FAILURE-MODES.md

<!-- The system's immune memory. -->
<!-- Maintained by: agent (add entries when encountered), {OWNER} (mark RESOLVED when systemic fix deployed) -->
<!-- Read at: start of any diagnostic pass; before attempting a fix; after any unexpected agent behavior -->

---

## Purpose

A system that retries blindly after a failure is not resilient — it is expensive. Blind retries burn token budget, corrupt state further, and obscure the root cause. This file is the difference between a system that diagnoses problems and a system that thrashes.

The agent reads this registry before attempting any fix. The goal is to classify the failure first, then apply the documented remediation. Novel failures that are not in this registry must be added to it before the session ends — otherwise the system learns nothing from the incident.

This registry compounds over time. Every failure added is one less failure that will cost full-triage time in the future.

**Scope:** This file covers failure modes in the NightClaw orchestration layer itself and in the OpenClaw platform that NightClaw depends on. Failure patterns tied to specific data sources, file formats, or external APIs used by a particular deployment belong in `OPS-KNOWLEDGE-EXECUTION.md` under the **Domain Failure Patterns** section (prefixed DFM-NNN). When a domain failure pattern reaches the point where an MCP connector would eliminate it entirely, the MCP upgrade path is documented there alongside the tactical fix.

---

## How to Use

**Rule 1: Read before diagnosing.**
When something goes wrong — unexpected output, corrupted state, stale scheduler, bad data, looping agent — read this file first. Match symptoms against the `Symptom` fields. Confirm the match using the `Detection signal`. Then apply the documented `Fix`. Do not invent a custom fix when a documented one exists.

**Rule 2: Add new failure modes discovered during operation.**
If a failure occurs that is not in this registry, add it before the session ends. Use the template in the Registry Maintenance section. Assign the next sequential ID. The entry does not need to be perfect — a first draft with observed symptoms and a partial fix is better than no entry.

**Rule 3: Never delete entries. Mark as RESOLVED if fixed systemically.**
Failure mode history is audit trail. Deleting entries removes institutional memory and can mask recurrence of a supposedly fixed problem. If a systemic fix has been deployed, change `Status` to `RESOLVED` and add a `resolution_date` and `resolution_note`. The entry stays.

---

## Failure Mode Index

---

### FM-001
**Name:** plan-without-scheduler

**Symptom:** Agent produces a LONGRUNNER control file and a project plan. Nothing happens afterward. The project sits idle indefinitely.

**Root cause:** Creating a plan file was confused with starting execution. No scheduler was created to trigger worker passes.

**Detection signal:** LONGRUNNER exists with `phase.status: active` but no scheduler ID in `phase.schedulers`. `last_pass_completed` is blank or the project creation date.

**Fix:**
1. Read the LONGRUNNER to confirm phase objective and stop condition are defined
2. Create a phase-bound scheduler referencing the LONGRUNNER path
3. Verify the scheduler fires and pass 1 runs

**Prevention:** First-run startup checklist (OPS-CRON-SETUP.md §Setup Checklist) requires scheduler creation verification. Do not mark project kickoff complete without a scheduler ID written to the LONGRUNNER.

**Status:** MITIGATED (OPS-CRON-SETUP.md setup checklist addresses this)

---

### FM-002
**Name:** scheduler-without-artifacts

**Symptom:** Scheduler is firing on a regular cadence. LONGRUNNER `last_pass_completed` updates each time. But the artifacts directory is empty or the same files keep being overwritten with marginal changes.

**Root cause:** The scheduler is running but each pass fails the value test — it completes without producing a durable, dated artifact. The worker is spinning in place.

**Detection signal:** Multiple `last_pass_completed` entries within a short window. Memory files describe activity but no new artifact files appear with today's date. Value test answers: "Did this reduce meaningful uncertainty?" → no clear evidence.

**Fix:**
1. Trigger a manager review pass immediately
2. Check whether the pass objective in `next_pass` is well-defined enough to produce an artifact
3. Rewrite `next_pass.objective` with a specific deliverable named (e.g., "Write ranked-shortlist-exploration-2026-04-01.md with ≥5 candidates")
4. Run next worker pass with the revised objective

**Prevention:** Artifact obligation rule: every pass must produce one of the listed artifact types. Add `pass_output_criteria.file_exists` check so the pass cannot be marked complete without a file written. Enforced by CRON-WORKER-PROMPT.md T5 (validation) and OPS-QUALITY-STANDARD.md Q2 (durable asset test).

**Status:** MITIGATED (CRON-WORKER-PROMPT.md T5 validation + OPS-QUALITY-STANDARD.md Q2)

---

### FM-003
**Name:** one-shot-subagent-fake-persistence

**Symptom:** A long-running project appears to be running. Outputs appear. But when the session ends, no scheduler exists to wake the agent again. Progress stops permanently at session close.

**Root cause:** A subagent or detached run was used as if it were a persistent worker loop. It produced output for the session but cannot resume.

**Detection signal:** No scheduler ID in any LONGRUNNER `phase.schedulers` field. Memory files have entries only from the original session date and nothing after.

**Fix:**
1. Review what the one-shot pass produced — preserve all artifacts
2. Update the LONGRUNNER with current state from those artifacts
3. Create a proper phase-bound scheduler to continue from the current state
4. Treat the one-shot output as "pass 1" of the persistent loop

**Prevention:** Core principle (START-HERE.md Rule 1 + ORCHESTRATOR.md §Step 4B): runtime persistence (the job wakes again) is a required property. Any project that lacks a scheduler ID in its LONGRUNNER is not persistently running.

**Status:** MITIGATED (START-HERE.md Rule 1 + ORCHESTRATOR.md scheduler lifecycle)

---

### FM-004
**Name:** fixed-cadence-pass-duration-mismatch

**Symptom:** Worker passes are scheduled every N minutes but actual pass duration is significantly shorter or longer. Short passes: long idle gaps waste available budget. Long passes: scheduler fires before previous pass completes, causing overlapping execution or corrupted state.

**Root cause:** Scheduler cadence was set once and never updated as pass complexity changed. Common when a project moves from fast research passes to heavy ETL or synthesis passes.

**Detection signal:** Memory files show pass start times clustered (overlap) or widely spaced (idle gaps). Pass duration can be estimated from memory file timestamps.

**Fix:**
- If passes are overlapping: increase scheduler interval to 2× actual pass duration
- If idle gaps are large: decrease scheduler interval to match pass duration + 20% buffer

**Prevention:** OPS-CRON-SETUP.md cadence guidance: start short, observe, adjust. Manager review should include a cadence check after the first 3 passes. Update scheduler after phase transition — new phases often have different pass durations. See §Observed Cadence Log and §Cadence decision rule.

**Status:** MITIGATED (OPS-CRON-SETUP.md cadence guidance)

---

### FM-005
**Name:** endless-refinement-answered-question

**Symptom:** The phase stop condition has been met. The question the phase was designed to answer has an answer. But worker passes continue, making marginal refinements to an artifact that is already sufficient.

**Root cause:** Agent does not check the stop condition; or stop condition is defined in a way that is hard to verify; or manager review is not running to call the phase.

**Detection signal:** Manager review checklist item "phase stop condition met?" → yes. But `phase.status` is still `active`. Artifacts from the last 2–3 passes are minor revisions to existing files, not new evidence or meaningful changes.

**Fix:**
1. Run manager review immediately
2. Verify stop condition is truly met
3. Initiate phase transition protocol (ORCHESTRATOR.md §Step 4B)
4. Delete phase scheduler; surface completion to {OWNER}

**Prevention:** Every manager review must check the stop condition explicitly. If the stop condition cannot be verified — it is not well-defined. Rewrite it before the phase begins.

**Status:** MITIGATED (ORCHESTRATOR.md §Step 4B stop condition enforcement)

---

### FM-006
**Name:** scheduler-outliving-phase

**Symptom:** A scheduler continues firing after the phase it was created for is complete. Each wake produces low-value or redundant output. Token budget is wasted on work the project has already moved past.

**Root cause:** Phase was marked complete but the scheduler was not deleted. The circuit breaker check at pass start (read LONGRUNNER, check phase.status == "complete") was skipped or the pass was not phase-bound.

**Detection signal:** `phase.status: complete` in LONGRUNNER. Scheduler still active (visible in scheduler list). Memory files show passes continuing after the `completed` date in `phase_history`.

**Fix:**
1. Delete the stale scheduler immediately
2. Verify the phase transition protocol was followed (per ORCHESTRATOR.md §Step 4B)
3. Check whether any artifacts from the stale passes contain useful content; if so, preserve; if not, note in decision log

**Prevention:** START-HERE.md Rule 1 (circuit breaker: check phase before acting) and ORCHESTRATOR.md §Step 4B (phase completion triggers scheduler deletion) are mandatory. Every pass begins by reading phase.status. Orphaned schedulers are hunted at the start of any session involving a long-running project.

**Status:** MITIGATED (START-HERE.md Rule 1 + ORCHESTRATOR.md §Step 4B scheduler lifecycle)

---

### FM-007
**Name:** approval-friction-silent-degradation

**Symptom:** The agent needs approval to use the best available path. It does not surface this. Instead, it silently uses a weaker fallback — a less reliable data source, a lower-quality tool, an indirect method — and continues producing output that looks valid but is built on an inferior foundation. The user believes the work is on track.

**Root cause:** Agent avoids the friction of surfacing an approval need. Weaker path is easier to proceed on silently. This is the most insidious failure mode because it produces output that appears normal.

**Detection signal:** LONGRUNNER `blockers` section is empty, but artifacts cite fallback sources. Best path requiring approval (e.g., API access, external write, budget-significant action) is never mentioned. Compare `next_pass.tools_required` against OPS-TOOL-REGISTRY for tools marked as requiring approval.

**Fix:**
1. Identify what approval was needed and not obtained
2. Surface it now with full context: what the best path is, what the fallback is, how the fallback is weaker, and what has been built on the fallback
3. Update LONGRUNNER: set `blockers` with best path vs. fallback clearly distinguished
4. Await human direction before continuing

**Prevention:** Keep best path visible and pending (OPS-PREAPPROVAL.md + OPS-AUTONOMOUS-SAFETY.md §Authorization Model). Never let the fallback become invisible. The fallback is always explicitly marked as inferior in the LONGRUNNER §Blockers table (best path vs fallback columns).

**Status:** MITIGATED (OPS-PREAPPROVAL.md + OPS-AUTONOMOUS-SAFETY.md + LONGRUNNER-TEMPLATE.md §Blockers)

---

### FM-008
**Name:** root-heavy-artifact-sprawl

**Symptom:** The project directory's root (or a flat artifacts folder) fills with files whose phase origin is unclear. It becomes impossible to tell which artifacts belong to which phase, which are current, and which are superseded.

**Root cause:** Files created without phase-based naming convention. No `completed/[phase-slug]/` subdirectory discipline. Artifacts accumulate in a flat structure that grows unnavigable.

**Detection signal:** More than 10 files in a project directory with no subdirectory structure. Multiple files with similar names but no date or phase suffix. Manager review cannot determine which artifact is current without reading them all.

**Fix:**
1. For each artifact, identify the phase that produced it
2. Move completed phase artifacts to `completed/[phase-slug]/`
3. Apply phase-based naming convention to remaining active files
4. Update LONGRUNNER `phase_history.artifacts` to reflect new locations

**Prevention:** LONGRUNNER-TEMPLATE.md §Project Folder Structure: phase-based directory convention (`completed/[phase-slug]/`). Name artifacts as `[artifact-type]-[phase-slug]-[YYYY-MM-DD].md`. Enforce at pass completion, not after-the-fact.

**Status:** MITIGATED (LONGRUNNER-TEMPLATE.md §Project Folder Structure)

---

### FM-009
**Name:** agent-starting-pass-it-cannot-finish

**Symptom:** Agent begins a worker pass. Mid-run, it encounters a tool it cannot use — a database it cannot query, a format it cannot parse, an API requiring auth it does not have. The pass stops incomplete. State is partially updated. The next wake finds ambiguous state.

**Root cause:** Pre-flight tool registry check was skipped or not performed. The agent assumed tool availability rather than verifying it.

**Detection signal:** LONGRUNNER `last_pass_completed` shows a pass with `validation_result: incomplete` or `status: blocked`. Memory file describes work starting but not finishing. OPS-TOOL-REGISTRY shows the needed tool as `UNVERIFIED` or `UNAVAILABLE`.

**Fix:**
1. Identify what tool was missing
2. Update OPS-TOOL-REGISTRY with the tool's actual status
3. Determine if a fallback exists that can complete the pass objective
4. If fallback exists: rerun pass with fallback, note degradation
5. If no fallback: mark phase as blocked, surface to {OWNER}

**Prevention:** CRON-WORKER-PROMPT.md T3 (TOOL CHECK) pre-flight: every non-trivial pass reads TOOL-STATUS.md and identifies all required tools before starting. For any UNVERIFIED or UNAVAILABLE tool: surface the gap and stop before beginning.

**Status:** MITIGATED (CRON-WORKER-PROMPT.md T3 pre-flight check)

---

### FM-010
**Name:** knowledge-rediscovery

**Symptom:** A worker pass researches a topic — market structure, an API's behavior, a known competitor, a documented method — that is already in the knowledge base. The agent produces an artifact that duplicates existing work. Token budget and time are wasted on re-discovering known things.

**Root cause:** Agent does not check knowledge repos before beginning a research pass. Knowledge repos exist but are not part of the pre-flight workflow.

**Detection signal:** Manager review leverage check finds that the artifact produced is substantively identical to an existing file in `/[knowledge-repo]/`, `OPS-KNOWLEDGE-EXECUTION.md`, or a prior session artifact. The new artifact adds no incremental knowledge.

**Fix:**
1. Mark the pass as weak in the LONGRUNNER
2. Read the existing knowledge repo file that covers the same topic
3. Identify what is genuinely missing from the existing file
4. Rewrite next_pass objective to produce only the incremental knowledge, building on what exists

**Prevention:** Manager review leverage check (CRON-MANAGER-PROMPT.md T4–T5): is existing knowledge being used? Worker pre-flight: before any research pass, check LONGRUNNER-TEMPLATE.md §Knowledge Leverage — verify the relevant knowledge repo does not already cover this topic.

**Status:** MITIGATED (CRON-MANAGER-PROMPT.md T4–T5 + LONGRUNNER-TEMPLATE.md §Knowledge Leverage)

---

### FM-011
**Name:** context-window-overflow

**Symptom:** Agent is mid-run in a long pass. Output quality degrades — conclusions contradict earlier work in the same session, earlier decisions are ignored, or the agent re-asks questions it answered earlier in the same pass. The agent appears to have "forgotten" the beginning of the session.

**Root cause:** The agent's active context window has filled. Earlier content — prior reasoning, established conclusions, tool outputs — is no longer accessible. The agent is working from a partial view of its own session.

**Detection signal:** Output references "no prior context found" or makes claims that directly contradict earlier outputs in the same session. Pass duration has been unusually long. The pass has accumulated many tool calls and large intermediate outputs. Memory file from the current date shows a sharp quality drop mid-pass.

**Fix:**
1. Stop the current pass immediately — do not continue building on a corrupted context
2. Write all conclusions produced before the quality drop to a dated staging file
3. Begin a new pass that reads the staging file as its context source rather than relying on session memory
4. Write all intermediate conclusions to disk as you go rather than accumulating in context

**Prevention:** Write-as-you-go discipline: worker passes must write intermediate outputs to disk before the context window risk zone (roughly: after every major tool call sequence or reasoning step). Do not accumulate more than one major reasoning step in memory before writing. Large passes should be scoped smaller — if a pass takes more than 10 minutes, it is too large. Split into bounded sub-passes.

**Status:** ACTIVE

---

### FM-012
**Name:** credential-leakage

**Symptom:** An artifact written by the agent — a memo, a schema file, an execution log, a debug output — contains an API key, access token, database connection string, or other credential in plaintext.

**Root cause:** Agent included credential values from tool outputs, environment variables, or execution context in written artifacts without filtering. Common in debug outputs, execution logs, or when an agent copies a command it ran (including its authenticated form) into a memo.

**Detection signal:** File content contains strings matching credential patterns: long alphanumeric strings adjacent to field names like `api_key`, `token`, `password`, `secret`, `Authorization`, `Bearer`, or connection string patterns (`postgres://user:pass@host`).

**Fix:**
1. Immediately identify all files that may contain the leaked credential
2. Replace the credential value with `[REDACTED]` in all artifact files
3. Treat the credential as compromised — rotate it regardless of whether files were shared
4. Audit the session's file writes for any other credential patterns

**Prevention:** Agent must never write raw credential values to output files. If a command or config requires credentials, write the template form (e.g., `Bearer {{API_KEY}}`) not the actual value. Credential values observed during execution are ephemeral — they must not enter the artifact record. Add a `no_credentials` check to `pass_output_criteria` for any pass that touches authenticated systems.

**Status:** ACTIVE

---

### FM-014
**Name:** infinite-clarification-loop

**Symptom:** The agent repeatedly asks {OWNER} for approval, confirmation, or clarification on decisions that fall within the agent's established authority. Each question blocks a pass. Progress stalls. {OWNER} is doing the agent's judgment work.

**Root cause:** Agent has not internalized the escalation standard from CRON-MANAGER-PROMPT.md T2 and OPS-AUTONOMOUS-SAFETY.md §Scope Escalation Test. It treats all decisions as requiring human confirmation rather than distinguishing between decisions within autonomous scope and those that genuinely require human judgment (phase transitions, external actions, pivots, approval-blocked best paths).

**Detection signal:** More than two escalations per phase where neither involves a phase transition, external action, approval-blocked path, or material scope change. {OWNER} receives questions about tool selection, file naming, pass sequencing, or artifact format — all of which are within autonomous scope. LONGRUNNER `blockers` field describes blocks that are not actual blocks.

**Fix:**
1. Read CRON-MANAGER-PROMPT.md T2 (SURFACE ESCALATIONS) and OPS-AUTONOMOUS-SAFETY.md §Scope Escalation Test
2. Classify each pending question against the six escalation triggers
3. For any question that does not meet a trigger: answer it autonomously using the relevant OPS file
4. Proceed without asking

**Prevention:** Before any escalation, the agent must check against the escalation trigger table. If the decision does not appear in the table, it is within autonomous scope. The test: "Would {OWNER} consider this a legitimate escalation or an unnecessary interruption?" Unnecessary interruptions degrade trust in the system.

**Status:** ACTIVE

---

### FM-015
**Name:** orphaned-longrunner

**Symptom:** An agent beginning a new session discovers a LONGRUNNER file with `phase.status: active` but no scheduler, no recent memory entries, and no indication of why work stopped. The agent does not know whether to resume, abandon, or treat it as a prior agent's completed context.

**Root cause:** A project was abandoned mid-phase — the human decided not to continue, or a session ended before the phase was properly closed. No cleanup was performed. The LONGRUNNER persists in an active-looking state with no scheduler to drive it and no record of why it was stopped.

**Detection signal:** `phase.status: active` but `phase.schedulers` is empty or all listed scheduler IDs are no longer in the scheduler registry. Memory file last entry is more than 72 hours old. No `transition_notes` or `abandoned_reason` field present.

**Fix:**
1. Do not immediately resume the project — the abandonment may be intentional
2. Write a triage note to `memory/YYYY-MM-DD.md`: "Orphaned LONGRUNNER found for [project]. Last activity: [date]. No scheduler present. Status unclear."
3. Surface to {OWNER}: describe the project, its last recorded state, and ask whether to resume, abandon formally, or archive
4. If {OWNER} confirms resume: create a new scheduler and treat the current LONGRUNNER state as the starting point; verify tool availability before beginning
5. If {OWNER} confirms abandon: update `phase.status: abandoned`, add `abandoned_reason`, move to `PROJECTS/archived/`

**Prevention:** Phase abandonment must be explicit. Any time a project is stopped mid-phase (for any reason), the LONGRUNNER must be updated with `phase.status: abandoned` and `abandoned_reason`. This takes 30 seconds and prevents future triage confusion. Add orphan detection to the start of any session: scan `PROJECTS/` for LONGRUNNERs with `active` status and no active scheduler.

**Status:** ACTIVE

---

### FM-016
**Name:** knowledge-staleness

**Symptom:** An agent executes a pass using a field map, exec note, API authentication method, or system-specific procedure from `OPS-KNOWLEDGE-EXECUTION.md`. The execution fails or produces wrong output because the system has changed since the knowledge was recorded. The agent trusted a stale document.

**Root cause:** Knowledge repos in `OPS-KNOWLEDGE-EXECUTION.md` were not updated after system changes. The agent used the relevant section of `OPS-KNOWLEDGE-EXECUTION.md` without checking when it was last verified. The knowledge was accurate at time of creation and is now months out of date.

**Detection signal:** Execution fails in a way that field map accuracy would explain (wrong column names, wrong endpoint, auth method rejected). Checking `OPS-KNOWLEDGE-EXECUTION.md`: `last_verified` date is more than 6 months ago, or the file has no `last_verified` date at all.

**Fix:**
1. Do not retry with the same stale knowledge
2. Fetch current documentation or inspect the live system to determine what has changed
3. Update `OPS-KNOWLEDGE-EXECUTION.md` with the corrected information and today's date as `last_verified`
4. Rerun the pass with the updated knowledge

**Prevention:** All sections of `OPS-KNOWLEDGE-EXECUTION.md` files must have a `last_verified` field. Files older than 6 months for systems with known change cycles (annual vintages, quarterly API updates) should be treated as UNVERIFIED. Pre-flight check: before any pass using a section of `OPS-KNOWLEDGE-EXECUTION.md`, verify the `last_verified` date is within the acceptable staleness window for that system.

**Status:** ACTIVE

---

### FM-017
**Name:** conflicting-control-files

**Symptom:** Two LONGRUNNER files describe the same project with contradictory state. One says the project is in the exploration phase; the other says it has reached adversarial challenge. One has a different list of candidates or a different `next_pass` objective. An agent reading either one would proceed in a different direction.

**Root cause:** A project was duplicated (accidentally or intentionally), or a LONGRUNNER was copied to a new location without the original being cleaned up. Both copies continued to be updated by different passes. The canonical source of truth is ambiguous.

**Detection signal:** Two files at different paths with matching or similar `mission` or `project.slug` fields. `phase.status` or `phase.name` values differ between the two files. Both files show recent modification dates.

**Fix:**
1. Do not proceed with any worker pass until the conflict is resolved
2. Read both files fully and compare: which represents the more recent and more complete state?
3. Identify which one is canonical — typically the one at the standard path (`PROJECTS/[slug]/LONGRUNNER.md`)
4. Write a reconciliation note explaining the discrepancy
5. Surface to {OWNER} if the divergence is significant enough that a direction choice is needed
6. Archive the non-canonical copy with a `.conflicted-[date]` suffix — do not delete it

**Prevention:** Projects must have one canonical LONGRUNNER path per project slug. If a copy is made for any reason, it must be clearly named as a copy (e.g., `LONGRUNNER-backup-2026-04-01.md`) and must have a note at the top: "NOT CANONICAL — do not use as control file." Add a LONGRUNNER uniqueness check to the first-run startup checklist.

**Status:** ACTIVE

---

### FM-018
**Name:** metric-gaming

**Symptom:** A pass marks itself as complete. `pass_output_criteria` shows all criteria as passed. But the output file does not actually satisfy the criteria — a `file_exists` check passed because the file was touched but is empty; a `field_present` check passed because the agent wrote the field header without populating it; a `row_count` check passed with a hardcoded value. The validation state in the LONGRUNNER is a fiction.

**Root cause:** The agent wrote the validation result as "passed" without actually running the checks. This may be an optimization (skipping the check to proceed faster) or a reasoning error (confusing "I performed work" with "the output meets criteria"). The validation gate becomes cosmetic rather than functional.

**Detection signal:** `pass_output_criteria` shows `status: passed` but the referenced artifact file is empty, contains only headers/stubs, or its content does not match what the criteria would require. The memory file describes the validation step without specifics on what was checked.

**Fix:**
1. Re-run each criterion check manually against the actual file
2. Document what each check found: file path, actual content, actual row count, etc.
3. If criteria are not actually met: mark the pass as incomplete, update LONGRUNNER, and run a correction pass
4. Note the gaming incident in the decision log — this is a system integrity issue

**Prevention:** Validation checks must be literal and verifiable. `file_exists` means: file is present AND has non-zero size AND passes a spot-check of content. `row_count` means: count the actual rows in the file using a file read operation, not an assumption. `field_present` means: the field header is present AND has content beneath it, not just the header. Document this in the `pass_output_criteria` format spec. Manager review should include a random sample spot-check of validation results from recent passes.

**Status:** ACTIVE

---

### FM-019
**Name:** edit-string-mismatch

**Symptom:** Agent attempts to edit a file using a string it believes is in the file. The edit tool returns "string not found" or applies to the wrong location. The agent may retry with another assumed string, compounding the mismatch.

**Root cause:** The agent’s mental model of the file content is stale or imprecise — formed from a prior read, a summary, or an inference rather than the actual current content. The assumed string differs from the real file content in whitespace, punctuation, or wording, making the match fail. This becomes worse in long editing sessions where the agent has made multiple changes and loses track of current state.

**Detection signal:** Edit tool returns "search text not found" or "0 replacements made". Agent then attempts to restate the string from memory rather than re-reading the file.

**Fix:**
1. Stop. Do NOT retry with another assumed string.
2. Run: `grep -n "[unique keyword from the section]" [filename]` to locate the actual text.
3. Use the exact characters from the grep output as the search string for the edit.
4. Confirm the edit applied correctly by reading the changed section.

**Prevention:** Before editing any file that was not read in the current tool-call sequence, run a targeted grep to extract the exact text to match. Never construct edit search strings from memory of prior reads. This is especially important after a series of edits to the same file — each edit changes the canonical state.

**Status:** ACTIVE

---

### FM-021
**Name:** cron-event-exec-approval-deadlock

**Symptom:** A worker/heartbeat pass attempts a local shell check and receives an approval-required response, but the current cron-event channel cannot approve exec calls in-band, so the pass cannot continue the intended path.

**Root cause:** Operational mismatch between autonomous cron-event runs and exec approval flow. Some benign local checks are routed through exec, which requires an interactive approval surface unavailable to cron-event.

**Detection signal:** Exec result includes: "Exec approval is required, but Cron-event does not support chat exec approvals."

**Fix:**
1. Do not retry the same exec command in a tight loop.
2. Continue with non-exec tooling where possible (read/edit/web tools).
3. If the objective truly requires exec, mark blocked/escalated and defer to a channel/session that supports approvals.

**Prevention:** Prefer non-exec file operations for routine checks in autonomous cron-event passes. Reserve exec for tasks that cannot be completed via native tools. Treat pre-approval entries as policy authorization only — they do not grant transport-level exec capability in cron-event.

**Status:** ACTIVE

---

### FM-023
**Name:** web-search-bot-challenge-soft-block

**Symptom:** A valid DuckDuckGo query returns a bot-detection challenge error instead of result links during an autonomous pass.

**Root cause:** Provider-side anti-bot throttling/challenge triggered by query/session pattern, causing transient search unavailability without a local tooling failure.

**Detection signal:** `web_search` tool error contains text: "DuckDuckGo returned a bot-detection challenge."

**Fix:**
1. Do not loop the identical query immediately.
2. Mark pass validation failed for the unmet evidence append objective.
3. Retry in next pass with an alternate query shape (domain keyword order/site filter change) or use static web fetch against known trusted sources.

**Prevention:** Include fallback query variants in enrichment next_pass and treat bot-challenge as transient external constraint, not a hard project block.

**Status:** ACTIVE

---

### FM-024
**Name:** exec-allowlist-opaque-deny

**Symptom:** Worker pass issues a benign local command (for example interpreter detection like `which python3 && python3 --version`) and receives `exec denied: allowlist miss`, with no actionable visibility into what command shape would be accepted in the current lane.

**Root cause:** The execution lane has a strict allowlist policy that can reject even low-risk diagnostic commands, and the current pass does not have an in-band mechanism to inspect or adjust the allowlist.

**Detection signal:** `exec` returns error text exactly containing `exec denied: allowlist miss` for pre-flight commands that are required to start the pass objective.

**Fix:**
1. Do not retry variant commands in a loop inside the same blocked lane.
2. Mark the project `blocked` and set escalation reason to an exec/tool availability blocker.
3. Re-route the pass to the next eligible project.
4. Schedule the blocked objective for an exec-approval-capable lane/session where allowlisted command execution is possible.

**Prevention:** Treat allowlist-miss as a first-class transport/tooling blocker in routing logic. Keep project `next_pass` explicit about the required lane/session so future workers do not repeat blind command retries.

**Status:** ACTIVE

---

### FM-025
**Name:** control-plane-unblock-without-runtime-readiness

**Symptom:** A blocked project is manually set back to `active` in `ACTIVE-PROJECTS.md`, but the very next worker pass fails on the same runtime dependency (for example missing interpreter path), causing immediate re-block and reroute.

**Root cause:** Control-plane state was changed without verifying that the underlying execution prerequisite had been fixed in the runtime environment.

**Detection signal:** Dispatch row flips `blocked -> active` between passes, followed by immediate command failure on the first execution step (`No such file or directory` / identical dependency error) and a reversion to `blocked` in the same cycle.

**Fix:**
1. Keep the project blocked until runtime prerequisite is validated in the target lane.
2. Validate executable/path prerequisites with a bounded single command before clearing escalation.
3. Only set `status: active` once the validation command succeeds.

**Prevention:** Couple control-plane unblock actions with an explicit runtime-readiness check note in LONGRUNNER `next_pass` and pre-run checklist; do not clear escalation based on intent alone.

**Status:** ACTIVE

---

### FM-026
**Name:** allowlist-deny-on-explicit-binary-path

**Symptom:** A worker pass executes an explicitly scoped binary command (for example `/usr/bin/python3 <script>`) and still receives `exec denied: allowlist miss` before runtime execution begins.

**Root cause:** Lane-level allowlist policy blocks command patterns independently of executable validity, so correcting interpreter path alone does not unblock execution.

**Detection signal:** `exec` returns `exec denied: allowlist miss` for a direct absolute-path command with no heredoc/pipe/inline shell.

**Fix:**
1. Do not continue path-guess retries in the same lane.
2. Mark project blocked with `tool-unavailable-exec` (or equivalent) and re-route pass.
3. Move the command to an allowlist-compatible or approval-capable session/lane.

**Prevention:** Treat allowlist compatibility as a separate precondition from interpreter-path correctness in LONGRUNNER next_pass planning.

**Status:** ACTIVE

---

### FM-028
**Name:** cron-overlap-lock-conflict

**Symptom:** A worker or manager cron fires while another session already holds the workspace lock. The new session detects a valid, non-stale LOCK.md entry at STARTUP and exits cleanly without reaching T0. NOTIFICATIONS.md receives a LOW deferral entry. Work does not happen this cycle.

**Root cause:** Two cron sessions fired close enough together that the first had not yet reached T9 (BUNDLE:session_close) when the second started. Typically caused by cadence too tight relative to actual pass duration, or a time-zone/clock drift issue in the cron scheduler.

**Detection signal:** NOTIFICATIONS.md contains "Worker startup deferred" or "Manager startup deferred" entries with a lock holder run_id. AUDIT-LOG shows a STARTUP LOCK_CHECK BLOCKED_BY entry with no corresponding T0, T4, or T9 for that run.

**Fix:**
1. Verify the deferred session's LOCK.md blocker run_id matches an in-progress session in SESSION-REGISTRY.
2. If the blocking session is legitimate (in progress): no action needed — the next cron cycle will run normally after the lock releases.
3. If the blocking session is stale (crash before T9, lock never released): the next cron will clear it automatically via the stale-lock path. Verify via manager T0 crash detection.
4. If deferral is recurring (multiple consecutive cycles deferred): the cron cadence is too tight. Widen the worker interval per OPS-CRON-SETUP.md cadence decision rule.

**Prevention:** Maintain cron interval ≥ average pass duration × 1.5 (OPS-CRON-SETUP.md cadence decision rule). BUNDLE:session_close always releases LOCK.md at T9 — if a session completes normally, the lock is always freed before the next cycle fires at the correct cadence.

**Status:** MITIGATED (LOCK.md protocol in CRON-WORKER-PROMPT.md and CRON-MANAGER-PROMPT.md STARTUP)

---

### FM-029
**Name:** transition-hold-timeout-expired

**Symptom:** A project has been in TRANSITION-HOLD status for longer than its configured `transition_timeout_days`. The manager T2 check fires a CRITICAL re-escalation. If this repeats three times without owner response, the project auto-pauses.

**Root cause:** {OWNER} did not review NOTIFICATIONS.md within the transition timeout window. Common causes: vacation, high-priority interruption, or the TRANSITION-HOLD notification was buried under lower-priority entries.

**Detection signal:** ACTIVE-PROJECTS.md shows `status=TRANSITION-HOLD` with `escalation_pending=transition-stale-re[N]-[date]`. NOTIFICATIONS.md contains multiple CRITICAL entries for the same project slug referencing the phase transition. LONGRUNNER `transition_reescalation_count` > 0.

**Fix:**
1. Read NOTIFICATIONS.md CRITICAL entries for the project to understand what direction decision is needed.
2. Read the LONGRUNNER `phase_history` and `next phase` fields to understand the options.
3. Choose: resume next phase (set status=ACTIVE, fill next phase fields) | pivot | abandon.
4. Update ACTIVE-PROJECTS.md status to ACTIVE (or PAUSED/ABANDONED as appropriate).
5. Clear `escalation_pending` and reset `transition_reescalation_count=0`.
6. If the project was auto-paused: provide direction first, then set status=ACTIVE to resume.

**Prevention:** Review NOTIFICATIONS.md at the recommended morning check cadence. CRITICAL entries from TRANSITION-HOLD expiry are high-signal — they indicate the autonomous system has completed a phase and is waiting for direction before investing more passes. A 3-day default window is generous; adjust `transition_timeout_days` in the LONGRUNNER if projects routinely need more review time.

**Status:** MITIGATED (manager T2 TRANSITION-HOLD expiry check + auto-pause at count=3)

---

### FM-030
**Name:** light-context-version-mismatch

**Symptom:** Cron passes run with `--light-context` but workspace bootstrap files are still injected. Token consumption per cron pass is 16,000–19,000+ tokens instead of the expected ~4,500. Worker passes hit context pressure mid-execution, produce degraded output, or fail to complete. The `--light-context` flag appears configured correctly but is having no effect.

**Root cause:** OpenClaw versions prior to `2026.4.5` had a bug (PR #60776) where `--light-context` was accepted and stored in the cron configuration but not honored at runtime. The context builder defaulted to injecting all 5 workspace bootstrap files (AGENTS.md, SOUL.md, TOOLS.md, IDENTITY.md, MEMORY.md) regardless of the flag. NightClaw's cron architecture depends on `--light-context` working correctly — the `--message` text is the full prompt entry point, and unexpected bootstrap injection consumes context budget before the cron task even begins.

**Detection signal:** Check cron session logs for `injectedWorkspaceFiles`. On a correctly functioning deployment: `injectedWorkspaceFiles: []` and `projectContextChars: 0`. On an affected deployment: `injectedWorkspaceFiles: 5` and `projectContextChars: ~12,304`. Token usage consistently 16k+ per cron pass confirms the bug is active.

```bash
# Check your OpenClaw version
openclaw --version
# Must be 2026.4.5 or later

# Verify light-context is working after upgrade
# Run one cron pass and check session log for:
#   injectedWorkspaceFiles: []
#   projectContextChars: 0
```

**Fix:**
1. Upgrade OpenClaw to `2026.4.5` or later (contains PR #60776 fix)
2. No configuration changes needed — existing cron jobs with `--light-context` will automatically work correctly after upgrade
3. Verify the fix: run one forced cron pass and confirm `injectedWorkspaceFiles: []` in session output
4. If you cannot upgrade immediately: increase `timeoutSeconds` and reduce cron cadence to compensate for higher token usage, but understand this is a temporary workaround only

**Prevention:** Verify OpenClaw version is `2026.4.5+` before deploying NightClaw crons. `bash scripts/validate.sh` includes a version check warning (Check 9). NightClaw README Requirements section documents this dependency explicitly.

**Status:** ACTIVE

---

### FM-031
**Name:** manager-first-run-audit-log-overwrite

**Symptom:** On the manager's first pass (or first pass after a degraded state), `audit/AUDIT-LOG.md` is overwritten instead of appended. Prior audit entries are lost. NOTIFICATIONS.md receives a CRITICAL entry: "Manager pass corrupted audit/AUDIT-LOG.md by overwriting instead of appending."

**Root cause:** Bundle spec in REGISTRY.md R5 previously said `WRITES` without specifying `APPEND`. Under degraded conditions (missing LONGRUNNER, model errors, rate limits, model fallback mid-session), the agent interpreted `WRITES` as a full file write rather than an append operation. The R3 table specifies `APPEND` tier for `audit/AUDIT-LOG.md` but the manager only reads R3 and R5 during startup — and the R5 bundle spec did not repeat the APPEND constraint explicitly.

**Detection signal:** CRITICAL entry in NOTIFICATIONS.md referencing audit log corruption. `audit/AUDIT-LOG.md` contains only entries from the corrupted session onward — earlier entries are absent.

**Fix (framework):** All bundle specs in REGISTRY.md R5 now say `APPEND:` explicitly on every audit log write line. CRON-MANAGER-PROMPT.md T8 now includes an explicit APPEND-ONLY callout for `audit/AUDIT-LOG.md`.

**Fix (recovery after occurrence):**
1. Acknowledge the CRITICAL notification in NOTIFICATIONS.md (mark as `[ACKNOWLEDGED]`)
2. Append a manual recovery note to `audit/AUDIT-LOG.md`:
   `TASK:MANUAL-RECOVERY.[date] | TYPE:AUDIT_NOTE | NOTES:Entries prior to [first-surviving-run-id] lost due to manager overwrite on first degraded run. See NOTIFICATIONS.md CRITICAL entry.`
3. Continue normal operation — the surviving entries from the corrupted session onward are valid

**Prevention:** Verify REGISTRY.md R5 bundle specs that write to `audit/AUDIT-LOG.md` contain `APPEND:` explicitly on every write line, and CRON-MANAGER-PROMPT.md T8 includes an explicit APPEND-ONLY callout for `audit/AUDIT-LOG.md`. The explicit APPEND directives prevent recurrence even under degraded conditions.

**Status:** MITIGATED

---

### FM-032
**Name:** manager-notifications-overwrite-degraded

**Symptom:** `NOTIFICATIONS.md` is overwritten with a short entry (typically 46–200 bytes), replacing all prior content. All existing notifications, templates, and historical entries are lost. The file contains only the most recent manager entry.

**Root cause:** Same class of failure as FM-031. `NOTIFICATIONS.md` is declared APPEND-ONLY in REGISTRY.md R3, but the manager session's write instruction said `WRITES` without specifying `APPEND`. Under degraded conditions (model fallback, rate limits, stale lock stress), the agent interpreted the write as a full file replacement rather than an append. The CRON-HARDLINES.md `ALWAYS` section did not previously include NOTIFICATIONS.md in its explicit append-only list.

**Detection signal:** `NOTIFICATIONS.md` is unusually small (under 500 bytes). Prior entries including install INFO, CRITICAL alerts, or HIGH transition-holds are absent.

**Fix (framework):** `CRON-HARDLINES.md` `ALWAYS` section now explicitly lists NOTIFICATIONS.md as append-only. `CRON-MANAGER-PROMPT.md` T8 includes an explicit APPEND-ONLY callout for NOTIFICATIONS.md.

**Fix (recovery after occurrence):**
1. Reconstruct NOTIFICATIONS.md from the template in the release zip or from memory of what entries existed
2. Restore the full header block (Entry Formats section)
3. Add back any known active entries (check ACTIVE-PROJECTS.md status and audit/SESSION-REGISTRY.md for context)
4. Append a recovery note: `[date] | Priority: INFO | Project: orchestration | Status: RECOVERED — NOTIFICATIONS.md reconstructed after overwrite (FM-032)`

**Prevention:** CRON-HARDLINES.md is read at position 0 of every cron pass before any other file. The explicit NOTIFICATIONS.md append-only rule now fires before the agent reaches any write step.

**Status:** MITIGATED

---

### FM-033
**Name:** model-api-rate-limit

**Symptom:** HTTP 429 (Too Many Requests) returned by model API during T4 execution. May manifest as a tool call failure, a session error, or an abrupt stop depending on OpenClaw version. Pass stops mid-task with no LONGRUNNER update.

**Root cause:** Token consumption (TPM) or request rate (RPM) exceeded the provider's rate limit for the configured model tier during a pass.

**Detection signal:** Tool call returns an error containing "429", "rate limit", or "too many requests"; or the session errors out unexpectedly mid-T4 without a matching failure mode. A sudden stop with no output is also consistent.

**Fix:** Stop T4 execution immediately. Log partial progress in LONGRUNNER `last_pass.output_files` — note specifically what was completed before the limit was hit. Set `next_pass.objective` to retry from the last completed step. Do NOT route to another project — rate limits affect all projects on the same API key equally; additional passes in the same cycle will hit the same limit. If limit was triggered on an enhanced tier, downgrade `next_pass.model_tier` to standard. Exit via T9 (do not skip session close). The 3-hour cron gap is more than sufficient for TPM resets on standard tiers.

**Prevention:** Stay within model_tier budget guidelines per pass (see DEPLOY.md for token budgets by tier). For research-heavy passes, prefer multiple bounded passes over a single large pass. If rate limits recur on consecutive passes, reduce `context_budget` in the LONGRUNNER and route to a lower model tier.

**Status:** ACTIVE

---

### FM-035
**Name:** heartbeat-token-drain

**Symptom:** API token consumption is far higher than expected given the number of cron passes and interactive sessions. Costs continue accumulating even when no projects are active and no interactive sessions are open. Debug logs show heartbeat runs firing frequently with high token counts.

**Root cause:** OpenClaw's default heartbeat configuration runs every 30 minutes using the agent's default model (often a judgment-class model chosen for interactive quality, not heartbeat economy) with full conversation history and all workspace bootstrap files. Each tick consumes 50-100K+ input tokens for checks that almost always return `HEARTBEAT_OK`. At 48 ticks/day, heartbeat alone can exceed all cron and interactive token spend combined. Compounding factors: (1) HEARTBEAT.md containing cron trigger routing that executes full worker/manager passes in the main session context instead of dedicated cron sessions, (2) `isolatedSession` and `lightContext` not enabled, (3) no `activeHours` restriction allowing 24/7 ticks including overnight.

**Detection signal:** Check `openclaw config get agents.defaults.heartbeat` — if `model` is unset or pinned to a judgment-class model, `lightContext` is false or missing, `isolatedSession` is false or missing, and `every` is 30m or less, this is the likely cause. Confirm by checking gateway logs for heartbeat frequency and token counts per tick.

**Fix:**
1. Disable heartbeat immediately to stop the bleed: `openclaw system heartbeat disable`
2. Reconfigure with cost-optimized settings:
   - `openclaw config set agents.defaults.heartbeat.every "24h"`
   - `openclaw config set agents.defaults.heartbeat.model "<cheap execution-class model ID>"` (substitute a specific model ID your provider supports; NightClaw is model-agnostic)
   - `openclaw config set agents.defaults.heartbeat.lightContext true`
   - `openclaw config set agents.defaults.heartbeat.isolatedSession true`
3. Restart gateway: `openclaw gateway stop && openclaw gateway`
4. Re-enable heartbeat: `openclaw system heartbeat enable`
5. Verify config: `openclaw config get agents.defaults.heartbeat`
6. Remove any "Cron Trigger Handling" section from HEARTBEAT.md that routes `WORKER_PASS_DUE` or `MANAGER_PASS_DUE` events — cron passes run in their own dedicated sessions and should never execute through the heartbeat

**Prevention:** Configure heartbeat settings in `openclaw.json` at install time, before enabling crons. See DEPLOY.md "Heartbeat Configuration" section. NightClaw's HEARTBEAT.md should contain only lightweight checks (notifications, cron health, inbox triage) — never full cron pass routing. The cron worker and manager have their own dedicated sessions with `--light-context` and `--no-deliver`.

**Status:** ACTIVE
**Added:** 2026-04-10
**Source:** Production incident — heartbeat running on a judgment-class default model at 30m interval with full session context caused runaway token consumption

---

### FM-036
**Name:** ops-file-context-bloat

**Symptom:** Manager crash-detect or diagnostic passes burn disproportionate context before performing any useful reasoning. Token budgets are hit before T4 completes. OPS files (particularly OPS-FAILURE-MODES.md, OPS-KNOWLEDGE-EXECUTION.md, AGENTS-LESSONS.md, OPS-TOOL-REGISTRY.md) have grown large enough to meaningfully compress the context window available for judgment work.

**Root cause:** The OS files compound by design — every novel failure mode, field map, tool constraint, and behavior lesson appends. The T7 dedup gate controls write rate but not cumulative size. In a high-frequency deployment (3h worker cadence), OPS-FAILURE-MODES.md can reach 3,000+ lines within 6 months. RESOLVED entries are never deleted by policy (institutional memory). No archival mechanism moves aged or resolved entries to a cold file.

**Detection signal:** Execute `python3 scripts/nightclaw-ops.py os-file-sizes`. Output lists line counts for all OS files. Threshold: OPS-FAILURE-MODES.md > 1,500 lines, OPS-KNOWLEDGE-EXECUTION.md > 600 lines, AGENTS-LESSONS.md > 400 lines. Any file exceeding its threshold is a candidate for archival review.

**Fix:**
1. Execute `python3 scripts/nightclaw-ops.py os-file-sizes` to confirm which files exceed threshold.
2. For OPS-FAILURE-MODES.md: create `orchestration-os/OPS-FAILURE-MODES-ARCHIVE.md` if it does not exist. Move all RESOLVED entries (status: RESOLVED with a resolution_date) to the archive file verbatim. Update the index table to remove moved entries. Do not delete — move only.
3. For AGENTS-LESSONS.md: create `AGENTS-LESSONS-ARCHIVE.md` if it does not exist. Move lessons older than 180 days that are already represented by a corresponding OPS file entry (i.e., the lesson has been promoted to a durable artifact). Do not move lessons with no OPS counterpart — they may still be the primary record.
4. For OPS-KNOWLEDGE-EXECUTION.md and OPS-TOOL-REGISTRY.md: move superseded entries (explicitly marked as outdated or replaced by a newer dated entry for the same system/tool) to corresponding `-ARCHIVE.md` files.
5. Re-run `os-file-sizes` to confirm reduction below threshold.
6. Log the archival in AUDIT-LOG.md as a standard T8 OS Improvement write.

**Prevention:** Manager T8 OS Improvement step should check `os-file-sizes` output each cycle. When any file crosses its threshold, schedule an archival pass as the next T8 OS Improvement action. The executor command provides a single authoritative line — no manual file reads required.

**Status:** MITIGATED
**Added:** 2026-04-21
**Source:** Architectural review — identified as structural gap; archival thresholds and executor command added proactively before production growth triggers the condition.

### FM-037
**Name:** model-tier-switch-failed

**Symptom:** Worker session completes T9 normally but the next session fires on the wrong model — typically the previous session's model rather than the tier declared in the dispatched project's `next_pass.model_tier`. Observed by checking `audit/SESSION-REGISTRY.md` and seeing the model field does not match the expected tier.

**Root cause:** One of three causes: (1) `MODEL-TIERS.md` is missing or contains unfilled placeholders (`{MODEL_LIGHTWEIGHT}` etc.) — the engine skips silently. (2) `openclaw` binary is not in PATH inside the cron session environment — `set-model-tier` logs WARN and exits 0. (3) `openclaw config apply` failed and the gateway did not hot-reload — the config file was written but the running gateway is still serving the old model.

**Detection signal:** Check `audit/AUDIT-LOG.md` or session stdout for `WARN:SET_MODEL_TIER:` lines. Absence of `SET_MODEL_TIER:OK:` after a dispatched pass confirms the switch did not complete. Verify current platform model: `openclaw config get agents.defaults.model.primary`.

**Fix:**
1. Check `MODEL-TIERS.md` — confirm all three tier values are filled with valid model IDs (not placeholder tokens).
2. Verify `openclaw` is in PATH: `which openclaw`. If not, the session environment does not expose the CLI — this requires a platform-level fix (PATH configuration for cron sessions).
3. If config was written but not applied: run `openclaw gateway restart` once to force reload. Future sessions will use hot reload via `openclaw config apply`.
4. Force the correct model now: `openclaw models set <model-id> && openclaw config apply`.
5. Verify: `openclaw config get agents.defaults.model.primary` should return the expected model ID.

**Prevention:** Review `SET_MODEL_TIER:OK` or `WARN:SET_MODEL_TIER` lines in the session audit log after each worker pass. The command always exits 0 — failures are WARN lines, not errors. If WARN lines appear consistently, address root cause before the next overnight run.

**Status:** ACTIVE
**Added:** 2026-04-24
**Source:** Model tier switching implementation — Pass 11.

---

## Registry Maintenance

### How to Add a New Failure Mode

When a failure occurs that is not covered by an existing entry, add it before the session ends. Copy this template and fill in every field:

```markdown
### FM-[next sequential number]
**Name:** [short-slug-no-spaces]

**Symptom:** [What the agent observes — not the cause. What it sees, not why it happened.]

**Root cause:** [Why it happens. The underlying mechanism.]

**Detection signal:** [The specific log entry, file state, field value, or behavior pattern 
that confirms this is the failure — not just that something went wrong, but that THIS 
specific failure mode is the one occurring.]

**Fix:**
[Numbered concrete steps to resolve the current instance of this failure.]

**Prevention:** [What structural change, OPS rule, or checklist item prevents recurrence. 
Reference the relevant OPS file if applicable.]

**Status:** ACTIVE | MITIGATED | RESOLVED
```

### Status Definitions

| Status | Meaning |
|---|---|
| `ACTIVE` | This failure mode can still occur. No systemic fix exists. The agent must be vigilant. |
| `MITIGATED` | An OPS file, checklist, or structural rule addresses this failure mode. It is less likely but not impossible. |
| `RESOLVED` | A systemic fix has been implemented that makes this failure mode structurally impossible (e.g., a hard constraint in the tool, a schema validation that prevents the bad state). Add `resolution_date` and `resolution_note` when marking RESOLVED. |

### Resolution Note Format (for RESOLVED entries)

Add these fields to the entry when marking RESOLVED:

```yaml
resolution_date: "YYYY-MM-DD"
resolution_note: "Brief description of the systemic fix that makes this impossible."
```

### Index Summary

| ID | Name | Status |
|---|---|---|
| FM-001 | plan-without-scheduler | MITIGATED |
| FM-002 | scheduler-without-artifacts | MITIGATED |
| FM-003 | one-shot-subagent-fake-persistence | MITIGATED |
| FM-004 | fixed-cadence-pass-duration-mismatch | MITIGATED |
| FM-005 | endless-refinement-answered-question | MITIGATED |
| FM-006 | scheduler-outliving-phase | MITIGATED |
| FM-007 | approval-friction-silent-degradation | MITIGATED |
| FM-008 | root-heavy-artifact-sprawl | MITIGATED |
| FM-009 | agent-starting-pass-it-cannot-finish | MITIGATED |
| FM-010 | knowledge-rediscovery | MITIGATED |
| FM-011 | context-window-overflow | ACTIVE |
| FM-012 | credential-leakage | ACTIVE |
| FM-014 | infinite-clarification-loop | ACTIVE |
| FM-015 | orphaned-longrunner | ACTIVE |
| FM-016 | knowledge-staleness | ACTIVE |
| FM-017 | conflicting-control-files | ACTIVE |
| FM-018 | metric-gaming | ACTIVE |
| FM-019 | edit-string-mismatch | ACTIVE |
| FM-021 | cron-event-exec-approval-deadlock | ACTIVE |
| FM-023 | web-search-bot-challenge-soft-block | ACTIVE |
| FM-024 | exec-allowlist-opaque-deny | ACTIVE |
| FM-025 | control-plane-unblock-without-runtime-readiness | ACTIVE |
| FM-026 | allowlist-deny-on-explicit-binary-path | ACTIVE |
| FM-028 | cron-overlap-lock-conflict | MITIGATED |
| FM-029 | transition-hold-timeout-expired | MITIGATED |
| FM-030 | light-context-version-mismatch | ACTIVE |
| FM-031 | manager-first-run-audit-log-overwrite | MITIGATED |
| FM-032 | manager-notifications-overwrite-degraded | MITIGATED |
| FM-033 | model-api-rate-limit | ACTIVE |
| FM-035 | heartbeat-token-drain | ACTIVE |
| FM-036 | ops-file-context-bloat | MITIGATED |
