# LONGRUNNER — [PROJECT NAME]
<!-- Copy to PROJECTS/[slug]/LONGRUNNER.md. Fill the CORE section before starting. Appendix is optional. -->
<!-- Rule: if this file is stale, the project is lost. Update after every pass. -->

---

# CORE (fill before starting — takes under 5 minutes)

## Mission
<!-- One sentence: what is this project for and what makes it a success? -->


## Conflict Check
- Domain: [state the domain]
- Conflict risk: low / medium / FLAG
- [ ] Confirmed: not in prohibited domain (check USER.md for declared restrictions)

## Current Phase

```yaml
phase:
  name: ""          # example names: exploration | adversarial-challenge | shortlist | implementation-planning | proof-execution | deployment
                   # (these are examples, not required vocabulary — use names that fit your project)
  objective: ""     # one sentence
  stop_condition: ""  # verifiable — not subjective. If you can't test it, rewrite it.
  started: ""       # YYYY-MM-DD
  schedulers: []    # scheduler IDs bound to this phase — delete these when phase completes
  successor: ""     # next phase name
  status: "active"  # active | complete | blocked | abandoned
  # Transition fields (set by BUNDLE:phase_transition when status → complete):
  transition_triggered_at: ~    # ISO8601Z timestamp when phase_transition bundle fired
  transition_expires: ~         # ISO8601Z deadline for {OWNER} direction (triggered_at + timeout_days)
  transition_timeout_days: 3    # configurable per project; default 3. Manager re-escalates on expiry.
  transition_reescalation_count: 0  # incremented by manager T2 on each missed expiry; auto-pauses at 3
```

## Last Pass

```yaml
last_pass:
  date: ""
  objective: ""
  output_files: []
  validation_passed: true   # did output meet pass_output_criteria?
  weak_pass: false           # true if all 4 value tests failed
```

## Next Pass

```yaml
next_pass:
  objective: ""           # one sentence — what will be done
  tools_required: []      # from TOOL-STATUS.md
  output_files_expected: []
  model_tier: "standard"  # lightweight | standard | heavy
                          # lightweight: state checks, file reads, log writes (gpt-4o-mini)
                          # standard: research, writing, ETL passes (gpt-5.3-codex / gpt-5.2)
                          # heavy: planning, synthesis, adversarial review (best available GPT)
                          # RATE LIMIT: if 429 hit, downgrade to standard for next pass
  pass_type: ""           # execution | research-discovery | research-depth | research-synthesis | idle
                          # execution: ETL, file work, data pipeline, scripting
                          # research-discovery: 8-10 searches, broad signal scan (see OPS-KNOWLEDGE-EXECUTION.md)
                          # research-depth: 4-6 searches, deep dive on 2-3 signals from prior discovery pass
                          # research-synthesis: no new searches, synthesize prior pass outputs into ranked artifact
                          # idle: no active project; see OPS-IDLE-CYCLE.md
                          # SEARCH BUDGET: discovery=8-10 queries, depth=4-6 queries, synthesis=0 queries
```

## Open Questions
<!-- Questions requiring human judgment. Move answered ones to Decision Log. -->
<!-- Leave blank if none. -->

## Blockers

| Blocker | Best path if unblocked | Fallback in use | Quality degradation |
|---|---|---|---|
| | | | |

## Decision Log
<!-- Append-only. -->

| Date | Decision | Rationale | By |
|---|---|---|---|
| | | | |

## Phase History
<!-- Append-only. -->

```yaml
phase_history:
  - name: ""
    started: ""
    completed: ""
    scheduler_deleted: false
    artifacts: []
```

## Resume Template
<!-- FAST-PATH: Cron workers read THIS SECTION ONLY first. Full file only if ambiguous. -->
<!-- Update before ending EVERY pass. Keep under 8 lines. -->

```
Project: [NAME] | Phase: [phase.name] | Status: [active/blocked/complete]
Last pass: [YYYY-MM-DD] — [one sentence: what was done]
Next pass: [next_pass.objective — one sentence]
Tools needed: [comma-separated from TOOL-STATUS.md]
Output expected: [filename(s)]
Blocker: [none | description]
LONGRUNNER: PROJECTS/[slug]/LONGRUNNER.md
```

---

# APPENDIX (fill as needed — not required to start)

## Tools for This Project

| Tool | Status | Approval? | Notes |
|---|---|---|---|
| Web Search | CONSTRAINED | No | Max 10–15 searches/session |
| OpenAI Model | AVAILABLE | No | Use intentionally — batch high-token tasks |
| File System | AVAILABLE | Destructive: YES | `trash` > `rm` |
| Python | AVAILABLE | External calls: YES | Write intermediate outputs to dated files |
| SQLite/DuckDB | AVAILABLE | No | Local SQL, no setup needed |
| Git | AVAILABLE | Push to remote: YES | Only commit to repos {OWNER} owns |
| Browser/fetch | AVAILABLE | Form submit: YES | Use static fetch first; headless only if needed |
| {EXAMPLE_API} | CONDITIONAL | No (free public) | Free key at eia.gov/opendata |
| SQL (Oracle) | UNVERIFIED | YES | Confirm connectivity + legality first |
| Embedding Search | UNAVAILABLE | — | Future; use OpenAI proxy until available |

## Inputs
- `[path or URL]` — [what it provides]

## Outputs
- `[path]` — [what it is]

## Knowledge Leverage
<!-- Check these BEFORE starting any research or script pass — do not rediscover what is known -->
- [ ] `OPS-KNOWLEDGE-EXECUTION.md` → System Registry → [system name if applicable]
- [ ] `/[knowledge-repo]/07-index/index.md` — scan for domain matches before researching
- [ ] Prior session artifacts in `PROJECTS/[slug]/` — read before running new searches

## Pass Output Criteria (standing)
<!-- These apply to every pass unless overridden in next_pass -->

```yaml
standing_output_criteria:
  - no fabricated URLs — all URLs real or marked [SPECULATIVE]
  - evidence sections append-only — never overwrite
  - metadata.updated_at reflects today's date
```

## Per-Pass Output Criteria (override as needed)

```yaml
pass_output_criteria:
  - type: file_exists
    path: "[dated output file]"
  - type: row_count
    file: "[log file]"
    min_new_rows: 1
  - type: field_present
    file: "[output file]"
    field: "## [required section header]"
  - type: schema_match
    file: "[CSV output]"
    required_columns: ["col1", "col2", "col3"]
  - type: no_regression
    file: "[append-only log]"
    note: "new row count must be >= prior row count"
```

## Project Folder Structure

```
PROJECTS/[slug]/
├── LONGRUNNER.md           ← this file
├── inbox/                  ← unrouted inputs (process before each pass)
├── outputs/                ← final artifacts + evidence-log.md
├── lanes/                  ← parallel lane subdirs (if running multiple workers on sub-tasks)
│   ├── [lane-a]/LONGRUNNER.md
│   └── [lane-b]/LONGRUNNER.md
└── completed/              ← archived phase artifacts
    └── [phase-slug]/
```

## Manager Review Notes
<!-- Append after each manager review -->

| Date | Outcome | Rationale |
|---|---|---|
| | continue / stop / pivot | |
