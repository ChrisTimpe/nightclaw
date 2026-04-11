# UPGRADING.md — Upgrade Guide for Deployed Workspaces

<!-- This file is for users upgrading an existing live NightClaw deployment. -->
<!-- If you are a contributor modifying the repository, see CONTRIBUTING.md. -->

---

## The Core Constraint

NightClaw is not a library you update with a package manager. It is a **stateful, living workspace**. After weeks or months of operation, your deployment is a customized fork:

- `AGENTS-LESSONS.md` contains lessons written by your agent from real passes
- `orchestration-os/OPS-FAILURE-MODES.md` contains failure modes discovered in your environment
- `orchestration-os/OPS-TOOL-REGISTRY.md` contains tool constraints specific to your platform
- `orchestration-os/OPS-KNOWLEDGE-EXECUTION.md` contains field maps your agent has extended
- `audit/` files are your audit trail — append-only, never overwritten
- `PROJECTS/` contains your live LONGRUNNERs and all project state

**Pulling upstream changes blindly will overwrite your runtime knowledge.** This guide tells you which files to overwrite, which to merge, and which to leave entirely alone.

---

## Before You Start

```bash
# 1. Pause all projects — no cron passes during upgrade
# For each active project:
nightclaw-admin pause [slug]

# 2. Verify the system is idle
openclaw cron list   # confirm both crons are still configured
cat LOCK.md          # confirm status: released

# 3. Backup your workspace
cp -r ~/.openclaw/workspace ~/.openclaw/workspace-backup-$(date +%Y-%m-%d)

# 4. Note your current version
cat VERSION
```

---

## File Classification

Every file in a NightClaw workspace falls into one of four upgrade categories:

### Category A — Safe to overwrite (framework files, no runtime state)
These contain only framework logic. Your agent never writes to them. Upstream improvements here are safe to pull directly.

```
orchestration-os/START-HERE.md
orchestration-os/ORCHESTRATOR.md
orchestration-os/OPS-CRON-SETUP.md
orchestration-os/OPS-PASS-LOG-FORMAT.md
orchestration-os/LONGRUNNER-TEMPLATE.md
orchestration-os/PROJECT-SCHEMA-TEMPLATE.md
HEARTBEAT.md
WORKING.md
INSTALL.md
DEPLOY.md
README.md
CONTRIBUTING.md
CHANGELOG.md
CODE_OF_CONDUCT.md
SECURITY.md
LICENSE
VERSION
scripts/install.sh
scripts/validate.sh
scripts/verify-integrity.sh
scripts/nightclaw-admin.sh
scripts/nightclaw-ops.py
.github/
```

### Category B — Merge required (agent-extended files)
These files are extended by your agent during operation. Upstream may add new entries. You must merge — never blindly overwrite.

```
orchestration-os/OPS-FAILURE-MODES.md    ← your FM-034+ entries must be preserved (FM-001 through FM-033 are base framework entries)
orchestration-os/OPS-TOOL-REGISTRY.md    ← your platform-specific tool constraints
orchestration-os/OPS-KNOWLEDGE-EXECUTION.md  ← your extended field maps
orchestration-os/OPS-QUALITY-STANDARD.md    ← domain-specific calibration you may have added
orchestration-os/OPS-IDLE-CYCLE.md          ← if you customized idle cycle tiers
AGENTS-LESSONS.md                           ← lessons your agent has written
```

**Merge protocol:** Diff upstream against your copy. Add any new upstream entries at the top of the relevant section. Preserve all entries your agent has written. Never delete existing entries — they are the system's operational memory.

### Category C — Review before overwriting (protected files with behavioral contracts)
These are in the integrity manifest. Upstream changes reflect protocol improvements. Review the diff carefully before accepting — these files govern how your agent behaves.

```
SOUL.md
AGENTS-CORE.md
orchestration-os/CRON-WORKER-PROMPT.md
orchestration-os/CRON-MANAGER-PROMPT.md
orchestration-os/CRON-HARDLINES.md
orchestration-os/OPS-PREAPPROVAL.md
orchestration-os/OPS-AUTONOMOUS-SAFETY.md  (also in Category B if you extended it)
orchestration-os/REGISTRY.md
```

After accepting any Category C file: **re-sign the manifest.**

### Category D — Never overwrite (your deployment's identity and state)
These are yours. Upstream never has meaningful versions of these because they contain your personal configuration and live state.

```
SOUL.md §Domain Anchor          ← your domain focus
USER.md                         ← your profile and domain restrictions
IDENTITY.md                     ← your agent's identity
MEMORY.md                       ← your agent's long-term memory
LOCK.md                         ← runtime state
ACTIVE-PROJECTS.md              ← your project dispatch table
NOTIFICATIONS.md                ← your pending notifications
TOOLS.md                        ← your environment specifics
PROJECTS/                       ← all your project state (never touch)
audit/                          ← your audit trail (never touch)
memory/                         ← your daily logs (never touch)
```

