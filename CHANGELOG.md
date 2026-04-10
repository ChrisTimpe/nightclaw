<!-- Future entry format:
## vX.Y.Z — [short description]
**Released:** YYYY-MM-DD
### Fixes
- **Item**: description
### Enhancements
- **Item**: description
-->

# CHANGELOG

All notable changes to NightClaw will be documented here.

---

## v0.2.0 — Deterministic Operations + Owner CLI

**Released:** 2026-04-10

### New: nightclaw-admin CLI
- **Owner CLI** (`scripts/nightclaw-admin.sh`): manage the system from the terminal without spending tokens
  - `status` / `alerts` / `log` — read system state
  - `approve` / `decline` — act on project drafts
  - `pause` / `unpause` / `priority` — manage active projects
  - `guide` — inject guidance the worker picks up at T1.5
  - `arm` / `disarm` — toggle pre-approvals with automatic re-signing
  - `done` — resolve notifications
  - All commands log to audit/AUDIT-LOG.md and audit/CHANGE-LOG.md in the same format the cron sessions use

### New: Deterministic ops commands (nightclaw-ops.py)
- **longrunner-extract** — extracts routing fields without full LONGRUNNER file read
- **idle-triage** — deterministic idle cycle prerequisite check
- **strategic-context** — pre-digests manager T3.5 inputs with A/B/C/D routing
- **t7-dedup** — fuzzy word-overlap dedup against existing entries
- **crash-context** — retrieves project/objective/crash history for recovery
- **scan-notifications** rewritten — structural matching, section-scoped, skips code block templates

### Enhancements
- Cron prompts (worker + manager) updated to route through new ops commands
- `--message` in cron command blocks trimmed from ~200 to ~30 tokens
- REGISTRY.md: R2 field contracts added for 7 objects (NOTIFY-ARCH, MEMORY, REGISTRY, TOOLREG, LESSONS, LOCK, FM)
- REGISTRY.md: CL5 PROTECTED-PATHS now includes AGENTS-CORE.md
- All doc references to approval flow updated to mention nightclaw-admin CLI

### Cost Impact
- ~30-40% reduction in per-pass tokens from deterministic command routing
- Zero-token owner management via nightclaw-admin CLI
- Projected daily cost: ~$0.40-0.70 (down from ~$0.65-1.06) during active work

---

## v0.1.0 — Initial Public Release

**Released:** 2026-04-07

First public release. All development hardening from internal versions v0.001 and v0.001.1 is included. See sections below for full history.

### What's included
- Complete autonomous overnight orchestration framework for OpenClaw
- LONGRUNNER project lifecycle with phase transitions and human approval gates
- SHA-256 integrity manifest covering all protected governance files
- Session lock protocol with stale detection and orphan guard
- Indexed failure mode registry (continuously growing) with behavioral prevention
- Pre-approval system (PA-001, PA-002) for overnight autonomy
- Morning-check workflow via NOTIFICATIONS.md
- Self-healing audit trail (AUDIT-LOG, SESSION-REGISTRY, CHANGE-LOG)
- Autonomous project proposal from Domain Anchor (Tier 4 idle cycle)
- 8 scripts: install, validate, resign, upgrade, new-project, check-lock, verify-integrity, smoke-test
- TROUBLESHOOTING.md with lock reset, integrity recovery, and manual testing procedures
- 96 validation checks

---

## v0.001.1 — Pre-Public Hardening (internal)

**Released:** 2026-04-06

### Fixes

- **CI/PR trust model clarified** — `CONTRIBUTING.md` and `PULL_REQUEST_TEMPLATE.md` now explicitly distinguish the two roles of `INTEGRITY-MANIFEST.md`: (1) the per-deployment signed record users maintain, and (2) the template hash maintainers keep current in the repo. These are separate operations and must not be conflated.
- **Unfilled placeholder detection added to `validate.sh`** — Check 7 now scans runtime files for unsubstituted `{OWNER}`, `{WORKSPACE_ROOT}`, and related tokens. A failed or partial install now reports a clear failure instead of reaching T0 and failing opaquely with a Python `FileNotFoundError`. CI workflow updated with a pre-substitution step so the check passes correctly in the uninstalled repo state.
- **`UPGRADING.md` added** — Documents the upgrade path for live deployments. Classifies every file into Category A (safe to overwrite), B (merge required — agent-extended), C (review before overwriting — protected), and D (never overwrite — deployment identity). Includes step-by-step procedure, cron recreation guidance, and emergency rollback instructions.
- **Six-frame review audit trail formalized** — `SOUL.md §1b` now requires an `AUDIT-LOG.md` entry (`TYPE:IMPACT_PLAN`, step `.SFR`) before any PROTECTED-tier or R4-SOURCE write. Format defined. `CRON-WORKER-PROMPT.md` updated to reference the logging obligation at Tier 2B and T4. `REGISTRY.md` R2 updated with the SFR type and its format. A write with no preceding SFR entry is now a classified protocol violation.
- **`OPS-IDLE-CYCLE.md` Tier 1 fallback added** — Tier 1 now has an explicit prerequisite block: if `[knowledge-repo]` is not configured, skip Tier 1 entirely and proceed to Tier 2. Each sub-step (1a, 1b, 1c) has a directory/file existence check with a defined skip path. Demand signals found during 1c are routed to `NOTIFICATIONS.md` when no knowledge-repo is configured. Fresh installs now have a defined, non-halting idle cycle behavior.
- **`UPGRADING.md` added to `validate.sh` EXPECTED_FILES** — now included in the 92 validation checks.


