# PROTOCOL-PROOF.md

_What NightClaw is, how this repo proves it, and what it does not claim. Principal-architect level, grounded in the current code and schema._

> **Scope of this document.** This is a human-facing proof artifact that explains the NightClaw protocol. It is **not** part of the operational R3 registry and is not routed. The protocol itself is R1–R7 plus the engine commands, gates, bundles, and audit behavior. Running `python3 scripts/nightclaw-ops.py registry-route PROTOCOL-PROOF.md` returns `ROUTE:UNKNOWN` by design — the file is explanatory doctrine, not an object governed by the protocol. When this document and the schema disagree, trust the schema.

## 0. The claim

**OpenClaw is the agent workspace platform; NightClaw is the sovereign protocol for autonomous work inside that workspace.** The protocol defines how an autonomous session may know, touch, mutate, audit, and carry forward state. It is *not* a replacement for probabilistic input surfaces (MCP connects tools and data; RAG retrieves context). It is the deterministic operation protocol that governs writes, dependencies, audits, and cross-session handoffs so those probabilistic surfaces can be used without the workspace trusting the model to remember anything.

Stated as code-true properties:

1. **The registry is machine-readable.** Seven sections — R1 objects, R2 field contracts, R3 routing, R4 edges, R5 bundles, R6 SCR rules, R7 change-log format — live as YAML under `orchestration-os/schema/` and are loaded into a typed `SchemaModel` at every engine command.
2. **Writes go through named transactions with declared preconditions.** The R5 bundle executor validates before mutating and emits audit rows automatically.
3. **Every field change is logged with two timestamps.** `audit/CHANGE-LOG.md` captures effective + recorded, enabling point-in-time reconstruction.
4. **Protected files cannot drift silently.** SHA-256 signed; `integrity-check` halts the next session on divergence.
5. **The catalog is queryable, not just declarative.** Agents (human or LLM) can ask the engine `registry-route`, `cascade-read`, `validate-field`, `validate-bundles` against the live in-memory model.

## 1. Live schema shape

The protocol's live shape is queryable by command; this document does not hard-code counts or fingerprints because they change with every deliberate schema edit. To see the current state, run:

```bash
python3 scripts/nightclaw-ops.py bootstrap --track=general
```

The `Repo summary` section of the bootstrap projection prints the live count of objects / fields / routes / edges / bundles / SCR rules and the schema fingerprint. Every schema-related claim in this document maps to a YAML file under `orchestration-os/schema/` and a command that reads it; §8 below lists the exact verifications.

Engine surface: `nightclaw_engine/commands/__init__.py::COMMANDS` registers every command; `STEP_CMD_MAP` in the same file records which T-tier each command emits as.

## 2. Concrete proof — one command, one bundle, one edge, one audit chain

The worker has just completed a project pass at T5 quality `STRONG`. At T6 it records the result through the R5 `longrunner_update` bundle.

**Invocation (exactly as cron worker issues it):**

```bash
python3 scripts/nightclaw-ops.py bundle-exec longrunner_update \
    slug=example-research \
    run_id=RUN-20260424-001 \
    quality=STRONG \
    objective="Normalize EIA-860M vintages to snapshot_860m rows" \
    output_files="PROJECTS/example-research/outputs/snapshot_860m.csv" \
    next_objective="Diff consecutive vintages and emit event feed" \
    model_tier=standard \
    context_budget=40000 \
    tools="file_system,web_search"
```

**R5 bundle spec the executor resolves (`orchestration-os/schema/bundles.yaml` lines 17-40):**

```yaml
- name: longrunner_update
  trigger: "T6 after pass completes (T5 PASS or WEAK)"
  args: [slug, run_id, quality, objective, output_files, next_objective,
         model_tier, context_budget, tools]
  validates:
    - "LONGRUNNER:{slug}.phase.status EQUALS ACTIVE"
    - "next_objective NOT_EMPTY"
    - "quality IN STRONG,ADEQUATE,WEAK,FAIL"
    - "model_tier IN lightweight,standard,heavy"
  writes:
    "LONGRUNNER:{slug}":
      last_pass.date:         "{TODAY}"
      last_pass.objective:    "{objective}"
      last_pass.output_files: "{output_files}"
      last_pass.quality:      "{quality}"
      next_pass.objective:    "{next_objective}"
      next_pass.model_tier:   "{model_tier}"
      next_pass.context_budget: "{context_budget}"
      next_pass.tools_required: "{tools}"
    "DISPATCH:{slug}":
      last_worker_pass: "{NOW}"
  append:
    "audit/AUDIT-LOG.md": "TASK:{run_id}.T6 | TYPE:BUNDLE | BUNDLE:longrunner_update | RESULT:SUCCESS"
  returns: SUCCESS
```

