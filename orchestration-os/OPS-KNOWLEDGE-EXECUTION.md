# OPS-KNOWLEDGE-EXECUTION.md — Skill Layer (Part 2 of 2)

<!-- ═══════════════════════════════════════════════════════════════════════════════ -->
<!-- PART 2 OF THE NIGHTCLAW TWO-PART SYSTEM                                        -->
<!-- Part 1: The orchestration framework (SOUL, AGENTS, cron protocols, audit trail) -->
<!-- Part 2: THIS FILE — domain execution knowledge attached as a replaceable skill  -->
<!-- ═══════════════════════════════════════════════════════════════════════════════ -->

<!-- Maintained by: Human ({OWNER}) on structural changes; Agent on extension after successful runs -->
<!-- Read at: before writing any script for a known system; before any ETL pass involving registered data sources -->

> **SKILL LAYER — REPLACEABLE PER DEPLOYMENT**
> This file demonstrates the skill-attachment pattern: domain-specific execution knowledge
> (field maps, API patterns, schema quirks) encoded in a structured file the agent reads
> before writing any code. Replace the examples below with field maps for your own systems.
> The pattern — not the examples — is what you are adopting.

---

## Purpose

When an agent generates code for an unfamiliar system from scratch, it produces plausible-looking scripts that fail on real data. Column names are guessed. Auth flows are invented. Date formats are assumed to be strings when they are stored as integers. Pagination is either omitted or wired to the wrong offset parameter. The script runs, returns no errors, and produces garbage. Debugging this takes longer than writing the script correctly the first time would have — and the next run faces the same wall because nothing was learned. This file breaks that cycle. It contains the accumulated field maps, auth patterns, endpoint signatures, and quirk notes for every system {OWNER} regularly works with. Before writing any script for a registered system, the agent reads the relevant section of this file and starts from confirmed knowledge, not from inference.

Knowledge-informed execution also has a compounding return. Each successful run is an opportunity to update this file with what was actually observed: which columns were null in practice, which API endpoints returned unexpected shapes, which data source had renamed or rearranged columns. Over time, the file becomes a reliable ground truth that reduces the failure rate of first-pass scripts toward zero. An agent that writes from this file and then extends it is operating in a learning loop. An agent that ignores this file and generates from general training data is operating at a flat error rate — it never improves no matter how many runs it completes. This file is the difference between an agent that gets smarter over time and one that merely gets more active.

---

## How to Use This File

- **When to read it:** Read the relevant section of this file before writing any script, query, or pipeline that touches a registered system. If the system name appears in the System Registry table, this file has a field map for it. Do not write code for that system without consulting the map first. A quick scan of the field map takes 30 seconds; a debugging session from a wrong column name takes 30 minutes.

- **How to reference a field map:** Locate the system by name in the System Registry table. The `Field Map File Reference` column points to the section in this file (e.g., `#field-map-my-system`). Navigate to that section. Read the column table and the Known Quirks block before writing any code. Use the exact logical names, physical column names, and data types listed — do not substitute from general knowledge or documentation that may be outdated.

- **How to extend this file after a successful run:** After any run that produced validated output from a registered system, append observations to the relevant field map. Specifically: if any column behaved differently than documented (unexpected nulls, different data type in practice, renamed header), update the column row and add a dated note. If a new quirk was discovered, add it to the Known Quirks block. If a new endpoint or subject area was used, add it. Then confirm the script template is still current. Mark the update with a comment `<!-- updated YYYY-MM-DD: [brief description] -->`.

- **How to flag a gap:** If a system is needed but not registered, do not generate a script from general knowledge. Instead: (1) add a placeholder row to the System Registry with status `UNVERIFIED`, (2) write a note to `/00-inbox/knowledge-gaps.md` naming the system and what is needed, (3) surface the gap to {OWNER} before starting the run. A script built on unverified field assumptions may succeed silently on small test data and fail on production volumes — always register first.

---

## System Registry

