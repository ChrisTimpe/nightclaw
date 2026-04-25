# CURRENT-PASS.md

<!--
Handoff-state surface. This file is the only place in the repo where open
issues and active-work pointers live. When a fresh LLM needs to know "what
should I be aware of before editing," this is the file to read.

Discipline: append to "Known issues" when a live footgun is identified;
remove entries when they are fixed. Do not turn this file into a journal.
The repo is the source of truth for what the system IS; this file is the
source of truth for what requires attention RIGHT NOW.
-->

## Active pass

None. Repo is in handoff-grade state.

---

## Known issues

None. 377 passed / 1 skipped / 0 failed as of 2026-04-25. All 5 gates pass (integrity-check 11/11, scr-verify RESULT:PASS, validate-bundles 8/8, schema-sync NOOP, schema-lint OK).

---

## Pointers

* Six non-negotiables: enumerated in the general bootstrap track ("Six
  non-negotiables" section) and in `review_pr`.
* Gate sequence: `pytest -x -q`, then each of the `scripts/nightclaw-
  ops.py` gates — see the `gate_sequence` resolver output.
* Cron critical path: `orchestration-os/CRON-WORKER-PROMPT.md` and
  `orchestration-os/CRON-MANAGER-PROMPT.md` are authoritative; read
  `orchestration-os/CRON-HARDLINES.md` before any cron-session edit.
* Invariant catalog: `python3 scripts/nightclaw-ops.py bootstrap
  --track=general` renders the live catalog from tests/ annotations and
  `orchestration-os/schema/scr_rules.yaml`.
