# memory/

Daily append-only session logs live here.

This directory can be empty in a fresh template. The first worker, manager, or
session-close write creates a dated log such as `memory/YYYY-MM-DD.md` through
the `append` command or the `session_close` bundle.

Do not confuse this directory with root `MEMORY.md`:

| Surface | Purpose | Write policy |
|---|---|---|
| `MEMORY.md` | Protected, compact long-term memory auto-injected into main sessions. | Owner/dream-consolidation only; never worker-written. |
| `memory/YYYY-MM-DD.md` | Append-only daily runtime/session log. | Written through `nightclaw-ops.py append` or approved bundles. |

The empty directory is retained with `.gitkeep` so install and smoke-test flows
start with the expected runtime log location.