**What deterministically happens, in order:**

1. **R3 route check.** `nightclaw_engine.engine.gates.route_check("PROJECTS/example-research/LONGRUNNER.md", "BUNDLE:longrunner_update")` matches the glob row `PROJECTS/*/LONGRUNNER.md STANDARD BUNDLE:longrunner_update`. Route OK. Same check for `ACTIVE-PROJECTS.md`. CL5 protected-file check runs on both targets; both pass (neither is in `protected.yaml`).
2. **Precondition evaluation.** All four `validates` expressions are executed. `quality IN STRONG,ADEQUATE,WEAK,FAIL` → STRONG is in set. `model_tier IN lightweight,standard,heavy` → standard is in set. `next_objective NOT_EMPTY` → non-empty. `LONGRUNNER.phase.status EQUALS ACTIVE` → resolved against the current project YAML. **If any one fails, no write is emitted.**
3. **Atomic writes.** The two target files are mutated per the `writes` block, with `{NOW}` / `{TODAY}` expanded by the executor (not the LLM).
4. **Automatic change-log emission.** For every `(target, field, old, new)` where `old != new`, a typed row is appended to `audit/CHANGE-LOG.md` with the effective timestamp (when the value applies) and the recorded timestamp (when it was written). Nine fields change in this call, so nine rows are emitted.
5. **R4 cascade-check emission.** For every target the bundle wrote, `cascade_for(target)` is queried and a `FILE:<src>#CASCADE_CHECK|<edge-type>|<edge-target>|worker|<run_id>|<ts>|<ts>|bundle-longrunner_update|BUNDLE:longrunner_update` row is appended to `CHANGE-LOG.md` for every R4 edge. For `PROJECTS/example-research/LONGRUNNER.md` (after the 2026-04-24 glob-aware matcher patch), three outgoing edges exist — so three CASCADE_CHECK rows are emitted, documenting that the write is known to affect `ACTIVE-PROJECTS.md`, `audit/CHANGE-LOG.md`, and `MODEL-TIERS.md`.
6. **TASK append.** `TASK:RUN-20260424-001.T6 | TYPE:BUNDLE | BUNDLE:longrunner_update | RESULT:SUCCESS` is appended to `audit/AUDIT-LOG.md`.
7. **Return.** `SUCCESS` printed on stdout; exit code 0.

Every step above is executed by code in `nightclaw_engine/commands/bundle.py` and `bundle_mutators.py`. The LLM supplied the arg values; the LLM did not compose the writes, compute the timestamps, pick the target paths, or format the audit rows.

**The complete R4 edge set for this bundle (`orchestration-os/schema/edges.yaml:10,17-20`):**

```
ACTIVE-PROJECTS.md                TRIGGERS    BUNDLE:longrunner_update
BUNDLE:longrunner_update          WRITES      PROJECTS/*/LONGRUNNER.md
BUNDLE:longrunner_update          WRITES      ACTIVE-PROJECTS.md
BUNDLE:longrunner_update          WRITES      audit/CHANGE-LOG.md
BUNDLE:longrunner_update          WRITES      audit/AUDIT-LOG.md
```

The trigger edge is how a future reader asks "what can cause `ACTIVE-PROJECTS.md` updates?" and gets a typed answer from the graph. The four WRITES edges are how the reader asks "when does `audit/AUDIT-LOG.md` get written?" and gets six bundle-source rows back from `cascade_upstream("audit/AUDIT-LOG.md")` without reading a single prose document.

## 3. Validation surface

Run from the repo root to verify the protocol is internally consistent:

```
pytest tests/ -q                                       → all tests pass
python3 scripts/nightclaw-ops.py schema-lint           → SCHEMA-LINT:OK:<fingerprint>
python3 scripts/nightclaw-ops.py schema-sync           → SCHEMA-SYNC:NOOP:<fingerprint>:SECTIONS=7
python3 scripts/nightclaw-ops.py scr-verify            → RESULT:PASS   (SCR-01..11 + CL5)
python3 scripts/nightclaw-ops.py validate-bundles      → RESULT:PASS
python3 scripts/nightclaw-ops.py integrity-check       → RESULT:PASS files=11
python3 scripts/skills-sync.py                         → OK
```