---

## Step-by-Step Upgrade Procedure

### Step 1 — Download the new release
```bash
cd /tmp
# Download from https://github.com/ChrisTimpe/nightclaw/releases
# or clone: git clone https://github.com/ChrisTimpe/nightclaw nightclaw-new
unzip nightclaw-vX.XXX-release.zip -d nightclaw-new
```

### Step 2 — Overwrite Category A files
```bash
WS=~/.openclaw/workspace
NEW=/tmp/nightclaw-new/nightclaw-vX.XXX-release

# Safe overwrites
cp $NEW/orchestration-os/START-HERE.md $WS/orchestration-os/
cp $NEW/orchestration-os/ORCHESTRATOR.md $WS/orchestration-os/
cp $NEW/orchestration-os/OPS-CRON-SETUP.md $WS/orchestration-os/
cp $NEW/orchestration-os/OPS-PASS-LOG-FORMAT.md $WS/orchestration-os/
cp $NEW/orchestration-os/LONGRUNNER-TEMPLATE.md $WS/orchestration-os/
cp $NEW/orchestration-os/PROJECT-SCHEMA-TEMPLATE.md $WS/orchestration-os/
cp $NEW/HEARTBEAT.md $WS/
cp $NEW/WORKING.md $WS/
cp $NEW/INSTALL.md $WS/
cp $NEW/DEPLOY.md $WS/
cp $NEW/README.md $WS/
cp $NEW/CONTRIBUTING.md $WS/
cp $NEW/UPGRADING.md $WS/
cp $NEW/CHANGELOG.md $WS/
cp $NEW/CODE_OF_CONDUCT.md $WS/
cp $NEW/SECURITY.md $WS/
cp $NEW/LICENSE $WS/
cp $NEW/VERSION $WS/
cp -r $NEW/scripts/ $WS/
cp -r $NEW/.github/ $WS/
```

### Step 3 — Merge Category B files
```bash
# For each file, diff and manually merge upstream additions
diff $NEW/orchestration-os/OPS-FAILURE-MODES.md $WS/orchestration-os/OPS-FAILURE-MODES.md
diff $NEW/orchestration-os/OPS-TOOL-REGISTRY.md $WS/orchestration-os/OPS-TOOL-REGISTRY.md
diff $NEW/orchestration-os/OPS-KNOWLEDGE-EXECUTION.md $WS/orchestration-os/OPS-KNOWLEDGE-EXECUTION.md
diff $NEW/orchestration-os/OPS-QUALITY-STANDARD.md $WS/orchestration-os/OPS-QUALITY-STANDARD.md
diff $NEW/AGENTS-LESSONS.md $WS/AGENTS-LESSONS.md
```
Add new upstream content (new failure modes, new field map sections, new quality patterns) to your copy. Do not overwrite your runtime-written entries.

### Step 4 — Review and accept Category C files
```bash
# Review each diff carefully before accepting
diff $NEW/orchestration-os/CRON-WORKER-PROMPT.md $WS/orchestration-os/CRON-WORKER-PROMPT.md
diff $NEW/orchestration-os/CRON-MANAGER-PROMPT.md $WS/orchestration-os/CRON-MANAGER-PROMPT.md
diff $NEW/orchestration-os/CRON-HARDLINES.md $WS/orchestration-os/CRON-HARDLINES.md
diff $NEW/orchestration-os/REGISTRY.md $WS/orchestration-os/REGISTRY.md
diff $NEW/SOUL.md $WS/SOUL.md         # preserve your §Domain Anchor section
diff $NEW/AGENTS-CORE.md $WS/AGENTS-CORE.md
```
For SOUL.md: accept upstream changes to all sections except `§Domain Anchor` — keep your own text there.

### Step 5 — Re-sign the integrity manifest
After accepting any Category C file:
```bash
cd ~/.openclaw/workspace
bash scripts/verify-integrity.sh
# Update each changed hash in audit/INTEGRITY-MANIFEST.md
# Set Verified by to: yourname-re-signed-vX.XXX
```

### Step 6 — Run validation
```bash
bash scripts/validate.sh
# Must show: 0 failed. Warnings are non-blocking — review but do not block the upgrade on warnings.
```

### Step 7 — Test one cron cycle before re-enabling all projects
```bash
# Enable only one low-stakes project first
nightclaw-admin unpause [slug]

# Force-run the worker
openclaw cron run [worker-trigger-id]

# Verify the pass log
cat memory/$(date +%Y-%m-%d).md

# Check status
nightclaw-admin status

# If clean: re-enable remaining projects
```

