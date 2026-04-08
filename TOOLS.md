# TOOLS.md — Environment Notes
<!-- Auto-injected every session. Keep lean — tool policy detail lives in orchestration-os/CRON-WORKER-PROMPT.md -->

## Tool Priority (quick reference)

| Goal | Use | Never use |
|------|-----|-----------|
| Read file | `ReadFile` | `cat`, `head`, `tail` |
| Edit file | `Edit` (diff only) | `sed`, `awk` |
| Create file | `Write` | `echo >`, heredoc |
| Find files | `Glob` | `find`, `ls` |
| Search content | `Grep` | shell `grep`, `rg` |
| Shell/system ops | `Bash` — last resort | — |
| Broad exploration | Explore sub-agent | Inline bash thrash |

**Git safety:** Never commit, push, or run destructive git commands without {OWNER} explicitly asking.
**Parallel tool calls:** When multiple independent tools are needed, call them in parallel in a single response.

---

## This Environment

- **Platform:** {PLATFORM}
- **Workspace:** {WORKSPACE_ROOT}
- **Scratchpad:** Use `workspace/tmp/` for temp files — not `/tmp`, not project root
- **Model:** _(set by {OWNER} in openclaw.json)_
- **DuckDuckGo:** Hard limit ~10–15 searches/session — spend intentionally

For full tool constraints, fallbacks, and approval requirements:
→ `orchestration-os/OPS-TOOL-REGISTRY.md`
→ `orchestration-os/TOOL-STATUS.md` (fast pre-flight, ~200 tokens)

---

## Add Environment Specifics Here
```
SSH:
  (add host details here)

TTS / Voice:
  (add if configured)

API keys / services:
  (reference env var names only — never paste values here)
```
