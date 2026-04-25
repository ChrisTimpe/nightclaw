# TOOL-STATUS.md

<!-- Fast pre-flight reference. ~200 tokens. Read this instead of OPS-TOOL-REGISTRY.md during worker passes. -->
<!-- Update this file whenever OPS-TOOL-REGISTRY.md changes. -->
<!-- Full detail, fallbacks, and approval requirements: OPS-TOOL-REGISTRY.md -->

## Quick Status Table

| Tool | Status | Key Constraint |
|------|--------|----------------|
| Web Search (DuckDuckGo) | CONSTRAINED | ~10–15 searches/session hard limit |
| OpenAI LLM | AVAILABLE | Flat-fee; use intentionally, batch high-token tasks |
| File System | AVAILABLE | Workspace root: `{WORKSPACE_ROOT}` |
| Python / Script (Ubuntu-sandbox) | AVAILABLE | No GUI; write progress to files, not stdout |
| SQLite / DuckDB | AVAILABLE | File-based; DuckDB preferred for flat file analytics |
| Python Exec (cron lane) | CONSTRAINED | exec allowlist blocks python3 in cron-event channel. Use interactive session for exec-gated passes. If your project requires exec in cron, add a PA entry in OPS-PREAPPROVAL.md before your first overnight run. |
| Static Web Fetch | AVAILABLE | No JS execution; blocked by Cloudflare on some sites |
| Playwright (headless) | UNVERIFIED | Needs `playwright install chromium` confirmed |
| Cron / Scheduler | AVAILABLE | OpenClaw native; phase-bound; delete when phase completes |
| Notifications | AVAILABLE | OpenClaw native; use sparingly |

## Context Note

Cron passes run with `--light-context` — ALL bootstrap files are skipped: SOUL.md, AGENTS.md, TOOLS.md, IDENTITY.md, USER.md, HEARTBEAT.md, and MEMORY.md are NOT injected (fix confirmed in OpenClaw 2026.4.5, PR #60776). This saves ~5,000 tokens per cycle at current file sizes. The cron task `--message` text is the full prompt entry point. Security boundaries are enforced by the task text and the first manual read of CRON-HARDLINES.md, not by auto-injected files.

---

## Pre-Flight Decision Rule

For the `next_pass` objective in the LONGRUNNER, identify which tools above are needed.

- All needed tools are `AVAILABLE` → proceed with the pass
- A needed tool is `CONSTRAINED` → check remaining budget before proceeding (log if near limit)
- A needed tool is `UNVERIFIED` → **stop**. Log gap in LONGRUNNER `blocked_reason`. Set ACTIVE-PROJECTS.md status to `blocked`. Surface to {OWNER}.
- A needed tool is `UNAVAILABLE` → **stop**. Apply fallback from `OPS-TOOL-REGISTRY.md`. Note quality degradation in LONGRUNNER §Blockers (best path vs fallback).

Read `OPS-TOOL-REGISTRY.md` only when: a tool status changes, a new tool needs to be added, or a fallback is needed.

**Minimum Model Quality:** GPT-5 class minimum or equivalent. Below this threshold instruction-following degrades and orchestration controls cannot maintain correctness. Never use GPT-4o or below for cron sessions.
