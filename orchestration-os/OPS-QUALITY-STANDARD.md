# OPS-QUALITY-STANDARD.md
<!-- Independent quality rubric + manager value methodology. -->
<!-- Workers use pass_output_criteria to define what to produce. -->
<!-- This file defines what makes output good enough to be worth keeping. -->

---

## Why This File Exists

pass_output_criteria in a LONGRUNNER is written by the same agent that executes the pass.
That's circular — an agent defining and grading its own exam. It catches obvious failures
but misses the deeper question: is this output genuinely valuable to {OWNER}?

This file provides an external standard. It doesn't replace pass_output_criteria — that
still governs whether the pass technically completed. This governs whether the output
is worth {OWNER}'s time to read.

---

## The Three-Question Quality Test

Apply this after every pass before writing the validation result. All three must pass.

### Q1 — The Expert Test
> Would a domain expert in this field find this output useful, surprising, or actionable?

A domain expert knows the obvious things. If your output only contains things a domain
expert already knows, it has zero marginal value.

**Passes if:** The output contains at least one specific finding, connection, or
recommendation that is non-obvious — i.e., it required actual research, synthesis, or
reasoning to produce, not just retrieval.

**Fails if:** The output is a summary of publicly available general knowledge with no
specific application to {OWNER}'s actual situation, project, or opportunity.

### Q2 — The Durable Asset Test
> Will this output be useful in 30 days, or does it expire with today's context?

Work that only makes sense right now (e.g., "the data source website was slow today") is noise.
Work that compounds (e.g., "data source vintage comparison logic that can be reused for
future vintages") is signal.

**Passes if:** The output produces at least one durable artifact — a ranked list,
a schema, a validated finding, a reusable script, a field map, a decision — that
will be directly usable in a future pass.

**Fails if:** The output is a log of activity with no reusable artifact attached.
"I researched X and found some things" is not a durable asset. "I produced
[filename]-[date].md with [specific contents]" is.

### Q3 — The Compounding Test
> Does this output make the NEXT pass faster, smarter, or higher-leverage?

Autonomous systems that compound get dramatically better over time. Systems that don't
compound just spin.

**Passes if:** The LONGRUNNER next_pass is more specifically scoped after this pass
than before it. Or: an OPS file was updated with a finding that improves future passes.
Or: a tool, script, or field map was produced that reduces the effort of a future pass.

**Fails if:** The next_pass after this pass is exactly as uncertain or as broad as it
was before. The pass consumed tokens but produced no leverage.

---

## Quality Result Reporting

After running the three-question test, write the result in the LONGRUNNER `last_pass`:

```
quality_check:
  expert_test: PASS | FAIL | (one sentence on what specific non-obvious finding justified PASS or caused FAIL)
  durable_asset_test: PASS | FAIL | (name the specific artifact produced, or explain the failure)
  compounding_test: PASS | FAIL | (what specifically is now faster/smarter, or why nothing compounded)
  overall: STRONG | ADEQUATE | WEAK | FAIL
    STRONG  = all three pass, at least one is genuinely impressive
    ADEQUATE = all three pass minimally
    WEAK    = one test fails; proceed but flag to manager
    FAIL    = two or more tests fail; do NOT mark pass as complete; set next_pass to retry
```

---

## Quality vs. Completion

These are different things.

| pass_output_criteria | quality_check | What to do |
|---------------------|--------------|------------|
| PASS | STRONG | Excellent. Proceed normally. |
| PASS | ADEQUATE | Good. Proceed. |
| PASS | WEAK | Note it. Proceed, flag to manager. |
| PASS | FAIL | File downloaded but useless. Retry with different approach. |
| FAIL | any | Technical failure. Retry per existing protocol. |

A pass that technically completes but fails quality is a waste of tokens. The system
must be able to recognize this and self-correct rather than accumulating low-quality
artifacts over many passes.

---

## The Calibration Question

When unsure whether an output passes the expert test, ask:

> "If I showed this to {OWNER} right now and said 'here's what I found' — would he say
> 'interesting, I didn't know that' or would he say 'yeah I could have Googled that'?"

If the honest answer is the second: FAIL. Retry with a sharper approach.

---

## Domain-Specific Quality Bars

Add domain-specific quality bars for each active project type. Template:

### [Project Type] ([project-slug] project)
- Expert test minimum: [what counts as non-obvious for this domain]
- Durable asset minimum: [what artifact must be produced]
- Compounding minimum: [what must be improved for future passes]
- Noise filter: [what types of results do NOT qualify as signals]

---

## What the Manager Checks

The manager pass (CRON-MANAGER-PROMPT.md) should spot-check quality_check results from
recent worker passes. Specifically:

- Are any projects accumulating consecutive WEAK or FAIL quality results?
  If yes: the next_pass objective needs to be rewritten. Surface to {OWNER}.
- Is any project consistently producing STRONG results?
  If yes: consider whether the phase stop condition should be tightened — strong output
  often means the system is ready to advance faster than planned.
- Are durable assets actually durable? Read one at random from each project and apply Q1.
  If it fails Q1 on re-read: the project's quality calibration is too lenient.

---

## Manager Value Methodology

Four-question value test applied by manager T4 to each project with new activity.

For each project pass under review, answer these four questions:

1. **Uncertainty reduction:** Did this pass reduce meaningful uncertainty about the problem, market, or solution? (Not just producing output — producing output that changes what should be done next.)
2. **Durable asset:** Did this pass produce a reusable artifact — a file, a script, a dataset, a model — that compounds value across future passes?
3. **Decision improvement:** Does this output improve a human decision that matters? ({OWNER}'s next action, a buyer's understanding, a product direction.)
4. **OS improvement:** Did this pass improve the operating system itself — a new constraint, a new pattern, a new quality calibration?

**Scoring:**
- STRONG: 3–4 questions YES
- ADEQUATE: 1–2 questions YES
- WEAK: 0 questions YES (surface to NOTIFICATIONS.md)
- FAIL: output does not exist or does not match pass_output_criteria (retry required)

A project where consecutive passes score WEAK or FAIL requires manager direction change (T5).

---

## T7 OS Improvement Gate

The worker T7 step surfaces OS improvement candidates — behavioral lessons, novel failure
modes, edge cases discovered during a pass. Not every observation qualifies. Apply both
gates before writing to any OS file:

**G1 — Non-obvious:** Would a competent agent who has read all OPS files already know this?
If yes: skip. If no: continue to G2.

**G2 — Generalizable:** Does this apply beyond the current project or pass?
If no: one-line note in daily memory only. If yes: write to the appropriate OS file
(AGENTS-LESSONS.md for behavioral lessons, OPS-FAILURE-MODES.md for failure modes,
OPS-QUALITY-STANDARD.md for quality calibration patterns, etc.)

**Both gates must pass for an OS file write.** Either gate failing means memory-only.

This gate replaces the prior "None honest → FM-[next]" pattern, which incentivized
noise writes. Under the gate pattern, the correct T7 output when nothing qualifies is:
"no OS improvement this pass" — no penalty, no forced entry.