Exact counts and fingerprint are intentionally not pinned in this document — they change with every deliberate schema edit. The `OK` / `NOOP` / `PASS` / `RESULT:PASS` shapes are the stable contracts.

Plus — end-to-end install/smoke against a disposable zip of the patched working tree (no real credentials, no real model IDs, placeholders preserved):

```
bash scripts/smoke-test.sh <patched-tree-zip>          → 18 passed, 0 failed, 3 warnings
```

The smoke test exercises: extract → install.sh → 11/11 initial integrity → SOUL.md edit + resign → USER.md edit + resign → OPS-PREAPPROVAL.md edit + resign → validate.sh → new-project.sh → T0 integrity simulation → LOCK.md state. Every stage produces a machine-parseable pass/fail line.

## 4. Inter-tier consistency — what SCR enforces in CI

The protocol's internal consistency is enforced by 11 predicates (`orchestration-os/schema/scr_rules.yaml`) evaluated in every `scr-verify` run. The three most load-bearing:

- **SCR-09** `prompt_bundle_args_match_r5` (HIGH) — for every `Execute: bundle-exec <name>` in the cron prompts, every arg name must appear in `bundles.yaml:<name>.args`. This is what makes the prompt ↔ bundle boundary typed.
- **SCR-03** `r3_protected_files_are_in_manifest` (CRITICAL) — every R3 row with `tier=PROTECTED` must appear in `audit/INTEGRITY-MANIFEST.md`. Closes the gap between "declared as protected" and "actually hash-verified at session start."
- **SCR-10** `code_files_have_r3_rows` (HIGH) — every `.py` file under the four engine packages and every `.html` under `apps/monitor/` must have a CODE-tier row in R3. Closes the "routing table silently missed a file" failure mode.

Each predicate is a pure function over the `SchemaModel` + repo root; none of them regex-reads `REGISTRY.md` (`tests/core/test_thesis_alignment.py::test_predicates_do_not_call_registry_sections`). The rules operate on the authoritative YAML, not the rendered projection.

## 5. Surface boundaries — what the protocol governs vs. what it does not

The repo ships five technical surfaces in strict dependency order (ARCHITECTURE.md §0):

1. **Core engine + admin CLI** — `scripts/nightclaw-ops.py` + `nightclaw_engine/`. The only component required for a cron pass. Imports stdlib + PyYAML; optionally `nightclaw_ops` behind `try/except`.
2. **Telemetry emitter** — `nightclaw_ops/telemetry.py` + `nightclaw_ops/lifecycle.py`. Fire-and-forget JSON to `/tmp/nightclaw-ops.sock`. Fail-open: if nothing listens, `emit_step` no-ops and the engine continues.
3. **Bridge server** — `nightclaw_bridge/`. Reads the ops socket, fans to WebSocket, serves `apps/monitor/*.html`. **Does not import `nightclaw_engine`.** Invokes admin functionality only by spawning `scripts/nightclaw-admin.sh` / `scripts/nightclaw-ops.py` as subprocesses.
4. **Monitor UI** — `apps/monitor/*.html` + `nightclaw_monitor/`. Live reflection plus a token-authenticated RW admin panel. Localhost bind only; RW default-deny if `NIGHTCLAW_BRIDGE_TOKEN` unset; `hmac.compare_digest` token check; failed-attempt rate limiting per IP; fixed verb vocabulary (`ADMIN_CMD_RO | ADMIN_CMD_RW`); no shell interpolation.
5. **LLM bootstrap** — `orchestration-os/LLM-BOOTSTRAP.yaml` + `nightclaw-ops.py bootstrap`. Developer/agent-dev orientation tool. Invoked by humans only; cron prompts never reference it.

INV-15 (`tests/core/test_reachability.py`) enforces the DAG at the Python-symbol level. `tests/core/test_surface_boundaries.py` (six tests) pins the import-direction invariants: engine ↛ bridge/monitor, bridge ↛ engine, cron prompts ↛ `LLM-BOOTSTRAP.yaml`, step-map parity between parent monitor and data-flow iframe, admin verb vocabulary is a closed disjoint set.

## 6. What the domain proof (supporting material) validates

