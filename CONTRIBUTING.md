# Contributing to NightClaw

NightClaw is open source under the Apache 2.0 license.

For questions, issues, or to get involved, contact Chris Timpe at [human@tokenarch.com](mailto:human@tokenarch.com).

---

## Before You Change Anything

NightClaw is not a file collection — it is an object model with a typed impact graph. Every file that matters is either a declared object (R1/R2), a write-routed file (R3), or a node in the dependency graph (R4). Changes that ignore the graph produce silent drift: the feature works, but future traversals give wrong answers about what depends on what.

**The mandatory first step for any extension, customization, or bug fix is R4 traversal — not grepping for strings.**

### Why R4 traversal, not grep

Grep finds what you look for. R4 traversal finds what you don't know to look for. The typed impact graph (`orchestration-os/schema/edges.yaml`, rendered in `orchestration-os/REGISTRY.md § R4`) encodes every declared relationship between files — READS, WRITES, VALIDATES, TRIGGERS, REFERENCES, AUTHORIZES. The repo's own integrity guarantee states:

> *"The integrity guarantee holds ONLY as far as R4 declares. If a relationship between files is not in R4, PW-2 cannot surface it and the cascade terminates early."*

This means: if you add a new file relationship and don't declare an R4 edge, the graph silently returns `CASCADE:NONE` for that file. Every future engineer and every future agent session gets a false "nothing depends on this" answer.

### The extension workflow

For any change that introduces a new file, a new command, a new config file, or a new runtime relationship between existing files:

**1. Bootstrap first (developer/LLM tool — not used by cron sessions)**

NightClaw ships a developer bootstrap tool (`orchestration-os/LLM-BOOTSTRAP.yaml`) that is completely separate from the autonomous cron runtime. The cron worker and manager never call it and are never aware of it. It exists solely for developers and LLMs working on the repo itself.

```bash
python3 scripts/nightclaw-ops.py bootstrap --track=extend
```
This projects the dependency graph, the write-routing table, the protected file list, and the gate sequence into a single scoped view. Read it before touching anything.

**2. Traverse R4 on every file you plan to touch**
```bash
python3 scripts/nightclaw-ops.py cascade-read <file>
```
Run this on each target file. Read all surfaces edges return. If a file returns `CASCADE:NONE` and it is not genuinely isolated, the edge is missing — declare it before proceeding.

**3. Declare new R4 edges before writing**
If your change creates a new relationship between files (a new command reads a new config file, a new prompt step triggers a new command, a new field is validated by a new predicate), add the edge to `orchestration-os/schema/edges.yaml` first. Then run `schema-sync` to re-render `REGISTRY.md`. Then write the code.

The edge is the contract. The code implements it.

**4. Run the gate sequence after every structural change**
```bash
python3 -m pytest -x -q
python3 scripts/nightclaw-ops.py integrity-check
python3 scripts/nightclaw-ops.py scr-verify
python3 scripts/nightclaw-ops.py validate-bundles
python3 scripts/nightclaw-ops.py schema-sync
python3 scripts/nightclaw-ops.py schema-lint
```
All five must pass. `schema-sync` must be NOOP on second invocation after any deliberate schema edit.

**5. Re-sign protected files after any edit to them**
```bash
bash scripts/resign.sh <file>
```
The 11 protected files are listed in `audit/INTEGRITY-MANIFEST.md`. Editing any of them without re-signing causes `integrity-check` to fail on the next session.

### What makes NightClaw different from a standard codebase

Most codebases: change a file, run tests, done.

NightClaw: change a file, traverse its R4 edges, declare any new edges the change introduces, run schema-sync if schema YAML changed, re-sign if the file is protected, run the full gate sequence, verify cascade-read returns the correct result on every new file introduced. Then done.

This overhead exists because NightClaw's autonomous cron sessions use the same graph to make pre-write decisions at runtime. A gap in R4 doesn't break tests — it silently degrades the agent's impact analysis on every future session that touches that file.

### LLM bootstrap tracks

`orchestration-os/LLM-BOOTSTRAP.yaml` is a **developer and LLM tool only**. It is not part of the autonomous cron runtime. The cron worker, cron manager, and the core engine never reference it, call it, or depend on it. It has no R4 edges into the operational graph by design.

The bootstrap command projects a scoped, token-budgeted view of the repo for the specific task at hand:

| Track | Use when |
|-------|----------|
| `general` | Orientation — first time in the repo |
| `extend` | Adding a new feature, command, config file, or runtime relationship |
| `add_bundle` | Adding a new R5 bundle |
| `edit_schema` | Editing YAML under `orchestration-os/schema/` |
| `fix_bug` | Diagnosing or fixing a bug |
| `review_pr` | Reviewing a change for architectural fit |
| `add_predicate` | Adding a new SCR predicate |

