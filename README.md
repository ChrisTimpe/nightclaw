# NightClaw — Autonomous Overnight Agent Operating System for OpenClaw

**NightClaw turns OpenClaw into an agent that works on your projects while you live your life.**

You configure a domain focus and a project. You go about your day — or sleep. NightClaw runs structured passes overnight, builds on prior work across sessions, and surfaces a morning briefing of what was done, what decisions it needs from you, and what it wants to tackle next. You read it in two minutes, say yes or no, and it runs again tonight.

---

## At a Glance

**What is OpenClaw?** An open-source AI agent runtime that gives an LLM a shell, a filesystem, scheduled cron tasks, and persistent memory — running on your own hardware. [295,000+ GitHub stars as of April 2026](https://github.com/openclaw/openclaw) — the most-starred software project in GitHub history. This is what NightClaw runs on.

**What NightClaw adds:** A structured operational architecture for running OpenClaw around the clock on real multi-session projects. Two permanent crons (Worker + Manager), per-project phase lifecycle management with machine-testable completion, indexed failure recovery, pre-authorization for overnight autonomy, and an async morning briefing surface. All markdown files in the workspace the agent already reads. No external service. No API. No code to write or maintain.

**No Docker. No daemon. No database.** It is a folder of markdown files you drop into your OpenClaw workspace. The agent reads them as part of its working context. No code to write or maintain — that is the entire runtime.

**Platform:** Any OS where OpenClaw runs — macOS, Ubuntu, Windows (WSL2), remote Linux server, cloud VM. The install script requires `bash`, `sed`, `python3`, and `sha256sum` — present by default on macOS and any Linux distribution.

**Cost:** NightClaw itself is free (MIT). Running it costs only your LLM API tokens — Ollama works at zero cost for evaluation; Claude Sonnet 4.5 or GPT-5 class models are recommended for autonomous production passes. Token baseline: ~2,400 tokens per cron pass startup + ~6,900 session floor (SOUL + AGENTS + WORKING + ACTIVE-PROJECTS). See DEPLOY.md for full budget guidance.

**Web search:** OpenClaw's native search tool uses DuckDuckGo with a hard limit of ~10–15 queries per session. This is sufficient for targeted research passes but will block under heavy query patterns. For higher-volume research workloads, configure the [SearXNG plugin](https://github.com/openclaw/openclaw/releases) (bundled in OpenClaw 2026.4.x) or a dedicated search API (Serper, Brave) in your OpenClaw setup before running research-heavy projects.

**What you actually see after setup:**

| File | What it shows |
|------|---------------|
| `NOTIFICATIONS.md` | Every proposal, blocker, and escalation the agent has surfaced — your morning inbox |
| `audit/SESSION-REGISTRY.md` | Every cron run: model used, tokens consumed, projects touched, quality result, outcome |
| `audit/AUDIT-LOG.md` | Append-only record of every action taken, with authorization and outcome |
| `ACTIVE-PROJECTS.md` | What the agent is working on and at what priority — edit this to shift focus |
| `PROJECTS/[slug]/LONGRUNNER.md` | Per-project control file: current phase, verifiable stop condition, last pass, next pass objective |
| `memory/YYYY-MM-DD.md` | Structured log of what each pass actually did, written by the agent |

**Already have OpenClaw running?** See [Adding NightClaw to an Existing Workspace](#adding-nightclaw-to-an-existing-workspace) below.

> **⚠ NOTICE:** This framework was developed with AI assistance. It should be reviewed and adapted before use in any environment where failures could cause material harm. See the Disclaimers section.

> **Placeholders:** Files in this repo contain `{OWNER}`, `{WORKSPACE_ROOT}`, and similar tokens. These are intentional — `scripts/install.sh` substitutes them during setup. Do not edit them manually before running the install script.

---

## The Problem This Solves

People are already running OpenClaw overnight. Crons are already set. The question isn't whether to run an autonomous agent — it's whether it's doing anything useful and how you'd know.

OpenClaw ships with real operational tools: Standing Orders for program governance, exec approvals for action gating, session history, and behavioral identity files (SOUL.md, AGENTS.md, MEMORY.md). These work well for interactive use and single-program automation. What they don't cover is the specific challenge of multi-session autonomous work that spans days and weeks:

- No structured per-project lifecycle — what phase is active, what does done actually mean, what's the next objective
- No cross-session operational record — which cron runs happened, what they produced, what model was used, what the quality result was
- No failure taxonomy — when the agent hits a problem at 3am, it has no documented library of what that failure class means or what to try
- No pre-authorization model — the agent either blocks until you respond (useless overnight) or improvises permission (risky)
- No meta-cognitive oversight — nothing reviews whether the work the agent is doing is actually valuable, not just completed

Marc Andreessen called YOLO mode and keeping logs the right instinct. Jensen Huang said every company needs an OpenClaw strategy. NemoClaw answers the runtime sandbox question. **NightClaw answers the operational question** — what is the agent working on, across how many sessions, and is it actually making progress?

The operational layer lives inside the workspace the agent already reads. No external service. No separate infrastructure. No code. Because it's natural language the agent reasons over natively, the agent can diagnose failures, manage its own project state, and surface the decisions that actually need a human — instead of blocking on everything or guessing at everything.

A data engineer running ETL on a traditional stack manually monitors jobs, debugs failures, updates field maps when schemas change, and maintains records of what ran. **NightClaw externalizes all of that into the agent's own workspace.** The failure mode registry is the encoded runbook. The LONGRUNNER is the job definition. The session registry is the run record. The cron pattern is the scheduler. Because it's all natural language the agent reads directly, the agent can reason about failures — not just re-execute mechanically.

---

## What You Get

**Always-on operational architecture:**
- Worker cron every 60 minutes: integrity check → dispatch → project routing → execute pass → validate → quality gate → state update → OS improvement → session close
- Manager cron every 105 minutes (offset deliberately to review a completed pass, not a running one): crash detection → integrity verification → surface escalations → value and direction review → priority rebalancing → audit
- Session lock (LOCK.md) prevents concurrent cron overlap — Python-evaluated, not LLM-reasoned
- Manager detects worker crash from session registry + audit log correlation, surfaces CRITICAL escalation without halting other active projects

**Per-project phase lifecycle (LONGRUNNER):**
- Explicit current phase with a machine-testable stop condition — "at least 12 entries each containing name, URL, pricing, and user sentiment" not "when research is done"
- Successor phase definition and human review gate between transitions — TRANSITION-HOLD with auto-pause after 3 unanswered escalations
- Bounded next-pass objective the worker reads on startup; pass type taxonomy (discovery / depth / synthesis) with token budgets per type
- Phase-bound scheduler IDs tracked in the LONGRUNNER — scheduler deleted when phase completes, preventing stale wakes
- Per-pass output criteria: typed assertions (file_exists, row_count, field_present, schema_match, no_regression) verified at T5 before any pass is marked complete

**Self-healing execution:**
- 33 indexed failure modes — detection signal, root cause, fix procedure, prevention per entry
- Blocker decision tree: known failure → apply fix; pre-approved → act; partial completion possible → continue; none → surface proposal, re-route, never halt entirely
- Novel failures appended at T7 — the system never hits the same wall twice
- Cross-domain signal capture at T7: findings outside the current pass objective logged without derailing execution

**Quality standard (not just completion):**
- Three-question test at T5.5 after every pass: Expert Test (would a domain expert find this non-obvious?), Durable Asset Test (will this be useful in 30 days?), Compounding Test (does this make the next pass faster?)
- Applied from the outside — not the same agent grading its own work
- WEAK result surfaces a one-liner to NOTIFICATIONS.md; FAIL triggers a retry with a different approach

**Pre-approval for unattended overnight runs:**
- Two pre-approval slots (PA-001, PA-002) with scope, condition, expiry, and boundary declarations
- Worker checks at T2.7 before any action requiring approval — matches against active pre-approvals
- Every invocation logged to APPROVAL-CHAIN.md with timestamp, run_id, and scope verified
- Conservative mode when no pre-approvals active: anything uncertain goes to NOTIFICATIONS.md, never improvised

**Cross-session operational record:**
- SESSION-REGISTRY: every cron pass logged (model, tokens, quality result, integrity check, outcome) — not session history, a cross-session run ledger
- AUDIT-LOG: append-only action log with field-level change attribution and authorization linkage
- CHANGE-LOG: field-level diff log with bi-temporal timestamps (t_written / t_valid)
- APPROVAL-CHAIN: countersigned pre-approval invocations with scope verification

**Governance integrity (structured accountability, not tamper prevention):**
- SHA-256 hashes for 11 core framework files, verified at T0 (Worker) and T1 (Manager) every pass
- Mismatch halts the Worker before any execution — an alert you may miss is categorically different from a session that won't start
- Intentional edits require explicit re-sign via `scripts/resign.sh` — making changes deliberate, not accidental
- Manager updates "Last verified" timestamps after verification; hash values are owner-only writes

**Behavioral discipline (encoded as identity, not enforced by runtime):**
- Hard Lines in SOUL.md and CRON-HARDLINES.md: NEVER list (git push, external posting, prompt injection responses, skill injection) and ALWAYS list (append-only audit files, one approval = one action in one context)
- CRON-HARDLINES distills behavioral constraints into ~800 tokens loaded first in every cron session
- Emergency kill switch: setting all ACTIVE-PROJECTS.md rows to paused is the reliable halt path for unattended operation
- Specific prompt injection defenses documented as behavioral identity: LONGRUNNER injection, skill injection, memory file poisoning, link preview exfiltration, log poisoning (CVE fixed in 2026.2.13)

**Idle cycle — productive when no projects are active:**
- Tier 1: active intelligence (inbox scan, staleness checks, demand signals)
- Tier 2: knowledge base maintenance (source freshness, OPS file review, TOOL-STATUS sync)
- Tier 3: memory consolidation and OS improvement (dream pass, AGENTS-LESSONS update)
- Tier 4: autonomous project proposal from Domain Anchor — drafts a LONGRUNNER and surfaces for approval

**Skill layer (Part 2 — replaceable):**
- OPS-KNOWLEDGE-EXECUTION.md demonstrates field map + script template pattern for known systems
- Agent reads field maps before writing scripts → confirmed knowledge, not inference
- Agent extends maps after successful runs → compounding accuracy over time
- Ships with generic scaffolding; add field maps for your own systems and APIs

---

## Quick Start

```bash
# For fresh installs only — this overwrites your workspace directory
# Clone directly into your OpenClaw workspace
git clone https://github.com/ChrisTimpe/nightclaw ~/.openclaw/workspace
cd ~/.openclaw/workspace
bash scripts/install.sh
```

```bash
# Or from a downloaded zip release
cp -r nightclaw-v0.1.0-release/* ~/.openclaw/workspace/
cd ~/.openclaw/workspace
bash scripts/install.sh
```

The install script will prompt for your configuration values, substitute all placeholders, and generate the initial integrity hashes.

**Input sanitization note:** All values entered during install must contain only alphanumeric characters, hyphens, underscores, forward slashes, periods, and tildes. Do not include shell metacharacters (spaces, quotes, pipes, semicolons, dollar signs, backticks, etc.) in any configuration value.

### Manual Setup (if not using install script)

```bash
OWNER="yourname"
WORKSPACE_ROOT="$HOME/.openclaw/workspace"
CRON_DIR="$HOME/.openclaw/cron"
LOGS_DIR="$HOME/.openclaw/logs"
PLATFORM="Ubuntu/WSL2"
INSTALL_DATE=$(date +%Y-%m-%d)

# Values must be alphanumeric, hyphens, underscores, forward slashes, and periods only.
# No spaces in any value — spaces break sed substitutions.
find . -name "*.md" -exec sed -i \
  -e "s|{OWNER}|$OWNER|g" \
  -e "s|{WORKSPACE_ROOT}|$WORKSPACE_ROOT|g" \
  -e "s|{OPENCLAW_CRON_DIR}|$CRON_DIR|g" \
  -e "s|{OPENCLAW_LOGS_DIR}|$LOGS_DIR|g" \
  -e "s|{PLATFORM}|$PLATFORM|g" \
  -e "s|{INSTALL_DATE}|$INSTALL_DATE|g" \
  {} \;

# {DOMAIN_ANCHOR} is set manually — open SOUL.md and replace the
# Domain Anchor section with your own domain focus or consulting practice.

# Generate integrity hashes (first-sign)
bash scripts/verify-integrity.sh
# Paste each hash into audit/INTEGRITY-MANIFEST.md

# Set agent timeout
openclaw config set agents.defaults.timeoutSeconds 600

# Create two crons
openclaw cron add \
  --name "nightclaw-worker-trigger" \
  --every 60m \
  --session "session:nightclaw-worker" \
  --message "HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-WORKER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps." \
  --light-context \
  --no-deliver

openclaw cron add \
  --name "nightclaw-manager-trigger" \
  --every 105m \
  --session "session:nightclaw-manager" \
  --message "HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-MANAGER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps." \
  --light-context \
  --no-deliver
```

> **Cron session names** are `nightclaw-worker` and `nightclaw-manager` by default. Rename them to anything — update both `--name` and `--session` together, and update references in `orchestration-os/OPS-CRON-SETUP.md`.

Full setup details: [`INSTALL.md`](INSTALL.md) → [`DEPLOY.md`](DEPLOY.md)

---

## Your First Project

After install and cron setup, **you don't need to do anything.** On the first idle cycle the worker reads your Domain Anchor in `SOUL.md` and proposes a first project automatically. You wake up to a draft waiting for your one-word approval.

**The default overnight flow:**

1. Crons start running
2. First idle cycle: worker reads Domain Anchor → drafts `PROJECTS/[slug]/LONGRUNNER-DRAFT.md` → surfaces MEDIUM notification
3. You open a main session: agent briefs you on the draft and what the first pass will do
4. You say **"approve"** — agent activates the project, worker picks it up on next pass
5. Overnight: worker executes research passes, manager reviews, progress accumulates
6. Morning: you read `NOTIFICATIONS.md` for a summary of what happened

**To start immediately without waiting:**

```bash
# Scaffold a project in one command
bash scripts/new-project.sh my-first-project

# Fill in CORE section of the generated LONGRUNNER.md
# (Required: mission, phase.objective, stop_condition, next_pass.objective)

# Force-run the worker now
openclaw cron run [worker-id]   # get ID from: openclaw cron list
```

**What to expect on first run:**
- Worker reads your LONGRUNNER, executes the first pass objective
- Writes a structured log to `memory/YYYY-MM-DD.md`
- Updates `last_pass` in your LONGRUNNER
- Logs to `audit/SESSION-REGISTRY.md`
- If blocked: writes a proposal to `NOTIFICATIONS.md` and routes to next available project

**Multiple projects:** NightClaw is designed to run a portfolio. While one project is in review or transition, the worker routes to the next. For meaningful overnight throughput, 2–3 active projects at different phases is the intended operating mode.

> **Reference:** `PROJECTS/example-research/LONGRUNNER.md` is a fully filled-in example you can read before creating your own. It has no effect on the running system unless added to `ACTIVE-PROJECTS.md`.

---

## Adding NightClaw to an Existing Workspace

If OpenClaw is already running, NightClaw drops in alongside it. The operational layer — `orchestration-os/`, `audit/`, `scripts/`, `PROJECTS/`, `memory/`, `skills/`, and a set of new root-level files — adds cleanly with no conflicts. A handful of root identity files (`SOUL.md`, `AGENTS.md`, `MEMORY.md`, and a few others) will replace OpenClaw's defaults — this is intentional. NightClaw's versions of those files contain the behavioral contracts and governance wiring the system needs.

**macOS, Linux, remote server, WSL2, or cloud VM:**
```bash
cd ~/.openclaw/workspace        # or wherever your workspace is
curl -L https://github.com/ChrisTimpe/nightclaw/archive/refs/heads/main.tar.gz | tar xz --strip-components=1
bash scripts/install.sh
```

That's it for a vanilla OpenClaw workspace. The install script prompts for your configuration values and generates the integrity hashes.

> **Prefer git?** `git clone https://github.com/ChrisTimpe/nightclaw /tmp/nightclaw && cp -r /tmp/nightclaw/* ~/.openclaw/workspace/`

**If you've customized any of these files**, back them up before running the curl command — they will be overwritten:

```
SOUL.md    AGENTS.md    AGENTS-CORE.md    WORKING.md
MEMORY.md  IDENTITY.md  USER.md           HEARTBEAT.md  TOOLS.md
```

After install, merge your customizations back in. Content worth preserving: your persona or custom Hard Lines in `SOUL.md`, domain restrictions in `USER.md`, memory entries in `MEMORY.md`. NightClaw's versions of these files are required for the operational architecture to work — your content goes on top, not instead.

**If your workspace is already active (crons running):** Pause all projects first, drop in the files, run `install.sh`, then re-enable.
```bash
# In ACTIVE-PROJECTS.md: set all rows to status: paused
# Then install, then re-enable one project at a time
```

---

## How It Works

Two crons run permanently. The **worker** fires every 60 minutes: verifies session state (Python-evaluated lock check, not LLM-reasoned), reads the dispatch table, routes to the highest-priority active project, and executes one bounded pass (T0–T9): integrity check → dispatch → LONGRUNNER read → authorization check → tool pre-flight → execute → validate output criteria → quality gate → state update → OS improvement gate → session close. If it hits a blocker, it runs the blocker decision tree — applies the known failure mode fix, checks pre-approvals, attempts partial completion, or surfaces a proposal and re-routes. Designed to never halt on recoverable blockers; integrity failures halt by design.

The **manager** fires every 105 minutes — offset deliberately to review a completed worker pass, not a running one. It verifies session state, detects worker crash from audit log correlation, surfaces escalations, checks TRANSITION-HOLD expirations (with auto-pause after 3 unanswered escalations), reviews pass quality and direction against OPS-QUALITY-STANDARD.md, rebalances priorities, and closes with session registry and memory entries.

The **human touchpoint** is async. The agent surfaces proposals, blockers, and enhancement candidates to NOTIFICATIONS.md as it encounters them. The owner reviews at their own cadence — typically a morning check — approves or guides, and the next worker pass acts on those decisions. This is the designed interaction pattern, not an exception flow.

```
ACTIVE-PROJECTS.md              ← what to work on (dispatch table)
PROJECTS/[slug]/LONGRUNNER.md   ← how to work on it (per-project control file)
NOTIFICATIONS.md                ← what needs human attention (proposals + escalations)
CRON-WORKER-PROMPT.md           ← worker protocol (T0–T9)
CRON-MANAGER-PROMPT.md          ← manager protocol (T0–T9)
```

---

## File Map

### Root

```
SOUL.md                    Agent identity — Hard Lines as behavioral defaults, task discipline
AGENTS.md                  Navigation index — points to AGENTS-CORE.md and AGENTS-LESSONS.md
AGENTS-CORE.md             PROTECTED behavioral contracts, sub-agent rules, memory model
AGENTS-LESSONS.md          T7d lesson accumulation (STANDARD — written by agent)
IDENTITY.md                Agent persona template (filled on first run)
USER.md                    Owner profile and domain restrictions
MEMORY.md                  Long-term memory (auto-injected each session by OpenClaw)
HEARTBEAT.md               Periodic check-in and cron trigger routing
WORKING.md                 Session briefing template
ACTIVE-PROJECTS.md         Priority-ranked dispatch table
LOCK.md                    Session lock — prevents concurrent cron writes (Python-evaluated)
NOTIFICATIONS.md           Async proposal + escalation surface (agent writes, owner reads)
TOOLS.md                   Tool notes and local environment config
VERSION                    Current version identifier
INSTALL.md                 Setup guide
DEPLOY.md                  Complete deployment guide
UPGRADING.md               Upgrade guide for existing deployments
TROUBLESHOOTING.md         Lock reset, integrity recovery, manual testing procedures
CONTRIBUTING.md            Contribution guidelines
README.md                  This file
LICENSE                    MIT license
CHANGELOG.md               Release history
CODE_OF_CONDUCT.md         Contributor Covenant v2.1
SECURITY.md                Vulnerability reporting policy
nightclaw-architecture.svg Integration synergy diagram
.gitignore                 Standard git exclusions
```

### audit/

```
AUDIT-LOG.md               Append-only action log with authorization linkage
INTEGRITY-MANIFEST.md      SHA-256 hashes for 11 protected files — T0 halt on mismatch
APPROVAL-CHAIN.md          Pre-approval invocation log with scope verification
SESSION-REGISTRY.md        Cross-session run record: model, tokens, quality, outcome per pass
CHANGE-LOG.md              Bi-temporal field-level state change log
```

### orchestration-os/

```
START-HERE.md              Read first — three rules, routing table, system overview
ORCHESTRATOR.md            Multi-project dispatch + phase transition protocol (runtime protocol)
CRON-WORKER-PROMPT.md      Worker cron protocol (T0–T9) — one pass, one objective, structured, audited
CRON-MANAGER-PROMPT.md     Manager cron protocol — govern, verify, direct; does not execute project tasks
CRON-HARDLINES.md          Distilled behavioral discipline for cron sessions (~800 tokens)
REGISTRY.md                System catalog: R1 objects, R2 field contracts, R3 write routing,
                           R4 dependency graph, R5 bundles, R6 self-consistency rules, R7 change-log format
OPS-CRON-SETUP.md          Cron configuration, cadence tuning, setup checklist
OPS-AUTONOMOUS-SAFETY.md   Behavioral discipline contract + blocker decision tree (self-healing core)
OPS-PREAPPROVAL.md         Pre-authorize action classes for overnight unattended runs
OPS-QUALITY-STANDARD.md    Three-question quality test + manager value methodology
OPS-FAILURE-MODES.md       33 indexed failure modes — diagnose before retrying
OPS-KNOWLEDGE-EXECUTION.md Part 2: skill layer — field maps + script templates (replaceable)
OPS-TOOL-REGISTRY.md       Tool constraint knowledge base
OPS-IDLE-CYCLE.md          Ranked autonomous work when no active project (4-tier ladder)
OPS-PASS-LOG-FORMAT.md     Structured daily memory log format
LONGRUNNER-TEMPLATE.md     Project control file template
PROJECT-SCHEMA-TEMPLATE.md Per-project schema template
TOOL-STATUS.md             Fast pre-flight tool check (~200 tokens)
```

### scripts/

```
scripts/install.sh          Automates placeholder substitution + first-sign hash generation
scripts/verify-integrity.sh Generates SHA-256 hashes for all protected files
scripts/validate.sh         96 checks — internal consistency, file references, registry completeness
scripts/resign.sh           Re-signs all protected files after intentional edits
scripts/upgrade.sh          Merges updated NightClaw files into an existing workspace without data loss
scripts/new-project.sh      Scaffolds a new LONGRUNNER project directory from template
scripts/check-lock.py       Diagnostic — prints current LOCK.md state (manual use only)
scripts/smoke-test.sh       18-check first-run smoke test in an isolated temp directory
```

### PROJECTS/

```
PROJECTS/MANAGER-REVIEW-REGISTRY.md   Global project scoreboard for manager reviews
PROJECTS/example-research/LONGRUNNER.md   Filled-in reference project (no effect unless added to ACTIVE-PROJECTS.md)
```

### Directories

```
memory/                    Daily session logs (written by agent at runtime)
skills/                    Agent skill files (added by user)
```

---

## Day-to-Day Operation

| Action | How |
|--------|-----|
| Check what's running | Read `ACTIVE-PROJECTS.md` or ask the agent |
| See proposals + escalations | Read `NOTIFICATIONS.md` |
| Add a project | `bash scripts/new-project.sh [slug]` → fill LONGRUNNER CORE section → add row to `ACTIVE-PROJECTS.md` |
| Shift focus | Change priority numbers in `ACTIVE-PROJECTS.md` |
| Pause a project | Set its status to `paused` |
| Emergency stop | Set all rows in `ACTIVE-PROJECTS.md` to `paused` |
| Authorize overnight work | Add entries to `OPS-PREAPPROVAL.md` before going offline |
| Approve an enhancement proposal | Add a pre-approval entry in `OPS-PREAPPROVAL.md` referencing the proposal |
| Adjust cron cadence | `openclaw cron delete [id]` then recreate with new `--every` value |
| Validate framework consistency | `bash scripts/validate.sh` (96 checks) |
| After editing any protected file | `bash scripts/resign.sh` — re-signs INTEGRITY-MANIFEST.md |
| Archive old audit logs | Review `audit/AUDIT-LOG.md` periodically (monthly recommended) |
| Diagnose a lock issue | `python3 scripts/check-lock.py` |

---

## Origin and Attribution

NightClaw originated these patterns for OpenClaw workspace governance. If you fork, port, or build on this work, no permission is required — but attribution is appreciated, and credit where it belongs matters to the community that made it possible.

The concepts introduced here, as of v0.1.0 (April 2026):

- **Workspace-native operational architecture** — the governance and orchestration layer lives inside the workspace the agent reasons over natively, not in external infrastructure; the agent reads its own governance as part of its working context
- **LONGRUNNER lifecycle** — per-project control file with explicit phases, machine-testable stop conditions, phase transition protocol with TRANSITION-HOLD and auto-pause, phase-bound scheduler tracking, and pass type taxonomy with token budgets
- **Indexed failure mode registry** — classified failure taxonomy the agent reads before retrying, with root cause, detection signal, fix, and prevention per entry; novel failures appended at T7 so the system never hits the same wall twice
- **Typed object model with cascade integrity** — REGISTRY.md as a schema with R1–R7 (objects, field contracts, write routing, dependency edges, bundles, self-consistency rules, change-log format); pre-write protocol traversing dependency edges before every write
- **Bi-temporal field-level change log** — `t_written` / `t_valid` split with point-in-time reconstruction
- **Hard Lines as behavioral identity** — behavioral discipline encoded as agent character rather than enforced constraints; CRON-HARDLINES.md distillation for light-context cron sessions
- **Pre-approval system for unattended overnight runs** — scoped action class authorization with expiry, condition, boundary declaration, scope verification, and countersigned approval chain
- **Manager/Worker two-cron split** — dedicated execution and governance passes at different cadences, both project-agnostic, driven by a priority-ranked dispatch table; manager detects worker crash state from session registry correlation
- **T7 OS improvement gate** — G1 (non-obvious) + G2 (generalizable) gate before any agent write to framework files; prevents noise accumulation; cross-domain signal capture without derailing active passes
- **TRANSITION-HOLD with auto-pause** — phase completion triggers human review gate; three missed escalations auto-pauses the project
- **Morning-check async workflow** — structured proposal surface the agent writes to during overnight passes; owner reviews at their own cadence
- **Idle cycle priority ladder** — 4-tier structured autonomous work when no projects are active; the system improves itself rather than sitting idle
- **Pass type taxonomy** — discovery / depth / synthesis pass types with declared token/search budgets; cost management built into the project lifecycle
- **Skill-attachment pattern (Part 2)** — domain execution knowledge encoded as a workspace file the agent reads before writing code; agent extends the file after successful runs, creating a compounding learning loop

This is v0.1.0. The framework will evolve. Whatever it becomes, this is where it started.

---

## Design Model

NightClaw is not a collection of markdown files with cross-references. It is an **object model with cascade integrity**.

**The schema is `REGISTRY.md`.** R1 defines the objects. R2 defines field contracts. R3 is the write-routing table — tier and bundle per file. R4 is the dependency graph: typed edges that declare structural relationships between objects. R5 is the bundle library: named operations that execute multi-file writes as atomic units.

**The cascade mechanism is the pre-write protocol** (`SOUL.md §1a`, PW-1–PW-5). When the agent writes any file, PW-2 greps R4 for that file's outbound edges and surfaces every downstream dependent. The agent does not manually reason about what might be affected — the schema declares it, and the protocol traverses it. The integrity guarantee holds only as far as R4 declares. Missing edges produce drift that looks like bugs but is actually incomplete schema.

**For anyone extending the system:** add R4 edges before adding new file relationships. The edge is the contract. Without it, PW-2 has no way to know the relationship exists, the cascade terminates early, and downstream files silently diverge.

**The AGENTS split** (v0.1.0): AGENTS.md is split into AGENTS-CORE.md (PROTECTED, in manifest) + AGENTS-LESSONS.md (STANDARD, T7d write target) + AGENTS.md (thin nav index, not in manifest). This follows the same pattern as ACTIVE-PROJECTS.md — separating the durable behavioral contract (drift-detected) from the accumulating agent-written layer (T7d target, never in manifest). AGENTS-CORE.md contains the behavioral contracts the agent internalizes as identity. AGENTS-LESSONS.md accumulates lessons written at T7d. AGENTS.md is the navigation pointer to both.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PART 1: ORCHESTRATION FRAMEWORK                             │
├──────────────────────────────────────────────────────────────┤
│                    SOUL.md (Behavioral Identity)             │
│         Hard Lines + task discipline + output standards      │
├──────────────────────────────────────────────────────────────┤
│  CRON-HARDLINES.md    Behavioral constraints for cron runs   │
├─────────────────────────┬────────────────────────────────────┤
│   Worker (60 min)       │   Manager (105 min)                │
│                         │                                    │
│   T0 Integrity check    │   T0 Crash detection               │
│   T1 Dispatch           │   T1 Integrity verification        │
│   T2 LONGRUNNER         │   T2 Surface escalations           │
│   T2.5 Model + budget   │   T3 Change detection              │
│   T2.7 Authorization    │   T4 Value check                   │
│   T3 Tool check         │   T5 Direction check               │
│   T4 Execute pass       │   T6 Priority rebalancing          │
│   T5 Validate criteria  │   T7 Update registry               │
│   T5.5 Quality gate     │   T8 Audit review + OS improve     │
│   T6 State update       │   T9 Session close                 │
│   T7 OS improvement     │                                    │
│   T9 Session close      │                                    │
│                         │                                    │
│   ↓ on blocker:         │                                    │
│   Blocker decision tree │                                    │
│   → self-heal or        │                                    │
│   → propose + re-route  │                                    │
├─────────────────────────┴────────────────────────────────────┤
│              NOTIFICATIONS.md (Async Human Surface)          │
│  Proposals  ·  Escalations  ·  Enhancement candidates       │
│  Agent appends  →  Owner reviews at morning check            │
├──────────────────────────────────────────────────────────────┤
│              REGISTRY.md (System Catalog)                    │
│  R1 Objects  R2 Fields  R3 Write routing  R4 Dependencies   │
│  R5 Bundles  R6 Self-consistency rules  R7 Change-log format │
├──────────────────────────────────────────────────────────────┤
│                    audit/ (5 files)                          │
│  AUDIT-LOG  SESSION-REGISTRY  CHANGE-LOG                     │
│  INTEGRITY-MANIFEST (drift detection)  APPROVAL-CHAIN       │
├──────────────────────────────────────────────────────────────┤
│  PART 2: ETL SKILL LAYER (Proof of Concept — Replaceable)   │
├──────────────────────────────────────────────────────────────┤
│  OPS-KNOWLEDGE-EXECUTION.md                                  │
│  Field maps + schema quirks + script templates               │
│  Agent reads before writing code → confirmed knowledge       │
│  Agent extends after successful runs → compounding accuracy  │
│  Ships with generic scaffolding; add field maps for your     │
│  own systems, APIs, and data sources                         │
└──────────────────────────────────────────────────────────────┘
```

### Integration Synergies

Six chains active from first cron pass — Domain Anchor → Tier 4 → NOTIFICATIONS, session lock dual-release paths, three-layer task system, T7 OS improvement gate, pre-approval chain, and cron security model:

![NightClaw Integration Synergies](nightclaw-architecture.svg)

---

## Requirements

- [OpenClaw](https://github.com/openclaw/openclaw) `2026.2.13` or later (CVE patched). Recommended: `2026.4.5`+ — two fixes required: `--every` flag format changed in `2026.4.1` (human-readable strings: `60m`, `1h`); `--light-context` workspace injection bug fixed in `2026.4.5` (PR #60776). NightClaw's cron architecture depends on both.
- Any supported LLM provider — OpenAI, Anthropic, Google, or local models via Ollama
- **Model minimum for autonomous cron sessions:** Confirmed working: Claude Sonnet 4.5+ (community sweet spot), GPT-5 class (gpt-5.3-codex or equivalent). Ollama works for evaluation and lightweight tiers. GPT-4o class and below are not recommended for autonomous cron passes — instruction-following at the LONGRUNNER and CRON-HARDLINES level degrades.
- A terminal for one-time placeholder substitution and first-sign

---

## Compatibility

**NemoClaw (NVIDIA):** Fully compatible. NightClaw and NemoClaw operate at distinct layers — NemoClaw provides runtime sandboxing (kernel-level filesystem isolation, deny-by-default networking, PII routing); NightClaw provides workspace operational architecture (project lifecycle, session registry, behavioral discipline, failure recovery). Run both together for defense in depth. NightClaw works with or without NemoClaw.

**OpenClaw Standing Orders:** NightClaw's LONGRUNNER and pre-approval system extend, not replace, OpenClaw's native Standing Orders. Standing Orders define what the agent is authorized to do within a session; LONGRUNNER defines what phase a project is in, what verifiable completion looks like, and what the next bounded pass should accomplish across sessions. Use both.

**OpenClaw forks** (nanobot, ZeroClaw, PicoClaw, NanoClaw, and others): Should work if the fork preserves OpenClaw's cron and session API — specifically `openclaw cron add`, `--light-context`, `--no-deliver`, and named sessions (`session:name`). Check the fork's changelog for API compatibility before deploying.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). High-value contributions: new failure modes from real deployments, field maps for additional systems, blocker decision tree improvements from edge cases encountered in practice.

---

## Maintainer

Created and maintained by [@ChrisTimpe](https://github.com/ChrisTimpe).

Contributions welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). Security issues: use GitHub private vulnerability reporting (see [`SECURITY.md`](SECURITY.md)).

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Disclaimers

**⚠ AI-assisted framework.** This orchestration framework was developed with AI assistance using publicly available documentation, research, and design patterns. It should be reviewed and adapted by qualified professionals before use in any environment where failures could cause material harm.

**Not legal, compliance, or regulatory advice.** NightClaw provides operational orchestration patterns for AI agent workspaces. It does not constitute legal counsel, and its use does not create any attorney-client or advisory relationship. Organizations should independently evaluate whether these patterns meet their specific compliance requirements.

**Behavioral discipline, not enforced security.** NightClaw implements behavioral discipline constraints (Hard Lines) encoded as agent identity. These are reliable because a well-calibrated agent internalizes them — not because they are technically enforced at the runtime level. SHA-256 integrity checks detect accidental file drift between sessions; they do not prevent a determined adversary from modifying files. For runtime sandboxing and kernel-level enforcement, use NemoClaw. For tamper-proof integrity records, use signed git commits.

**No warranty of fitness.** The Software is provided "as is," without warranty of any kind. See the MIT License for full terms. The authors and contributors are not liable for any damages arising from the use of this software.

**Automated system disclaimer.** This framework orchestrates automated AI agent actions. Users bear full responsibility for all actions taken by agents operating under this framework, including any financial, legal, or operational consequences.

**Domain restriction disclaimer.** Domain restrictions configured in `USER.md` are user-set behavioral preferences, not legal compliance mechanisms. This software does not provide legal enforcement of employment obligations, non-compete agreements, or contractual restrictions.

**Data storage notice.** This framework stores user-configured data (`USER.md`, `MEMORY.md`) and creates operational records of agent activity in the local workspace. Users are responsible for compliance with applicable data protection regulations (including GDPR, CCPA, and similar laws) when deploying this framework.

**Third-party references.** Any field maps or endpoint patterns added to `OPS-KNOWLEDGE-EXECUTION.md` should reference only publicly available documentation. No proprietary, NDA-protected, or confidential information from any third party should be included. All trademarks are the property of their respective owners.

**Audit log size.** Agent activity is logged to `audit/AUDIT-LOG.md` and `audit/SESSION-REGISTRY.md`. In high-frequency deployments these files can grow large. Periodic archival is recommended (monthly is a reasonable default).
