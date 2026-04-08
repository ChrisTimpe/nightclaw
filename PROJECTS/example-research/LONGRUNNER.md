# LONGRUNNER — Example Research Project
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- EXAMPLE ONLY — This project is provided as a reference for new users.  -->
<!-- It demonstrates a correctly filled-in LONGRUNNER for a research project. -->
<!-- To use NightClaw with this project: add a row to ACTIVE-PROJECTS.md.    -->
<!-- As shipped, this file has NO effect on the running system.               -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

---

# CORE

## Mission
Map the current landscape of AI-powered personal productivity tools — covering note-taking, writing assistants, email management, and scheduling — and produce a ranked comparison guide with honest trade-offs, good enough for someone to decide which tools to adopt for their daily workflow.

## Conflict Check
- Domain: AI tool research / consumer productivity
- Conflict risk: low
- [x] Confirmed: not in prohibited domain

## Current Phase

```yaml
phase:
  name: "exploration"
  objective: "Identify 3-4 candidate tools per category (note-taking, writing, email, scheduling) through web research and user community signal. No ranking yet — just discovery with basic facts per candidate."
  stop_condition: "A dated discovery file exists with at least 12 tools across 4 categories, each with: name, URL, pricing model, key AI feature, and one sentence on real-world user sentiment. No fabricated URLs."
  started: "2026-04-07"
  schedulers: []    # empty on fresh install — worker creates this on first pass
  successor: "adversarial-challenge"
  status: "active"
  transition_triggered_at: ~
  transition_expires: ~
  transition_timeout_days: 3
  transition_reescalation_count: 0
```

## Last Pass

```yaml
last_pass:
  date: ""
  objective: ""
  output_files: []
  validation_passed: false
  weak_pass: false
```

## Next Pass

```yaml
next_pass:
  objective: "Run 8-10 targeted web searches to discover 3-4 AI productivity tools per category (note-taking, writing, email, scheduling). Write findings to PROJECTS/example-research/outputs/ai-productivity-discovery-[date].md. Each entry: name, URL, pricing, key AI feature, one sentence on user sentiment from reviews or forums. Min 12 tools total across 4 categories."
  tools_required: ["web_search", "file_system"]
  output_files_expected: ["PROJECTS/example-research/outputs/ai-productivity-discovery-YYYY-MM-DD.md"]
  model_tier: "standard"
  pass_type: "research-discovery"
```

## Open Questions
- Should this include tools that are AI-augmented (e.g., Notion AI) or AI-native only (e.g., built from the ground up around AI)?
- Priority category: which of the four matters most for the target user's workflow?

## Blockers

| Blocker | Best path if unblocked | Fallback in use | Quality degradation |
|---|---|---|---|
| | | | |

## Decision Log

| Date | Decision | Rationale | By |
|---|---|---|---|
| 2026-04-07 | Scope to AI-native or deeply AI-augmented tools only — generic productivity tools without meaningful AI differentiation are out of scope for Phase 1 | Keeps comparison focused on what makes these tools different from pre-AI alternatives | {OWNER} |

## Phase History

```yaml
phase_history:
  - name: ""
    started: ""
    completed: ""
    scheduler_deleted: false
    artifacts: []
```

## Resume Template
<!-- FAST-PATH: Cron workers read THIS SECTION ONLY first. -->

```
Project: AI Productivity Tools Research | Phase: exploration | Status: active
Last pass: — (not yet run)
Next pass: Web research — 12+ AI productivity tools across 4 categories to outputs/ai-productivity-discovery-[date].md
Tools needed: web_search, file_system
Output expected: PROJECTS/example-research/outputs/ai-productivity-discovery-YYYY-MM-DD.md
Blocker: none
LONGRUNNER: PROJECTS/example-research/LONGRUNNER.md
```

---

# APPENDIX

## Tools for This Project

| Tool | Status | Approval? | Notes |
|---|---|---|---|
| Web Search | CONSTRAINED | No | Max 10–15 searches/session — use budget wisely |
| File System | AVAILABLE | Destructive: YES | Write outputs to PROJECTS/example-research/outputs/ |
| Python | AVAILABLE | No | For any data processing or formatting if needed |

## Inputs
- Web search results from targeted queries
- Product pages, review sites (G2, Product Hunt, Reddit), and community forums

## Outputs
- `PROJECTS/example-research/outputs/ai-productivity-discovery-YYYY-MM-DD.md` — discovery list
- `PROJECTS/example-research/outputs/ai-productivity-shortlist-YYYY-MM-DD.md` — ranked guide (Phase 2)

## Knowledge Leverage
- [ ] `OPS-KNOWLEDGE-EXECUTION.md` → Web Research Workflow section — follow query formulation discipline
- [ ] Prior session artifacts in `PROJECTS/example-research/` — read before running new searches

## Pass Output Criteria (standing)

```yaml
standing_output_criteria:
  - no fabricated URLs — all URLs real or marked [SPECULATIVE]
  - evidence sections append-only — never overwrite prior findings
  - each artifact dated in filename
```

## Per-Pass Output Criteria

```yaml
pass_output_criteria:
  - type: file_exists
    path: "PROJECTS/example-research/outputs/ai-productivity-discovery-YYYY-MM-DD.md"
  - type: row_count
    file: "PROJECTS/example-research/outputs/ai-productivity-discovery-YYYY-MM-DD.md"
    min_new_rows: 12
  - type: field_present
    file: "PROJECTS/example-research/outputs/ai-productivity-discovery-YYYY-MM-DD.md"
    field: "## Candidates"
```

## Project Folder Structure

```
PROJECTS/example-research/
├── LONGRUNNER.md           ← this file (EXAMPLE ONLY)
└── outputs/                ← artifacts written by agent passes
```

## Manager Review Notes

| Date | Outcome | Rationale |
|---|---|---|
| | continue / stop / pivot | |