A prior multi-document workflow exists outside this repo that demonstrates the *kind of project* NightClaw is designed to govern — a monthly generator/plant transition intelligence MVP built from EIA public data (shortlist, power-MVP-definition, schema-draft, diff-event-logic, source-map, scoring-and-review-plan, implementation-plan, first-proof-workflow, open-questions-and-risks). That work is the content side: a real domain project, with its own schema and event logic, that would be scheduled through `ACTIVE-PROJECTS.md`, driven through phase transitions via `BUNDLE:phase_transition` / `BUNDLE:phase_advance`, produce outputs under `PROJECTS/<slug>/outputs/`, and leave a full audit trail. NightClaw's protocol surfaces (R1–R6 + bundles + audit log) are the governance layer around exactly this kind of workflow. The domain proof is not part of this repo's release artifact; it is referenced here as a concrete example of the workflow shape the protocol assumes.

## 7. What this protocol does not claim

- **Not a replacement for MCP or RAG.** MCP and RAG are probabilistic input surfaces for tool invocation and context retrieval. NightClaw governs the *writes, dependencies, audits, and cross-session handoffs* — orthogonal concerns. A session using MCP to call tools and RAG to assemble context can still (and should still) route its state mutations through `bundle-exec`.
- **Not a replacement for model judgment.** The LLM decides *what* to do (objective text, escalation wording, pass quality, direction). NightClaw decides *how* the decision becomes durable state. The LLM supplies bundle args; the engine validates and writes.
- **Not a defense against out-of-band filesystem tampering.** If an adversary with shell access edits `audit/AUDIT-LOG.md` directly between cron passes, the next `integrity-check` catches it only if the file is in the protected-file set. For protected files the hash catches drift; for runtime state files, adversarial shell access is out of scope. For that threat model, sign your commits and sandbox the host.
- **Not a distributed protocol.** Within a workspace, `LOCK.md` enforces mutual exclusion between worker and manager on a single host. Horizontal scale is at the workspace level — each workspace is independent, anchored to its own `SOUL.md` Domain Anchor. NightClaw does not coordinate state across workspaces.
- **Not a security product.** It is a drift-prevention architecture. The defense-in-depth is: R3 tier routing → R5 bundle guards → SCR predicates → SHA-256 integrity manifest. In-session drift is *prevented* (executor-mediated writes with preconditions). Between-session drift is *detected* (hash verification at T0). Out-of-band adversarial tampering is out of scope.

## 8. How to verify this document's claims

Everything in this document maps to a file and a command in the repo. To verify any claim:

| Claim | Verification |
|---|---|
| Live schema shape (objects / fields / routes / edges / bundles / SCR rules / protected paths / fingerprint) | `python3 scripts/nightclaw-ops.py bootstrap --track=general` (Repo summary section) or read each `schema/*.yaml` directly |
| `longrunner_update` bundle spec | `sed -n '17,40p' orchestration-os/schema/bundles.yaml` |
| R4 edges touched by that bundle | `python3 scripts/nightclaw-ops.py cascade-read BUNDLE:longrunner_update` and `cascade-upstream` on each target |
| R3 route for `PROJECTS/<slug>/LONGRUNNER.md` | `python3 scripts/nightclaw-ops.py registry-route PROJECTS/example/LONGRUNNER.md` → `ROUTE:STANDARD:BUNDLE:longrunner_update` |
| SCR-09 definition | `grep SCR-09 orchestration-os/schema/scr_rules.yaml` |
| Protected-file triangle | compare `schema/protected.yaml`, R3 `tier=PROTECTED` rows, and `audit/INTEGRITY-MANIFEST.md` |
| Engine does not import bridge/monitor | `grep -rn "from nightclaw_bridge\|from nightclaw_monitor" nightclaw_engine/` → empty |
| Cron prompts never reference bootstrap | `grep "LLM-BOOTSTRAP.yaml\|nightclaw-ops.py bootstrap" orchestration-os/CRON-*-PROMPT.md` → empty |
| Smoke test is non-interactive | `bash scripts/smoke-test.sh <zip>` completes without prompts |

Every gate listed in §3 can be re-run by anyone with a clean checkout. The protocol is not something to take on trust; it is queryable.

---

_This document is prose. The protocol itself lives in `orchestration-os/schema/*.yaml` and `nightclaw_engine/`. When they disagree with this document, trust them._
