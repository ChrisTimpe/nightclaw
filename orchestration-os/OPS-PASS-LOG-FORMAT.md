# OPS-PASS-LOG-FORMAT.md
<!-- Defines the structured format for daily memory log entries. -->
<!-- Every worker and manager pass writes one entry per this format. -->
<!-- Replaces freeform prose in memory/YYYY-MM-DD.md for machine-parseable context. -->

## Why Format Matters

The daily memory log (`memory/YYYY-MM-DD.md`) is read at the start of every session and by manager passes to understand recent context. Freeform prose requires the model to parse narrative to extract facts. Structured entries let the next pass extract the critical fields (project, objective, output, value verdict) in ~100 tokens instead of ~400.

---

## Standard Entry Format

Every pass appends one entry to `memory/YYYY-MM-DD.md` in this format:

```
---
[WORKER | MANAGER | IDLE] | [timestamp] | Project: [slug or "general"]
Objective: [the next_pass objective that was executed — one sentence]
Output: [files written, rows appended, decisions made — be specific]
Validation: PASS | PARTIAL | FAIL
Value: STRONG | WEAK | NONE
If WEAK or NONE: [one sentence — why, and what next_pass will change]
Signals routed: [none | N signals → [knowledge-repo]/00-inbox/]
OS update: [none | what was updated in which OPS file]
---
```

---

## Examples

**Strong worker pass:**
```
---
[WORKER] | 2026-04-02 14:23 | Project: [project-slug]
Objective: Download two [external-data-source] vintages (2025-09, 2025-10) and run diff script
Output: eia860m-diff-2026-04-02.csv (847 rows), diff-summary-2026-04-02.md written
Validation: PASS
Value: STRONG
Signals routed: none
OS update: OPS-KNOWLEDGE-EXECUTION.md — added note: [data-source] bulk download rate limit is 10 req/min for ZIP files
---
```

**Weak pass flagged correctly:**
```
---
[WORKER] | 2026-04-02 16:45 | Project: [project-slug]
Objective: Validate diff output against known generator IDs from [data-source]-860 2025-09
Output: validation-notes-2026-04-02.md (stub only — [data-source]-860 2025-09 ZIP URL returned 404)
Validation: FAIL
Value: NONE
If NONE: URL structure changed. Next pass: re-run link discovery against [data-source] detail-data.php. Tool: static fetch (AVAILABLE).
Signals routed: none
OS update: OPS-FAILURE-MODES.md — added FM-007: [data-source] raw file URLs stale after 90 days, require re-discovery
---
```

**Idle cycle pass:**
```
---
[IDLE] | 2026-04-02 03:00 | Project: general
Objective: Opportunity-intel inbox scan + demand signal search
Output: 2 inbox files routed (nursing-home-cms-data.md → 02-opportunities, banking-branch-closure-signal.md → 04-demand-signals); 1 new demand signal appended to demand-log.md
Validation: PASS
Value: STRONG
Signals routed: n/a (this pass IS the signal processing)
OS update: none
---
```

**Manager pass with change detection skip:**
```
---
[MANAGER] | 2026-04-02 15:00 | Project: all
Objective: Manager review cycle
Output: No new worker activity since last review (14:23). Deep review skipped.
Validation: PASS
Value: NONE (correct — system current, nothing to review)
Signals routed: none
OS update: none
---
```

---

## Migration Note

Existing freeform entries in `memory/` files are valid and should not be rewritten. The structured format applies to all new entries going forward. The manager dream pass (Tier 3a in OPS-IDLE-CYCLE.md) will consolidate old freeform entries into MEMORY.md summaries over time, naturally transitioning the log to structured-only.

---

## Parser Hint for Future Passes

When reading `memory/YYYY-MM-DD.md` to understand recent context, extract these fields per entry:
- `Project:` — which project was active
- `Objective:` — what was attempted
- `Validation:` — did it succeed
- `Value:` — was it worth running
- `OS update:` — what the system learned

Skip prose between entries. The structured fields are sufficient for pass-to-pass context continuity. This reduces the effective token cost of reading recent memory by approximately 60% compared to parsing freeform prose.
