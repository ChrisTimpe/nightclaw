# INTEGRITY-MANIFEST.md
<!-- Session state verification — SHA-256 drift detection for core framework files. -->
<!-- Purpose: detect accidental drift between sessions. Not a tamper-prevention mechanism. -->
<!-- For tamper-proof integrity, use signed git commits. -->
<!-- Reader: worker T0 (verify), manager T1 (verify + timestamp). -->
<!-- Writer: {OWNER} (hash values), manager (last_verified timestamps only). -->
<!-- APPEND-ONLY for timestamp updates. Hash values: {OWNER} only. -->

---

## Protected Files

| File | SHA256 | Last verified | Verified by |
|------|--------|---------------|-------------|
| `SOUL.md` | ac29dda914b17ede94a5efacea4c0ff5369d5179697265937cc96267a289d5e4 | 2026-04-24 | computer-signed-2026.4.22 |
| `USER.md` | 75268773fdb4a367d656b5f4b7c5438b102fb6d154ca1836a7ae5a3059d576bc | 2026-04-22 | computer-signed-2026.4.22 |
| `IDENTITY.md` | d73a06e70bea594354f66818587c7c689210505e7de7bb40be7d8ee4258ba2c1 | 2026-04-22 | computer-signed-2026.4.22 |
| `MEMORY.md` | 810d1d0023410d4780d10ad842b34a5631858d3009ff327120e312c795da0d22 | 2026-04-22 | computer-signed-2026.4.22 |
| `AGENTS-CORE.md` | 192a6ccf36821dd960e4cde32543776eb42c4bf8ab427568500fad679fc18ff8 | 2026-04-22 | computer-signed-2026.4.22 |
| `orchestration-os/CRON-WORKER-PROMPT.md` | bfdabd8cd5420158defd73cf40f83947e99f5c8c0f54fcad4a9432aa787ec903 | 2026-04-24 | computer-signed-2026.4.22a |
| `orchestration-os/CRON-MANAGER-PROMPT.md` | 30af8bc29f429eead50143791b80321dbcbf0c05acc1c962ff87f414e35904bc | 2026-04-23 | computer-signed-2026.4.22a |
| `orchestration-os/OPS-PREAPPROVAL.md` | 6a0e63eeb47cec63f163af99c85a82e680ca9a527a8f06f063de4f397486dda6 | 2026-04-24 | computer-signed-2026.4.22 |
| `orchestration-os/OPS-AUTONOMOUS-SAFETY.md` | 237b804500413a496101dde2ffd44a621cb143ed6e8eb0c679fcc655980beb94 | 2026-04-24 | computer-signed-2026.4.22 |
| `orchestration-os/CRON-HARDLINES.md` | 188227216f29778faaa698fc070631924f791bfb84ad9d2af16e73d7f0d3b1f2 | 2026-04-24 | computer-signed-2026.4.22 |
| `orchestration-os/REGISTRY.md` | da45eeac8e55cdc47af89dad25bb68d13c17af829d4a79d5b1c8b7c3f9e074e5 | 2026-04-25 | computer-signed-2026.4.22 |

---

## First-Sign Instructions (run once after install)

<!-- Human operation: run from workspace root in your terminal. -->
<!-- Uses sha256sum (standard shell tool) for interactive use. -->
<!-- The install script (scripts/install.sh) runs this step automatically -->
<!-- and updates this file; manual execution is only needed if the script -->
<!-- fails or if you are doing a manual install. -->

In your workspace root, run:

```bash
for f in SOUL.md USER.md IDENTITY.md MEMORY.md AGENTS-CORE.md \
  orchestration-os/CRON-WORKER-PROMPT.md \
  orchestration-os/CRON-MANAGER-PROMPT.md \
  orchestration-os/OPS-PREAPPROVAL.md \
  orchestration-os/OPS-AUTONOMOUS-SAFETY.md \
  orchestration-os/CRON-HARDLINES.md \
  orchestration-os/REGISTRY.md; do
  echo "$(sha256sum "$f" | cut -d' ' -f1)  $f"
done
```

Paste each hash into the SHA256 column above. Set Last verified to today's date. Set Verified by to `{OWNER}-signed-[version]` (e.g. `yourname-signed-2026.4.16`).

**Only {OWNER} updates hash values in this file. Never delegate to the agent.**

---

## Worker T0 Protocol

<!-- Agent operation: runs inside a cron session via tool call. -->
<!-- Uses Python (not sha256sum) because the agent resolves {WORKSPACE_ROOT} at runtime -->
<!-- as a fully-qualified path. sha256sum is equivalent but less portable across agent -->
<!-- execution environments where shell PATH may differ. Both methods produce identical hashes. -->

For each file in the table above, substitute its exact relative path for FILENAME:
  `python3 -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('{WORKSPACE_ROOT}/FILENAME').expanduser().read_bytes()).hexdigest())"`

Each output MUST be exactly 64 hex characters. Empty or error = FAIL (treat as hash mismatch).

PASS (all valid + match): continue to step 1 (lock acquisition).
FAIL (any mismatch or invalid output): STOP IMMEDIATELY. No lock, no writes, no T9. {OWNER} investigates.

---

## Manager T1 Protocol

Same hash computation as worker T0.
PASS: update Last verified + Verified by to today's date + nightclaw-manager. BUNDLE:manifest_verify.
FAIL: STOP IMMEDIATELY. No lock, no writes, no T9. {OWNER} investigates.

---

## Re-sign After Any Edit to a Protected File

<!-- Human operation: run from your terminal (same sha256sum tool as First-Sign). -->
<!-- Do not delegate this step to the agent — hash values in this file are {OWNER}-only. -->

Run this in your terminal after editing any file in the table:
  `cd {WORKSPACE_ROOT} && sha256sum [edited-file] | cut -d' ' -f1`

Replace the hash value in this file. Do not update via agent — {OWNER} only.
