# OPS-TOOL-REGISTRY.md
<!-- Registry for tool constraints discovered during operation. -->
<!-- Written by: worker T7a when a new tool constraint is discovered. -->
<!-- Distinct from TOOL-STATUS.md: TOOL-STATUS = current availability. OPS-TOOL-REGISTRY = historical constraint knowledge. -->

## Registry

<!-- Entries below marked [seed] were discovered during initial framework development and apply broadly. -->
<!-- Your agent will append new entries here via T7a as it discovers constraints in your environment. -->

| Date | Tool | Constraint | Evidence | Session |
|------|------|-----------|----------|---------|
| 2026-04-03 | /usr/local/bin/python3 | Path does not exist on Ubuntu/WSL2; use `python3` or `/usr/bin/python3` | exec exit 127 during proof-execution pass | worker [seed] |
| 2026-04-03 | openclaw exec | Allowlist miss on cron channel for Python scripts; use interactive session for exec approval | exec denied: allowlist miss during proof-execution | worker [seed] |
