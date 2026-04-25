# MODEL-TIERS.md — NightClaw Model Tier Configuration

<!-- Edited by {OWNER} once at install. Never written by the agent. -->
<!-- The worker reads this at T9 to set the platform default model   -->
<!-- for the next session via: python3 scripts/nightclaw-ops.py set-model-tier <tier> -->

## What This File Does

NightClaw routes each project pass through one of three model tiers declared in the
project's LONGRUNNER.md (`next_pass.model_tier`). At the end of every worker session
(T9), after the session-close bundle fires, the engine reads the dispatched project's
`next_pass.model_tier` and calls `openclaw models set` to configure the platform
default model for the next session.

The worker cron is set up **without** a `--model` flag so it inherits the platform
default. The manager cron keeps its `--model` flag hardcoded — it is never affected
by this file.

## Tier Assignments

Set each value to the exact model ID your OpenClaw install accepts.
Run `openclaw models status` to see available model IDs.

```yaml
lightweight: {MODEL_LIGHTWEIGHT}
standard:    {MODEL_STANDARD}
heavy:       {MODEL_HEAVY}
```

## Tier Guidance

| Tier        | Use for                                              | Cost profile  |
|-------------|------------------------------------------------------|---------------|
| lightweight | Structured execution, file writes, data transforms   | Lowest        |
| standard    | Research, synthesis, multi-step reasoning            | Mid           |
| heavy       | Complex judgment, architecture decisions, long docs  | Highest       |

Default for new projects: `standard`. Set in LONGRUNNER-TEMPLATE.md.

## Changing Tiers

To change which model maps to a tier: edit this file and save. The engine picks
up the change on the next T9 call — no restart, no cron changes required.

To change which tier a project uses for its next pass: edit `next_pass.model_tier`
in the project's LONGRUNNER.md (or let the worker set it via `longrunner_update`).