```bash
python3 scripts/nightclaw-ops.py bootstrap --track=extend
```

### What R4 *does* model — and what it deliberately does not

R4 (`orchestration-os/schema/edges.yaml`) is the **operational object graph** used by the cron worker and cron manager to make pre-write decisions. It models cross-tier runtime relationships: which file/bundle reads or writes which other file, which prompt triggers which command, which doc cross-references which doc. It is the source of truth for `cascade-read` / `registry-route` / SCR predicates.

R4 **is not** a Python import graph. The four code packages (`nightclaw_engine`, `nightclaw_bridge`, `nightclaw_monitor`, `nightclaw_ops`) and `apps/monitor/*.html` are routed in R3 at tier `CODE` with on-disk existence checks (SCR-10, SCR-11). A CODE-tier file with zero R4 edges is acceptable: intra-package Python imports do not cross tier boundaries the runtime cares about, and the test suite is the primary correctness gate for those relationships. If you want to know "what imports `_shared.py`," use `grep -rn "_shared" nightclaw_engine/`. The `general` bootstrap track lists this escape hatch explicitly.

The CODE-tier rows that *do* have R4 edges are the ones that cross a tier boundary: `nightclaw_engine/schema/loader.py READS orchestration-os/schema/*.yaml`, `nightclaw_ops/telemetry.py WRITES /tmp/nightclaw-ops.sock`, `nightclaw_bridge/server.py READS /tmp/nightclaw-ops.sock`, etc. Add a new R4 edge if and only if your change introduces a new cross-tier relationship, not for ordinary Python imports.

### Monitor admin panel (Phase 2 — optional)

`nightclaw_bridge/runtime.py` exposes a fixed-vocabulary admin command surface to `apps/monitor/nightclaw-monitor.html`. The boundary is strict and worth understanding:

- **Bind:** localhost only (`127.0.0.1`). No remote access by default.
- **Token:** RW writes require `NIGHTCLAW_BRIDGE_TOKEN` set in the bridge's environment AND a matching token in the client's `connect` frame. Token comparison is constant-time (`hmac.compare_digest`). Token unset on the server → all clients are RO. Failed attempts are rate-limited per remote IP.
- **Vocabulary:** the verb sets `ADMIN_CMD_RO` (status/alerts/log/changes/file_diff/crash_context/notifications/audit/preapprovals/approval_chain/scr/phase/active_projects/diag_longrunner) and `ADMIN_CMD_RW` (approve/decline/pause/unpause/guide/arm/disarm/priority/done/clear_notifications/archive_project/resign/validate) are hard-coded constants. Anything outside the union is rejected before any work happens.
- **No shell interpolation.** Every shell-out uses `subprocess.run([...])` with a positional argv list. User input is validated by `_slug_ok` (regex), `_pa_ok`, path-traversal blocks, integer ranges, and length caps before becoming an argv element.
- **Engine independence.** `nightclaw_bridge/` does not import `nightclaw_engine` (verified by INV-15 + the R4-direction test in `tests/core/test_graph_integrity.py`). The bridge invokes engine functionality only by spawning `scripts/nightclaw-admin.sh` or `scripts/nightclaw-ops.py` as subprocesses. Same path the operator uses from a terminal.
- **Audit parity.** Every RW command writes to `audit/AUDIT-LOG.md` / `audit/CHANGE-LOG.md` in the same format the cron sessions write. There is no off-book channel.

The admin panel is a convenience for surface-1 commands, not a separate control plane. The cron worker and cron manager are unaffected by whether the bridge is running.

### Monitor data-flow SVG

`apps/monitor/NightClaw-Data-Flow.html` is a hand-authored static SVG: nodes and edges are `<rect>` and `<path>` elements with manually-placed coordinates. The step→nodes table inside the SVG file (`STEP_NODES`) and the matching table in the parent monitor (`STEP_GRAPH_MAP`) are also hand-curated. **The SVG is not generated from `edges.yaml` or `routing.yaml`**; if you add a new R1 object or R4 edge, the diagram will not auto-update.

The dynamic part is the activation/highlight overlay: when a `step` event arrives over WebSocket, the monitor posts `{type:'nc-highlight', step, nodes, run}` to the iframe, and `applyHighlight(step, nodes)` toggles CSS classes on the matching elements. Run labels, timestamps, and which step is current are live; layout is static. Treat the SVG as doctrine geometry, not a generated artifact.

### Versioning

NightClaw uses calendar versioning (`YYYY.M.D`). The runtime change record is `audit/CHANGE-LOG.md` — this is the official field-level log written by the cron agents during operation. There is no separate release changelog file.
