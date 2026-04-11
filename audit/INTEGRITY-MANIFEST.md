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
| `SOUL.md` | ac29dda914b17ede94a5efacea4c0ff5369d5179697265937cc96267a289d5e4 | 2026-04-07 | nightclaw-sign-v0.1.0 |
| `USER.md` | 75268773fdb4a367d656b5f4b7c5438b102fb6d154ca1836a7ae5a3059d576bc | 2026-04-07 | nightclaw-sign-v0.1.0 |
| `IDENTITY.md` | d73a06e70bea594354f66818587c7c689210505e7de7bb40be7d8ee4258ba2c1 | 2026-04-07 | nightclaw-sign-v0.1.0 |
| `MEMORY.md` | 810d1d0023410d4780d10ad842b34a5631858d3009ff327120e312c795da0d22 | 2026-04-07 | nightclaw-sign-v0.1.0 |
| `AGENTS-CORE.md` | 4f71016be01a97c9b4482c8d9791e75956c94d9405cf0a6654d70f9606573876 | 2026-04-07 | nightclaw-sign-v0.1.0 |
| `orchestration-os/CRON-WORKER-PROMPT.md` | cc405b9e50e08d5af17a7c6bf134c3178d78df9a08190298cccde780b039f91f | 2026-04-10 | nightclaw-sign-v0.2.0 |
| `orchestration-os/CRON-MANAGER-PROMPT.md` | 20ace9dbf3d4dee616d341e7c5b0401ba5e1c81f231a32f949035364b29f412b | 2026-04-10 | nightclaw-sign-v0.2.0 |
| `orchestration-os/OPS-PREAPPROVAL.md` | 2ff3bcf8712e617e8c661e9f6cd41f607d9c35dc746208bc7ce73560ead49ff9 | 2026-04-07 | nightclaw-sign-v0.1.0 |
| `orchestration-os/OPS-AUTONOMOUS-SAFETY.md` | 768cb8645d9ba567baac6cea2db059b7fe95692d70ab82733af63192ac240e6c | 2026-04-08 | nightclaw-sign-v0.1.0 |
| `orchestration-os/CRON-HARDLINES.md` | 8226d01c069066d1411ffec66ec6252f443eb69b7d95d71351378b95549f8af8 | 2026-04-10 | nightclaw-sign-v0.2.0 |
| `orchestration-os/REGISTRY.md` | e6c2ead835a56da11aaceff070f7069af5d931418cdbdc1ace4f0ee66d0fba92 | 2026-04-10 | nightclaw-sign-v0.2.0 |

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

Paste each hash into the SHA256 column above. Set Last verified to today's date. Set Verified by to `{OWNER}-signed-v[version]` (e.g. `yourname-signed-v0.001.1`).

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

PASS (all valid + match): continue to T1.
FAIL (any mismatch or invalid output): BUNDLE:integrity_fail → HALT.

---

## Manager T1 Protocol

Same hash computation as worker T0.
PASS: update Last verified + Verified by to today's date + nightclaw-manager. BUNDLE:manifest_verify.
FAIL: BUNDLE:integrity_fail. Surface. Continue manager pass (do not halt).

---

## Re-sign After Any Edit to a Protected File

<!-- Human operation: run from your terminal (same sha256sum tool as First-Sign). -->
<!-- Do not delegate this step to the agent — hash values in this file are {OWNER}-only. -->

Run this in your terminal after editing any file in the table:
  `cd {WORKSPACE_ROOT} && sha256sum [edited-file] | cut -d' ' -f1`

Replace the hash value in this file. Do not update via agent — {OWNER} only.