| System Name | Type | Auth Method | Data Format | Primary Use Case | Field Map Reference |
|---|---|---|---|---|---|
| Python/pandas local ETL | Local script execution (Ubuntu-sandbox) | N/A (local) | CSV, XLSX, Parquet | Data normalization, diffing, transformation, validation pipelines | [#script-template-pythonpandas-pipeline-pattern](#script-template-pythonpandas-pipeline-pattern) |
| DuckDuckGo Search | Web search (via agent tool) | None (tool-based) | Text snippets | Signal discovery, URL retrieval, lightweight fact-checking | [#web-research-workflow](#web-research-workflow) |
| Static Page Fetch | Direct URL fetch (no JS) | None | HTML/text | Full article text, landing page content, data file links | [#web-research-workflow](#web-research-workflow) |
| OpenAI API | LLM REST API | API key via Authorization header | JSON (chat completions) | Summarization, classification, schema validation, opportunity ranking | See OPS-TOOL-REGISTRY.md §2 |

---

## Web Research Workflow

This section gives the complete executable protocol for autonomous web research passes.
The tool exists. This is how to use it well.

### Invocation (OpenClaw)

In OpenClaw, web search is a native agent tool. Invoke it as:
```
search_web(query="[your query]")         # returns snippets + URLs
fetch_url(url="https://...")             # fetches full page text (no JS)
```
Search returns: title, URL, snippet (~150-300 chars). It does NOT return full content.
Fetch returns: full page text. Use when a snippet is insufficient to extract the finding.

For JavaScript-rendered pages (SPA sites, dynamic dashboards), fetch will return empty
or a JS shell. Use Playwright (UNVERIFIED — confirm `playwright install chromium` first).

---

### Budget Rule

Hard limit: ~10–15 searches per session (OpenClaw/DuckDuckGo constraint).
Per research pass, budget as follows:

| Pass type | Search budget | Fetch budget |
|-----------|--------------|-------------|
| Signal discovery (broad scan) | 8–10 queries | 3–5 fetches (priority URLs only) |
| Targeted deep-dive (one topic) | 4–6 queries | 5–8 fetches |
| Fact-check / validation | 2–3 queries | 1–2 fetches |

Track usage in the pass log. If approaching limit mid-pass: stop searching, process
what you have, queue remaining queries to `[knowledge-repo]/00-inbox/search-retry-queue.md`.
Format: one query per line with context: `[query] | [why needed] | [queued: YYYY-MM-DD]`

---

### Query Formulation Discipline

**Start specific, expand if needed. Never start broad.**

Bad (too broad — burns a query slot on noise):
```
"project management software"
"data engineering jobs"
```

Good (specific signal with intent):
```
"open source project management tools comparison 2026"
"devops platform engineer contract remote linkedin"
"[tool-name] API breaking changes 2026"
```

**Query construction rules:**
1. Include the domain/vertical explicitly ("healthcare", "manufacturing", "SLED")
2. Include signal type ("RFP", "job posting", "vendor announcement", "conference")
3. Include year when recency matters ("2026", "Q1 2026")
4. Use `site:` operator for targeted sources (sam.gov for federal RFPs, linkedin.com for roles)
5. One concept per query — don't AND multiple unrelated terms
6. If first query returns irrelevant results: narrow one variable, don't abandon and rewrite entirely

---

### Result Triage (snippet vs. fetch decision)

After getting search results:

```
For each result:
  Does the snippet contain the actual finding I need?
    YES → extract finding from snippet, record URL as source, no fetch needed
    NO  → Is this URL likely to contain the finding?
            YES + high-value → fetch the URL
            YES + medium-value → queue to search-retry-queue.md for next pass
            NO → discard
```

Fetch priority order (highest value per token spent):
1. Government procurement pages (sam.gov, state RFP portals) — full text needed
2. Job postings with specific technical requirements — full text needed
3. Vendor pricing pages — full text needed
4. News articles about a specific event — snippet usually sufficient
5. Wikipedia / general reference — never fetch; use LLM knowledge instead

---

### Finding Storage Format

Every finding must be written to a dated file before the pass ends.
Never rely on session memory — findings that aren't written are lost.

**For [knowledge-repo] signals:**
```markdown
## [Signal title] — [YYYY-MM-DD]

**Source:** [URL]
**Signal type:** [RFP | job posting | vendor announcement | conference | news]
**Domain:** [healthcare | manufacturing | SLED | etc.]
**Summary:** [2-3 sentences — what it says and why it's relevant]
**Relevance to {OWNER}:** [one sentence — which opportunity niche this supports]
**Action:** [monitor | research further | add to opportunity file | discard]
```

Save to: `[knowledge-repo]/00-inbox/signal-[slug]-[YYYY-MM-DD].md`
The manager or next pass processes the inbox; the worker just collects.

**For research facts (project-specific):**
Save directly to the project directory as a dated finding file.
Always include the source URL inline — not in a separate references section.
Example: `The vendor API response shape changed in January 2026 ([vendor announcement](https://...))."`

---

### Citation Discipline

Every factual claim in a durable artifact must have a source URL. No exceptions.

- Inline citation: `[source description](URL)` immediately after the claim
- Not acceptable: "According to the vendor's documentation..." with no URL
- Not acceptable: a "Sources" section at the bottom with generic names
- If a finding came from a snippet with no full fetch: cite the search result URL anyway
- If a URL is behind a paywall or auth wall: note `[paywalled]` and cite what you could access

This matters because:
1. {OWNER} may want to verify the finding independently
2. Future passes may need to re-check whether the source has been updated
3. Artifacts without citations can't be audited — they're assertions, not intelligence

---

### Multi-Pass Research Strategy

One pass cannot fully research a topic. Structure research across passes:

**Pass 1 — Discovery:** 8-10 queries, broad signal scan, write all findings to 00-inbox/
Deliverable: `[slug]-discovery-[date].md` with 5-15 raw signals, each sourced

**Pass 2 — Depth:** 4-6 queries on the 2-3 highest-value signals from Pass 1
Deliverable: one expanded finding per signal with full fetch, evidence depth ≥ 3 sources

**Pass 3 — Synthesis:** No new searches. Read Pass 1 and 2 outputs.
Deliverable: ranked conclusions with confidence levels, gaps identified for future passes

**Do not try to do all three in one pass.** The 10-15 search budget and token limits
make this impossible without sacrificing quality on each stage.

Set `next_pass` in the LONGRUNNER to the appropriate next stage after each pass.

---

### What Search Cannot Do (Use LLM Instead)

- Synthesize across 10+ sources → use LLM summarization on fetched content
- Answer questions about recent events before its training cutoff → search first, fetch, then ask LLM
- Rank opportunities by fit → write findings to file, then run a separate LLM ranking pass
- Validate data accuracy → cross-reference with a second source, not model knowledge

---

## Script Template: Python/Pandas Pipeline Pattern

```python
#!/usr/bin/env python3
"""
Reusable pandas pipeline skeleton.
Adapt INPUT_FILE, KEY_COLS, EXPECTED_ROW_RANGE, and DTYPE_MAP per pipeline.
"""

import pandas as pd
from datetime import date

INPUT_FILE = "input_data.csv"
OUTPUT_FILE = f"pipeline-output-{date.today().isoformat()}.csv"
CHECKPOINT_FILE = f"pipeline-checkpoint-{date.today().isoformat()}.csv"
KEY_COLS = ["id", "name"]                     # Columns that must never be null — adapt per dataset
EXPECTED_ROW_RANGE = (1, 1_000_000)          # (min_rows, max_rows) — tune per dataset
DTYPE_MAP = {                                 # Explicit dtypes prevent silent coercion
    "id": str,
    "name": str,
    "amount": float,
    "status": str,
}

# --- Read ---
df = pd.read_csv(INPUT_FILE, dtype=DTYPE_MAP, low_memory=False)
rows_in = len(df)
print(f"Rows in: {rows_in}")

# --- Normalize column names ---
df.columns = [c.strip().lower().replace(" ", "_").replace("(", "").replace(")", "") for c in df.columns]

# --- Validate ---
validation_passed = True
for col in KEY_COLS:
    null_count = df[col].isna().sum()
    if null_count > 0:
        print(f"VALIDATION FAIL: {null_count} nulls in key column '{col}'")
        validation_passed = False

min_rows, max_rows = EXPECTED_ROW_RANGE
if not (min_rows <= rows_in <= max_rows):
    print(f"VALIDATION FAIL: row count {rows_in} outside expected range [{min_rows}, {max_rows}]")
    validation_passed = False

assert validation_passed, "Pipeline halted: validation failed. Check logs above."

# --- Write checkpoint ---
df.to_csv(CHECKPOINT_FILE, index=False)
print(f"Checkpoint written: {CHECKPOINT_FILE}")

# --- Transform (insert pipeline steps here) ---
df_out = df.copy()  # Replace with actual transformation logic

# --- Write output ---
rows_out = len(df_out)
df_out.to_csv(OUTPUT_FILE, index=False)
print(f"Rows out: {rows_out} | Validation: {'PASS' if validation_passed else 'FAIL'} | Output: {OUTPUT_FILE}")
```

---

## Extension Protocol

How to add a new system to this file after a successful run:

**1. Add row to System Registry**
Add a new row to the System Registry table with all six columns filled in: system name, type, auth method, data format, primary use case, and field map reference (anchor link to the new section). Use status `VERIFIED` implicitly by placing it in the table — only add if the system has been successfully queried at least once.

**2. Add Field Map section**
Add a new `## Field Map: {System Name}` section following the same structure as existing field maps: overview paragraph, auth block, column table (with logical name, data type, nullable, description, validation rule), and Known Quirks block. Use only observed values — do not fill in columns with assumed types. Mark uncertain fields with `[UNVERIFIED]` inline.

**3. Add or update Script Template**
If a new system was used with a reusable pattern (auth + fetch + write), add a `## Script Template: {System Name}` section with a working skeleton. If the new system was an extension of an existing system (e.g., a new endpoint in an already-registered API), update the existing field map rather than creating a new template. Mark all credential placeholders with `[REQUIRES: {ENV_VAR_NAME} env var]`.

**4. Note any quirks discovered during the run**
Append to the Known Quirks block of the relevant field map. Include: what was expected vs. what was observed, the vintage or date of the run where the quirk appeared, and the workaround applied. Format: numbered list item with a dated inline comment `<!-- observed YYYY-MM-DD -->`.

**5. Update OPS-TOOL-REGISTRY.md if new tool capabilities were confirmed**
If the run confirmed a previously UNVERIFIED tool (e.g., SQL connectivity, browser rendering), update its status in OPS-TOOL-REGISTRY.md from `UNVERIFIED` to `AVAILABLE` or `CONSTRAINED`, add the confirmed constraint details, and remove the `[UNVERIFIED]` tag from the notes field. Do this in the same session as the successful run — do not defer.

---

## Domain Failure Patterns

<!-- ═══════════════════════════════════════════════════════════════════════════════ -->
<!-- DOMAIN FAILURE PATTERNS — deployment-specific failure modes                   -->
<!-- These are NOT core NightClaw orchestration failures (those live in             -->
<!-- OPS-FAILURE-MODES.md). These are failure patterns tied to specific data        -->
<!-- sources, file formats, or external APIs that a particular deployment uses.     -->
<!--                                                                                -->
<!-- Format mirrors OPS-FAILURE-MODES.md for consistency.                           -->
<!-- MCP Upgrade Path: where an MCP connector would eliminate the root cause        -->
<!-- entirely, that path is documented alongside the tactical fix.                  -->
<!--                                                                                -->
<!-- Agent: append new domain-specific failure patterns here via T7c when           -->
<!-- encountered. If a pattern affects all NightClaw deployments regardless of      -->
<!-- domain, it belongs in OPS-FAILURE-MODES.md instead.                            -->
<!-- ═══════════════════════════════════════════════════════════════════════════════ -->

<!-- Deployment-specific domain failure patterns (DFM-001 through DFM-NNN) are added here
     by the operator during initial configuration. See comment block above for format.
     No entries ship with the public template — add your own as your deployment encounters them. -->
