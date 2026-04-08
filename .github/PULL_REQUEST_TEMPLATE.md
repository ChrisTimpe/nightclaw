## Summary

<!-- What does this PR change and why? -->

## Checklist

- [ ] `bash scripts/validate.sh` passes (96 passed, 0 failed, 2 warnings)
- [ ] `bash scripts/verify-integrity.sh` passes (11/11) — **Note:** the integrity manifest governs per-deployment workspaces, not the repository itself. If you changed a protected file, update the manifest hash in `audit/INTEGRITY-MANIFEST.md` so the shipped template reflects the new file. Users re-sign their own manifest after pulling changes (see `UPGRADING.md`).
- [ ] No new `{PLACEHOLDER}` tokens introduced that are not handled by `scripts/install.sh`
- [ ] If adding a new file: added to `EXPECTED_FILES` in `scripts/validate.sh` and relevant R4 edges in `orchestration-os/REGISTRY.md`
- [ ] If modifying a protected file: hash updated in `audit/INTEGRITY-MANIFEST.md` AND `UPGRADING.md §Protected File Changes` reviewed to confirm the change is documented there
- [ ] CHANGELOG.md updated if this is a user-facing change

## Type of change

- [ ] Bug fix
- [ ] New failure mode (from real deployment — most valued contribution)
- [ ] New field map or skill layer example
- [ ] Documentation improvement
- [ ] Other:
