# DEPLOY.md — Extended Deployment Reference

---

## What This Is

**New users:** start with [README.md § Install](README.md#install) for the guided walkthrough —
platform setup, automated install, first-sign, cron creation, and validation in order.
This file is the extended reference for topics that need more depth: model configuration,
heartbeat cost control, pre-authorization, token budgets, and the uninstall procedure.

Works with any LLM provider configured in openclaw.json. Token figures below are based on a GPT-5 class model at typical context sizes — adjust for your provider.

---

## Before You Start

Five things that prevent 90% of first-hour problems:

1. **Confirm your OpenClaw version is 2026.4.5+** — run `openclaw --version`. Earlier versions have a `--light-context` bug that burns tokens on every cron pass. `bash scripts/validate.sh` checks this.

2. **Confirm a working model before starting crons** — run `openclaw models status` and verify a provider shows an active token or API key. If nothing is configured, crons will error silently. OpenAI OAuth (ChatGPT Plus) works immediately; Google Gemini requires an API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

3. **Fill in SOUL.md Domain Anchor before your first cron** — open `SOUL.md`, find `{DOMAIN_ANCHOR}`, replace it with 2-3 sentences describing your domain focus. This is what the agent uses to propose your first project autonomously. Without it, idle cycles produce nothing useful.

4. **Activate PA-001 and PA-002 before going offline** — see `## Before Your First Overnight Run` below. Without these, the system runs in conservative mode and idle cycles will find nothing actionable.

5. **Never force-run crons rapidly in succession** — each pass acquires a 20-minute lock. If you trigger a second run while the first is still active, it defers and produces no output. Wait for the lock to release (visible in `LOCK.md`) before re-running. Use `python3 scripts/check-lock.py` to verify whether the lock is released, active, or stale; the stale-lock failure class is documented in `orchestration-os/OPS-FAILURE-MODES.md`.

---

## Step 1 — Deploy Files

Copy the contents of this zip into your OpenClaw workspace:

```bash
# From the zip, copy everything into:
{WORKSPACE_ROOT}/

# The result should look like:
{WORKSPACE_ROOT}/
├── SOUL.md
├── IDENTITY.md
├── USER.md
├── AGENTS.md
├── AGENTS-CORE.md
├── AGENTS-LESSONS.md
├── LOCK.md
├── MEMORY.md
├── HEARTBEAT.md
├── WORKING.md
├── NOTIFICATIONS.md
├── ACTIVE-PROJECTS.md
├── DEPLOY.md                        ← Deployment guide (reference)
├── TOOLS.md
├── VERSION
├── INSTALL.md
├── audit/
│   ├── AUDIT-LOG.md
│   ├── INTEGRITY-MANIFEST.md
│   ├── APPROVAL-CHAIN.md
│   ├── SESSION-REGISTRY.md
│   └── CHANGE-LOG.md
├── orchestration-os/
│   ├── START-HERE.md
│   ├── ORCHESTRATOR.md
│   ├── CRON-WORKER-PROMPT.md
│   ├── CRON-MANAGER-PROMPT.md
│   ├── CRON-HARDLINES.md
│   ├── OPS-CRON-SETUP.md
│   ├── OPS-AUTONOMOUS-SAFETY.md
│   ├── OPS-PREAPPROVAL.md
│   ├── OPS-QUALITY-STANDARD.md
│   ├── OPS-FAILURE-MODES.md
│   ├── OPS-IDLE-CYCLE.md
│   ├── OPS-PASS-LOG-FORMAT.md
│   ├── OPS-TOOL-REGISTRY.md
│   ├── OPS-KNOWLEDGE-EXECUTION.md
│   ├── LONGRUNNER-TEMPLATE.md
│   ├── REGISTRY.md
│   ├── TOOL-STATUS.md
│   └── PROJECT-SCHEMA-TEMPLATE.md
├── PROJECTS/
│   └── MANAGER-REVIEW-REGISTRY.md
└── memory/                          ← Daily session logs (written by agent)
```

---

## Step 2 — Substitute Placeholders

Run the install script from the workspace root:

```bash
bash scripts/install.sh
```

This prompts for your configuration values, substitutes all placeholders across every `.md`
file, and generates the initial SHA-256 integrity hashes. It is the only manual step —
everything else is automated from here. Full details: [README.md § Automated install](README.md#automated-install-recommended).

---

## Step 2.5 — Configure SOUL.md Domain Anchor

Open `SOUL.md` and find the `{DOMAIN_ANCHOR}` placeholder. Replace it with 2–3 sentences
describing your domain focus — the area where you want the agent to build knowledge
and propose research projects autonomously.

**Example:**
```
I work in quantitative finance with a focus on fixed-income derivatives and risk modeling.
My research priorities are volatility forecasting, term-structure models, and cross-asset
correlation under stress. I am building toward a systematic literature review of recent
academic work in these areas.
```

This is what the idle cycle uses to generate your first autonomous project proposal (Tier 4).
Without it, idle passes produce nothing useful.

**SOUL.md is a protected file.** After editing, re-sign it or the first cron T0 will fail:
```bash
bash scripts/resign.sh SOUL.md
bash scripts/verify-integrity.sh   # must show 11/11
```

**Also update USER.md** (name, timezone, domain restrictions) and re-sign it:
```bash
bash scripts/resign.sh USER.md
```

---

## Step 3 — Verify OpenClaw Version

```bash
openclaw --version
```

Must show `2026.4.5` or higher. Versions 2026.4.1–2026.4.4 contain a `--light-context` bug
(PR #60776) that silently injects all bootstrap files despite the flag, burning 16k–19k tokens
per cron pass. Earlier versions are unsupported.

```bash
openclaw health
```

Should return: Gateway running, bound to 127.0.0.1.
If not: `openclaw gateway restart` then re-check.

---

## Step 4 — First Session

Open a main session. OpenClaw loads WORKING.md as context on session start (it is listed
in your openclaw.json bootstrap files). The agent will read it and deliver a briefing.
On fresh install it will say: "System is ready. No active projects running yet."

Tell it what to work on, or add a project row to ACTIVE-PROJECTS.md first.

---

## Step 5 — Configure Two Crons

**Before creating crons, set the timeout:**

```bash
openclaw config set agents.defaults.timeoutSeconds 600
```

### Cron 1: Worker (every 3 hours)

The worker model is managed automatically by NightClaw — no `--model` flag needed. At the end of each session NightClaw reads the dispatched project's `next_pass.model_tier` from `MODEL-TIERS.md` and sets the platform default for the next fire. The worker cron inherits that default. Set your initial model before creating the cron:

```bash
openclaw models set <your-starting-model-id>   # e.g. openai/gpt-4o
openclaw config apply
```

```bash
openclaw cron add \
  --name "nightclaw-worker-trigger" \
  --every 3h \
  --session "session:nightclaw-worker" \
  --message "HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-WORKER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps." \
  --light-context \
  --no-deliver
# No --model flag — NightClaw manages this automatically via MODEL-TIERS.md
```

### Cron 2: Manager (once per day)

The manager uses a heavy model for judgment and direction-setting. Once per day is sufficient — the manager reviews accumulated worker passes, detects crashes, surfaces escalations, and sets strategic direction. Running more frequently burns expensive model tokens on repeated "no changes" results.

```bash
openclaw cron add \
  --name "nightclaw-manager-trigger" \
  --every 24h \
  --session "session:nightclaw-manager" \
  --message "HARD LINES ACTIVE: never post externally, never write outside workspace, never modify cron schedule, employment constraint enforced (see USER.md). Step 1: READ orchestration-os/CRON-HARDLINES.md. Step 2: READ orchestration-os/CRON-MANAGER-PROMPT.md. Step 3: Follow it exactly from T0 through T9. Do not improvise steps." \
  --light-context \
  --no-deliver \
  --model <manager-model-id>
```

### Why custom named sessions

Two confirmed OpenClaw bugs make both obvious choices unreliable:
- `--session isolated`: agentTurn timeout bug (#42632) — hangs even on minimal prompts
- `--session main`: busy-skip bug (#10538) — silently skipped when main lane is active

Custom named sessions (`session:xxx`) avoid both. Combined with `--light-context`,
they start lean and build context only from what they explicitly read.

### Verify

```bash
openclaw cron list
```

Force-run to test:
```bash
openclaw cron run [worker-trigger-id]
```

Then check:
```bash
cat {WORKSPACE_ROOT}/memory/$(date +%Y-%m-%d).md
```

A structured log entry means it worked.

---

## Token Budget Baseline

Session startup floor: ~6,900 tokens (SOUL + AGENTS + WORKING + ACTIVE-PROJECTS).
Cron pass startup: ~2,400 additional tokens (CRON-HARDLINES + REGISTRY R3+R5).

**Small monthly budget guidance:** At 3-hour worker intervals (8 passes/day on a cheap execution-class model) + 1 manager pass/day (on a more capable judgment-class model) + 1 heartbeat/day (cheap), the system fits comfortably within a small OAuth budget. The deterministic ops toolkit (`scripts/nightclaw-ops.py`) eliminates ~120K tokens/day of LLM reasoning that code handles instead — integrity checks, dispatch, crash detection, timing, pruning, and audit are all script output, not model computation.

**Model assignment matters more than frequency.** The worker should run on the cheapest capable model because its job is structured execution — read script output, follow instructions, write results. The manager should run on a more capable model because its job is judgment — quality evaluation, strategic direction, anomaly interpretation. Running both on the same model either wastes money (worker over-spec'd) or degrades governance (manager under-spec'd). NightClaw is model-agnostic — choose the specific IDs that suit your provider.

`--light-context` is essential — prevents context accumulation across runs.
`--model` on each cron is essential — prevents both crons from inheriting whatever default model is configured.

---

## Heartbeat Configuration (Critical for Cost Control)

OpenClaw's heartbeat fires periodic agent turns in the main session. **The default configuration will silently drain your token budget.** Default interval is 30 minutes (48 calls/day), running on whatever model your agent defaults to, with full conversation history and all bootstrap files loaded.

NightClaw's cron worker and manager run in their own dedicated sessions — they do not depend on the heartbeat. The heartbeat's only job is a lightweight daily health check. It does not need an expensive model, frequent runs, or full session context.

**Recommended heartbeat configuration** (add to `openclaw.json`):

```json
{
  "agents": {
    "defaults": {
      "heartbeat": {
        "every": "24h",
        "model": "<worker-model-id>",
        "lightContext": true,
        "isolatedSession": true,
        "activeHours": {
          "start": "07:00",
          "end": "23:00"
        }
      }
    }
  }
}
```

Or apply via CLI:

```bash
openclaw config set agents.defaults.heartbeat.every "24h"
openclaw config set agents.defaults.heartbeat.model "<worker-model-id>"
openclaw config set agents.defaults.heartbeat.lightContext true
openclaw config set agents.defaults.heartbeat.isolatedSession true
openclaw gateway restart   # or: openclaw gateway stop && openclaw gateway
```

**What each setting does:**

| Setting | Default | Recommended | Why |
|---|---|---|---|
| `every` | 30m (48/day) | 24h (1/day) | The worker and manager crons handle all monitoring — the heartbeat is just a daily safety net |
| `model` | Agent default (often a judgment-class model) | A cheap execution-class model | Often ~5x cheaper per call — heartbeat checks are trivial |
| `lightContext` | false | true | Only injects HEARTBEAT.md, not full workspace bootstrap |
| `isolatedSession` | false | true | Fresh session each tick — no conversation history (~100K → ~2-5K tokens) |
| `activeHours` | none (24/7) | 07:00–23:00 | Ensures the daily tick fires during waking hours |

**Without these settings**, a judgment-class heartbeat at 30m intervals with full session context can consume more tokens than all your cron passes combined — potentially $10-15/day in API costs for checks that produce `HEARTBEAT_OK` 95% of the time.

**Important:** NightClaw's HEARTBEAT.md contains only lightweight checks. It does **not** route cron worker or manager passes — those run in their own dedicated sessions via `openclaw cron`. If your HEARTBEAT.md contains a "Cron Trigger Handling" section that routes `WORKER_PASS_DUE` or `MANAGER_PASS_DUE` events, remove it. That pattern duplicates cron execution in the main session context at full cost.

**Or disable the heartbeat entirely.** NightClaw's operational loop is the two `openclaw cron` triggers above — the worker and the manager. Those run in dedicated named sessions and do **not** depend on the heartbeat. Turning the heartbeat off is a supported configuration:

```bash
openclaw system heartbeat disable
```

With the heartbeat disabled you keep the full cron-driven loop, the audit trail, integrity verification, and all `nightclaw-admin` commands. The only thing you lose is the lightweight daily check that HEARTBEAT.md performs — and in practice those checks are redundant with what the manager pass does anyway. Pick the narrowed-heartbeat configuration if you want a zero-effort safety net; pick the disabled configuration if you want the smallest possible token footprint. Either is fine.

---

## Model Tier Switching

NightClaw automatically switches the worker model between sessions based on each project's `next_pass.model_tier`. No owner action is needed after initial setup.

**How it works:**
1. Each project's `LONGRUNNER.md` declares `next_pass.model_tier: lightweight | standard | heavy`
2. The worker sets this at T6 via `BUNDLE:longrunner_update` after each pass
3. At T9.5 (after session close), the worker calls `python3 scripts/nightclaw-ops.py set-model-tier <tier>`
4. The engine reads `MODEL-TIERS.md`, resolves the model ID, and runs:
   - `openclaw models set <model-id>` — writes to platform config
   - `openclaw config apply` — signals gateway hot reload (takes effect within seconds)
   - `openclaw config get agents.defaults.model.primary` — verifies the switch
5. The next worker cron fires (no `--model` flag) and inherits the updated platform default

**The manager is never affected** — it carries a hardcoded `--model` flag that overrides the platform default.

**One-pass lag is by design.** The switch happens at the end of the current session, so the next session runs on the correct model. This is the only safe moment — the model for the current session is already instantiated.

**Setup:** `install.sh` prompts for all three model IDs and writes `MODEL-TIERS.md`. To change a mapping later, edit `MODEL-TIERS.md` directly — no cron changes needed.

**Verify a switch took effect:**
```bash
openclaw config get agents.defaults.model.primary
```

**If switching is not working:** check `audit/AUDIT-LOG.md` for `WARN:SET_MODEL_TIER` lines. Common causes: `MODEL-TIERS.md` has unfilled placeholders, `openclaw` is not in PATH inside the session, or `openclaw config apply` needs a gateway restart (run `openclaw gateway restart` once to recover).

---

## Model Configuration

**Recommended provider:** OpenAI OAuth (ChatGPT Plus or Pro subscription).
Works immediately after `openclaw models auth login --provider openai-codex`.
No API key required. Quota is sufficient for normal overnight operation.

**Google Gemini (API key):** Supported. Use `google/gemini-2.5-flash` as the default model.
`google/gemini-2.5-pro` may return a thinking mode error depending on your OpenClaw version
and API configuration — flash is the safe choice.

```bash
# Set recommended model
openclaw models set google/gemini-2.5-flash

# Add API key
openclaw models auth add
# Provider: google
# Paste your AIza... key from aistudio.google.com/apikey
```

**Troubleshooting model errors:**

| Error | Cause | Fix |
|---|---|---|
| `Budget 0 is invalid. This model only works in thinking mode` | Using `gemini-2.5-pro` without thinking budget | Switch to `google/gemini-2.5-flash` |
| `You have hit your ChatGPT usage limit` | OpenAI Plus plan quota exhausted | Wait for reset (~24h) or add Gemini as fallback |
| `No API key found for provider google` | Key saved to global config but not agent auth store | Run `openclaw models auth paste-token --provider google --profile-id google:manual` |
| `All models failed: overloaded` | Provider capacity issue | Wait 2–3 minutes and retry |

---

## Day-to-Day Operation

**The `nightclaw-admin` CLI handles all routine management without spending tokens:**

```bash
# Morning check
bash scripts/nightclaw-admin.sh status       # what's active, what phase, next objective
bash scripts/nightclaw-admin.sh alerts        # unresolved notifications

# Act on cron results
bash scripts/nightclaw-admin.sh approve <slug>          # approve a pending project draft
bash scripts/nightclaw-admin.sh decline <slug> [reason]  # decline and delete a draft
bash scripts/nightclaw-admin.sh done <line-number>       # resolve a notification
bash scripts/nightclaw-admin.sh guide <message>          # inject guidance for next worker pass

# Manage projects
bash scripts/nightclaw-admin.sh pause <slug>             # pause a project
bash scripts/nightclaw-admin.sh unpause <slug>           # resume a paused project
bash scripts/nightclaw-admin.sh priority <slug> <n>      # change priority

# Overnight control
bash scripts/nightclaw-admin.sh arm PA-001 2026-04-11    # activate pre-approval (auto re-signs)
bash scripts/nightclaw-admin.sh disarm PA-001            # deactivate (auto re-signs)

# Audit
bash scripts/nightclaw-admin.sh log [n]                  # last n audit entries
```

All admin commands log to `audit/AUDIT-LOG.md` and `audit/CHANGE-LOG.md` in the same format the cron sessions use. The audit trail is complete regardless of whether a human or a cron made the change.

**You can also use a main agent session** for anything that requires reasoning — but routine approvals, pauses, and priority changes are mechanical file operations that the admin CLI handles at zero token cost.

**Additional operations:**
- **Add a project:** `bash scripts/new-project.sh <slug>` — scaffolds everything in one command
- **Shift focus:** `bash scripts/nightclaw-admin.sh priority <slug> <n>` or edit ACTIVE-PROJECTS.md directly
- **Approve a phase transition:** `bash scripts/nightclaw-admin.sh approve <slug>` or tell the agent in a main session
- **Re-sign after editing a protected file:** `bash scripts/resign.sh <file>` — updates the manifest automatically
- **Emergency stop:** Set all ACTIVE-PROJECTS.md rows to `paused`

---

## Before Your First Overnight Run

By default the system runs in **conservative mode** — research passes execute freely, but phase transitions and idle cycle autonomy require pre-authorization. For unattended overnight operation, activate the two built-in pre-approvals:

```bash
nano ~/.openclaw/workspace/orchestration-os/OPS-PREAPPROVAL.md
```

Find `PA-001` and `PA-002`. For each:
1. Change `Status: INACTIVE` to `Status: ACTIVE`

**OPS-PREAPPROVAL.md is a protected file.** After editing, re-sign it:
```bash
bash scripts/resign.sh orchestration-os/OPS-PREAPPROVAL.md
```

Do the same each morning when you change the PAs back to INACTIVE.
2. Set `Expires:` to tomorrow’s date (e.g. `2026-04-08 08:00`)

That’s it. With both active:
- Worker auto-advances phases to TRANSITION-HOLD when stop conditions are met
- Idle cycle drafts new project proposals from your Domain Anchor when all projects are blocked
- System never halts on recoverable blockers — always finds something valuable to do (integrity failures halt by design)

In the morning, change both back to `INACTIVE`, then re-sign:
```bash
bash scripts/resign.sh orchestration-os/OPS-PREAPPROVAL.md
```

---

## Deployment Complete

Once both crons are running and first session confirms clean, the system is self-documenting.
Check `NOTIFICATIONS.md` each morning — that is your primary interface from here.

---

## Uninstall & Emergency Stop

Follow these in order. Steps 1–3 are the safe graceful path. Step 4 is
a hard kill and will leave orphan audit entries — only use it when the
system is actively doing something you need to interrupt *now*.

### 1. Pause autonomous work (no data loss)

```bash
# Pause every active project one at a time. nightclaw-admin does not
# have a bulk pause-all subcommand by design — each pause writes an
# audit entry naming the slug.
bash scripts/nightclaw-admin.sh status          # see current slug + status
bash scripts/nightclaw-admin.sh pause <slug>    # repeat per active slug
```

If the admin CLI is unavailable, edit `ACTIVE-PROJECTS.md` manually and
set the `status` column on every row to `paused`.

### 2. Disarm any ACTIVE pre-approvals

```bash
# Open OPS-PREAPPROVAL.md, flip every ACTIVE row to INACTIVE, then re-sign.
nano orchestration-os/OPS-PREAPPROVAL.md
bash scripts/resign.sh orchestration-os/OPS-PREAPPROVAL.md
```

With every PA inactive, the worker cron will stop at any
pre-approval-gated boundary on the next tick.

### 3. Delete or disable the crons

```bash
openclaw cron list
openclaw cron delete <worker-cron-id>
openclaw cron delete <manager-cron-id>
```

After this step OpenClaw will not fire NightClaw again until you
recreate the crons.

### 4. (Optional) Remove the workspace entirely

Only do this after step 3 has deleted the crons. Otherwise OpenClaw
will try to run NightClaw against a path that no longer exists and log
errors every interval.

```bash
# Confirm no crons remain targeting the workspace.
openclaw cron list

# Archive the workspace first if you may want its audit trail later.
tar -czf "$HOME/nightclaw-archive-$(date +%Y%m%d).tgz" "$HOME/.openclaw/workspace"

# Then remove.
rm -rf "$HOME/.openclaw/workspace"
```

NightClaw does not install anything system-wide — no systemd unit, no
`/etc` entries, no symlinks outside `$HOME`. Removing
`$HOME/.openclaw/workspace` plus the two crons is a complete uninstall.

OpenClaw itself is not touched by this procedure. If you want to
uninstall OpenClaw too, follow the upstream OpenClaw uninstall guide.

### 5. Hard kill (last resort)

If a cron is currently executing and you need it to stop *now*:

```bash
# Find the running openclaw session.
pgrep -af openclaw

# Terminate it. Use TERM first; only use KILL if TERM doesn't work.
pkill -TERM -f "openclaw.*nightclaw"
```

After a hard kill, the next session may find `LOCK.md` in an
inconsistent state. Diagnose it with `python3 scripts/check-lock.py`;
if the lock is stale, the next scheduled pass can clear it through the
normal stale-lock path. Use `orchestration-os/OPS-FAILURE-MODES.md`
for the documented recovery class before applying any manual fix.