---

## Protected File Changes

This section is maintained by contributors. When a PR modifies a protected file, a summary entry is added here so deployers know what changed and whether it affects their workflow.

| Version | File | What changed | Action required on upgrade |
|---------|------|-------------|--------------------------|
| v0.001 | — | Initial release | First-sign per INSTALL.md |
| v0.001.1 | `SOUL.md` | Added SFR audit log requirement to §1b; Hard Lines clarified | Re-sign manifest after pulling |
| v0.001.1 | `orchestration-os/CRON-WORKER-PROMPT.md` | T1 dispatch includes surfaced-* projects; SFR logging at Tier 2B and T4 | Re-sign manifest after pulling |
| v0.001.1 | `orchestration-os/CRON-HARDLINES.md` | Emergency kill switch: ACTIVE-PROJECTS.md edit is the primary mechanism | Re-sign manifest after pulling |
| v0.001.1 | `orchestration-os/REGISTRY.md` | SFR type added to TASK enum with format spec | Re-sign manifest after pulling |
| v0.001.1 | `orchestration-os/REGISTRY.md` | All BUNDLE audit log writes now say APPEND explicitly (FM-031 fix) | Re-sign manifest after pulling; run `sed -i 's/{OWNER}/[yourname]/g'` if pulled from zip |
| v0.001.1 | `orchestration-os/CRON-MANAGER-PROMPT.md` | T8 now includes explicit APPEND-ONLY callout for audit/AUDIT-LOG.md (FM-031 fix) | Re-sign manifest after pulling; run `sed -i 's/{OWNER}/[yourname]/g'` if pulled from zip |
| v0.2.0 | `orchestration-os/CRON-WORKER-PROMPT.md` | T1 dispatch routes through `nightclaw-ops.py` commands (scan-notifications rewrite, 5 new ops commands) | Re-sign manifest after pulling |
| v0.2.0 | `orchestration-os/CRON-MANAGER-PROMPT.md` | Manager dispatch routes through `nightclaw-ops.py` commands | Re-sign manifest after pulling |
| v0.2.0 | `orchestration-os/REGISTRY.md` | R2 read-contracts added for ops commands; CL5 count updated | Re-sign manifest after pulling |

---

## Cron Cadence After Upgrade

If `CRON-WORKER-PROMPT.md` or `CRON-MANAGER-PROMPT.md` changed:
- Delete and recreate both crons with the updated message text from `OPS-CRON-SETUP.md`
- The cron `--message` is the entry point — stale message text means the agent reads outdated routing instructions

```bash
openclaw cron list   # note IDs
openclaw cron delete [worker-id]
openclaw cron delete [manager-id]
# Recreate per OPS-CRON-SETUP.md §Cron 1 and §Cron 2
```

---

## Emergency Rollback

If a post-upgrade cron pass behaves unexpectedly:

```bash
# 1. Pause everything immediately
nightclaw-admin pause [slug]   # for each active project

# 2. Restore from backup
cp -r ~/.openclaw/workspace-backup-YYYY-MM-DD/* ~/.openclaw/workspace/

# 3. Re-sign (backup had valid hashes for the prior version)
bash scripts/verify-integrity.sh

# 4. Re-enable projects one at a time after confirming behavior
```

---

## Maintainer Release Checklist (cutting a new version)

Before tagging and publishing a new release:

1. **Bump `VERSION`** — update to the new version string (e.g., `v0.1.1 | YYYY-MM-DD | nightclaw-v0.1.1-release`)
2. **Add CHANGELOG entry** — add `## vX.Y.Z — [description]` at the top of CHANGELOG.md with `**Released:** YYYY-MM-DD` and the full change list
3. **Run validation** — `bash scripts/validate.sh` must show 0 failed
4. **Re-sign if any protected file changed** — run `bash scripts/resign.sh [file]` for each changed manifest file; confirm `bash scripts/verify-integrity.sh` shows 11/11
5. **Update Protected File Changes table** — document any protected file changes with re-sign requirement for upgrading users
6. **Update FM comment in Category B** — if new base FM entries were added, update `FM-NNN+ entries must be preserved` to the new last entry + 1
7. **Pack the zip** — `cd .. && zip -r nightclaw-vX.Y.Z-release.zip nightclaw-vX.Y.Z-release/`
8. **Tag and push** — `git tag -a vX.Y.Z -m "vX.Y.Z — [description]" && git push origin vX.Y.Z`
9. **Create GitHub Release** — from the tag at https://github.com/ChrisTimpe/nightclaw/releases; paste the CHANGELOG section as release notes; attach the zip as a release asset
