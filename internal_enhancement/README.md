# internal_enhancement/

Maintainer-only enhancement and validation surfaces for NightClaw itself.

This directory is not public product documentation and is not cron runtime
state. It contains the internal architecture map, LLM-maintainer bootstrap
tracks, and current-pass handoff notes used when improving or validating the
NightClaw suite.

| File | Role |
|---|---|
| `ARCHITECTURE.md` | Internal runtime, telemetry, package-boundary, and file-category map. |
| `LLM-BOOTSTRAP.yaml` | Declarative tracks for `nightclaw-ops.py bootstrap`. |
| `CURRENT-PASS.md` | Live maintainer handoff surface: known issues and current-pass pointers. |

Public usage and install guidance belongs in the root `README.md`, `INSTALL.md`,
and `DEPLOY.md`. Protocol authority belongs in `orchestration-os/schema/*.yaml`
and the rendered registry.
