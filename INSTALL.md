# NightClaw — Install Guide

## What This Is

An orchestration framework for OpenClaw. Drop it into your workspace.
Every agent session runs inside a structured envelope: integrity-verified instructions,
append-only audit trail, write discipline, approval chains, and behavioral discipline contracts.

## Automated Install (Recommended)

```bash
# 1. Copy into your OpenClaw workspace
cp -r nightclaw-v0.1.0-release/* ~/.openclaw/workspace/

# 2. Run the install script
cd ~/.openclaw/workspace
bash scripts/install.sh
```

The install script will prompt for your configuration values, substitute all placeholders,
and generate the initial integrity hashes.

**Input sanitization note:** All values entered during install must contain only
alphanumeric characters, hyphens, underscores, forward slashes, periods, and tildes. Do not
include shell metacharacters (spaces, quotes, pipes, semicolons, dollar signs, backticks,
etc.) in any configuration value.

## Placeholders

Before first use (or during install script), replace these values throughout the workspace:

| Placeholder | Replace with |
|---|---|
| `{OWNER}` | Your name or handle (e.g., `alice`) |
| `{WORKSPACE_ROOT}` | Your OpenClaw workspace path (default: `~/.openclaw/workspace`) |
| `{OPENCLAW_CRON_DIR}` | Your OpenClaw cron directory (default: `~/.openclaw/cron`) |
| `{OPENCLAW_LOGS_DIR}` | Your OpenClaw logs directory (default: `~/.openclaw/logs`) |
| `{PLATFORM}` | Your execution platform (e.g., `Ubuntu/WSL2`, `macOS`, `Linux`) |
| `{INSTALL_DATE}` | Today's date in `YYYY-MM-DD` format |
| `{DOMAIN_ANCHOR}` | Your domain focus — **set manually in `SOUL.md` §Domain Anchor; not substituted by the install script** |

### Manual substitution (if not using install script)

Run from your workspace root after copying files:

```bash
OWNER="yourname"
WORKSPACE_ROOT="$HOME/.openclaw/workspace"
CRON_DIR="$HOME/.openclaw/cron"
LOGS_DIR="$HOME/.openclaw/logs"
PLATFORM="Ubuntu/WSL2"
INSTALL_DATE=$(date +%Y-%m-%d)

# Values must be alphanumeric, hyphens, underscores, forward slashes, periods, and tildes only.
# No spaces — spaces break sed substitutions and shell path operations.
find . -name "*.md" -exec sed -i \
  -e "s|{OWNER}|$OWNER|g" \
  -e "s|{WORKSPACE_ROOT}|$WORKSPACE_ROOT|g" \
  -e "s|{OPENCLAW_CRON_DIR}|$CRON_DIR|g" \
  -e "s|{OPENCLAW_LOGS_DIR}|$LOGS_DIR|g" \
  -e "s|{PLATFORM}|$PLATFORM|g" \
  -e "s|{INSTALL_DATE}|$INSTALL_DATE|g" \
  {} \;

# {DOMAIN_ANCHOR} is NOT substituted by this command.
# After the above runs, open SOUL.md and manually replace the Domain Anchor
# section with your own domain focus, consulting practice, or primary use case.
```

## First-Sign (Required)

`install.sh` generates the initial SHA-256 integrity hashes automatically as its final step
and writes them into `audit/INTEGRITY-MANIFEST.md`. No manual paste is needed.

If you ran install.sh, verify it completed successfully:

```bash
bash scripts/verify-integrity.sh
```

All 11 protected files should show `PASS`. If any show `FAIL`, re-run `install.sh` or
manually run `bash scripts/resign.sh` to regenerate the manifest.

This is the only step that requires your direct involvement — the agent handles everything
else from here.


## Model Setup (Required Before Crons)

NightClaw requires a working LLM provider. Crons will fail silently if no model is configured.

```bash
# Check what's currently configured
openclaw models status
```

**Option A — OpenAI OAuth (ChatGPT Plus/Pro, recommended):**
```bash
openclaw models auth login --provider openai-codex
# Follow the browser authentication flow
openclaw models set openai-codex/gpt-5.3-codex
```

**Option B — Google Gemini API key:**
```bash
# Get a free API key at aistudio.google.com/apikey
openclaw models auth add
# Provider: google
# Paste your AIza... key
openclaw models set google/gemini-2.5-flash
```

Verify it works:
```bash
openclaw agent --agent main -m "say hi"
```

The agent should respond using your configured model. If it falls back to a different model or errors, see `TROUBLESHOOTING.md § Issue: passes keep failing`.

---

## Cron Setup

```bash
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

## Validation

Run the validation script to check internal consistency:

```bash
bash scripts/validate.sh
```

This verifies that all files referenced in REGISTRY.md exist, all protected files are
listed in INTEGRITY-MANIFEST.md, and all cross-references resolve.

## What You Get Immediately

- Every agent session verifies the integrity of its own instruction files before acting
- Every file write is gated through a pre-write protocol (PW-1 through PW-5)
- Every autonomous action is checked against a scope escalation test
- Append-only audit trail from the first session
- Approval chain linking {OWNER} authorization to agent action to audit entry
- Emergency kill switch active from install

Full deployment details: [`DEPLOY.md`](DEPLOY.md)
