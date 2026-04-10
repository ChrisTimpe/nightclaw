# Contributing to NightClaw

Thank you for your interest in contributing. NightClaw is an open-source orchestration framework for OpenClaw, and contributions that improve the framework for all users are welcome.

## How to Contribute

### Reporting Issues

- Open a GitHub issue describing the problem
- Include which file(s) are affected and what behavior you expected vs. what happened
- If proposing a change to an orchestration protocol, explain the failure mode or gap it addresses

### Suggesting Improvements

- Open an issue first — describe the improvement and why it matters
- Reference specific files and sections
- If the change affects a protected file (listed in `audit/INTEGRITY-MANIFEST.md`), note that explicitly

### Submitting Changes

1. Fork the repository
2. Create a branch from `main` (`git checkout -b your-branch-name`)
3. Make your changes
4. Ensure all placeholder patterns (`{OWNER}`, `{WORKSPACE_ROOT}`, etc.) are preserved — do not substitute them with real values
5. Run `bash scripts/validate.sh` to verify internal consistency
6. If you add a new file, add it to the appropriate section in `README.md` and `orchestration-os/REGISTRY.md`
7. If you modify a protected file:
   - Update the hash in `audit/INTEGRITY-MANIFEST.md` in your PR so the shipped template is current
   - Document the change in `UPGRADING.md §Protected File Changes` so users know to re-sign after pulling
   - The integrity manifest has two roles: (1) a template that ships with the repo (maintained here), and (2) a per-deployment signed record in each user’s live workspace. Contributors maintain the template. Users re-sign their own deployments after upgrading. These are separate operations — do not conflate them.
8. Submit a pull request with a clear description of what changed and why

## What We're Looking For

### High-value contributions

- New failure modes discovered during use (add to `orchestration-os/OPS-FAILURE-MODES.md`)
- Field maps for additional systems (add to `orchestration-os/OPS-KNOWLEDGE-EXECUTION.md`)
- Improvements to the behavioral discipline contract or blocker decision tree based on edge cases encountered during use
- Bug fixes in cron protocols or orchestration logic
- Documentation clarity improvements

### Out of scope

- Changes that introduce personal, employer-specific, or proprietary context
- Features that require a specific LLM provider (the framework is model-agnostic)
- Runtime code or daemons — governance executes through the agent's reasoning, not through a separate process. The system has no runtime layer to add to.
- Changes to the core safety model (Hard Lines, append-only audit, integrity verification) without thorough justification

## Guidelines

- **Preserve the architecture.** NightClaw is a hybrid system: deterministic scripts that enforce hard bounds (integrity verification, structural validation, dependency pre-computation) and natural-language protocols the LLM reads and executes within those bounds. Both layers are load-bearing. Contributions should extend the protocols — new failure modes, schema additions to `REGISTRY.md`, field map extensions, protocol improvements — or improve the enforcement scripts. Do not add a separate execution layer; that would change the architecture.
- **No credentials or real data.** Never include API keys, tokens, tenant names, real company names, or personal information in any contribution.
- **Preserve placeholders.** All installer-substitutable values use `{PLACEHOLDER}` syntax. New placeholders should follow this convention and be documented in `INSTALL.md`.
- **Respect the append-only principle.** Files marked append-only in `orchestration-os/REGISTRY.md` (audit logs, session registry, change log) should never have entries edited or deleted in examples or templates.
- **Test in a real workspace.** If your change modifies a cron protocol, orchestration logic, or safety behavior, test it in an actual OpenClaw deployment before submitting.

## Code of Conduct

See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) for the full Contributor Covenant. Be respectful, constructive, and specific. A one-line fix to a failure mode entry is worth more than a thousand-line refactor that changes nothing behavioral.

## License

By contributing, you agree that your contributions will be licensed under the MIT License that covers this project.