### Enhancements

- **First-project experience** — `WORKING.md` now gives real instructions instead of a phantom `/new-project` command. README has a new `## Your First Project` section with Option A (agent-assisted) and Option B (manual) paths. `NOTIFICATIONS.md` install notice is now a numbered action checklist.
- **Example LONGRUNNER** — `PROJECTS/example-research/LONGRUNNER.md` ships as a fully filled-in reference project (web research). Clearly marked as example-only. No effect on system unless added to `ACTIVE-PROJECTS.md`.
- **FM-030 added** — `light-context-version-mismatch`: documents the OpenClaw PR #60776 bug where `--light-context` failed to skip bootstrap injection on versions prior to `2026.4.5`. Detection signal, fix, and prevention documented.
- **Bootstrap file size monitoring** (Check 8 in `validate.sh`) — warns at 16,000 chars, fails at 20,000 chars. Catches silent truncation before deployment. Also checks 150,000-char aggregate cap.
- **OpenClaw version check** (Check 9 in `validate.sh`, warn-only) — flags if `openclaw` is in PATH but below `2026.4.5`. Skips gracefully in CI where OpenClaw is not installed.
- **`NOTIFICATIONS.md` archival gap closed** — header claim of automated T8 archival removed. Manual archival is the correct documented approach.
- **`UPGRADING.md` Protected File Changes table populated** — documents all four protected-file changes from v0.001.1 fixes with re-sign requirement.
- **Validation checks: 92** (was 83) — 9 new checks across bootstrap file sizes, aggregate cap, and OpenClaw version.

---

## v0.001 — Initial Public Release

**Released:** 2026-04-05

### Orchestration Framework (Part 1)

- Append-only audit trail: AUDIT-LOG, SESSION-REGISTRY, CHANGE-LOG, APPROVAL-CHAIN
- SHA-256 integrity manifest covering all protected governance files — session-level drift detection
- LONGRUNNER project lifecycle — explicit pass boundaries, stop conditions, phase history, retry state
- Indexed failure mode registry with root cause, detection signal, fix, and prevention (grows during operation)
- Self-healing blocker decision tree — diagnose before retrying, never halt on recoverable blockers (integrity failures halt by design)
- Session lock (LOCK.md) — mutex preventing concurrent worker/manager cron overlap
- T7 OS Improvement Gate — G1 (non-obvious) + G2 (generalizable) gate before any OS file write
- TRANSITION-HOLD timeout — 3-day default, CRITICAL re-escalation × 3, then auto-pause
- Async proposal surface (NOTIFICATIONS.md) — agent appends, owner reviews at morning check
- Pre-approval system for unattended overnight operation
- Two-cron orchestration: worker (3h on Haiku) + manager (24h on Sonnet) — model assignment and frequency tuned for $20/mo OAuth budgets
- REGISTRY.md dual-tier write routing — append vs. structural operations explicitly separated
- Behavioral discipline (Hard Lines as agent identity — not enforced security)
- Pre-write protocol: scope check → dependency read → write → audit (PW-1 through PW-5)
- AGENTS split: AGENTS-CORE.md (PROTECTED, manifest-tracked) + AGENTS-LESSONS.md (T7d target) + AGENTS.md (nav index)

### ETL Skill Layer (Part 2 — Proof of Concept)

- OPS-KNOWLEDGE-EXECUTION.md demonstrates skill-attachment pattern
- Agent reads field maps before writing code — confirmed knowledge, not inference
- Agent extends maps after successful runs — compounding accuracy over time
- Replace provided examples with field maps for your own systems

---

*See README.md for full description and quick start.*
