"""nightclaw_engine.commands.integrity — SHA-256 manifest verifier.

Compares every protected file's SHA-256 against the manifest in
``audit/INTEGRITY-MANIFEST.md``. Exit code non-zero on any mismatch so
cron sessions refuse to continue against a tampered tree.

Body migrated verbatim from ``_legacy.py`` (Pass 6); ``ROOT``
resolves through :mod:`._shared`.
"""
from __future__ import annotations

import hashlib
import sys

from . import _shared


def cmd_integrity_check():
    """Compare SHA256 hashes of all protected files against manifest.
    Output: one line per file: PASS|FAIL|MISSING <filepath> [computed] [expected]
    Final line: RESULT:PASS or RESULT:FAIL count=N
    """
    manifest = _shared.read_file("audit/INTEGRITY-MANIFEST.md")
    if manifest is None:
        print("ERROR: audit/INTEGRITY-MANIFEST.md not found")
        sys.exit(1)

    # Parse manifest: extract filepath → hash pairs
    # Format: | `filepath` | hash | ... OR | `filepath` | `hash` | ...
    # H-SEC-01: a row whose hash cell is non-hex (e.g. the
    # ``_(blank — re-sign on install)_`` placeholder present in the
    # published release) is silently skipped during hash comparison.
    # That silent skip means a tampered protected file would still produce
    # RESULT:PASS. We cannot change the stdout contract (Lock 1), so we
    # emit an out-of-band WARN:UNSIGNED:<filepath> line on stderr for every
    # such row. Operators and CI both see it; existing cron-prompt parsers
    # consume only stdout and stay unaffected.
    manifest_hashes = {}
    unsigned_rows = []
    for line in manifest.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 2:
            continue
        fpath = cells[0].strip("`").strip()
        h = cells[1].strip("`").strip()
        # Skip the header row (``File | SHA256 | ...``) and the separator
        # (``------``). The header has ``file`` in the filepath cell; the
        # separator has only dashes.
        if not fpath or fpath.lower() == "file" or set(fpath) <= set("- "):
            continue
        if len(h) == 64 and all(c in "0123456789abcdef" for c in h):
            manifest_hashes[fpath] = h
        else:
            # A manifest row with a filepath but no verifiable hash. Record
            # it for an out-of-band warning so unsigned protected files are
            # visible even though they cannot be hash-compared.
            unsigned_rows.append(fpath)

    # Emit unsigned warnings on stderr before any stdout output so the
    # two streams interleave cleanly for operators watching both.
    for fpath in unsigned_rows:
        print(f"WARN:UNSIGNED:{fpath}", file=sys.stderr)

    if not manifest_hashes:
        print("ERROR: No hash entries found in manifest")
        sys.exit(1)

    fail_count = 0
    pass_count = 0
    for fpath, expected_hash in sorted(manifest_hashes.items()):
        full = _shared.ROOT / fpath
        if not full.exists():
            print(f"MISSING {fpath}")
            fail_count += 1
            continue
        computed = hashlib.sha256(full.read_bytes()).hexdigest()
        if computed == expected_hash:
            print(f"PASS {fpath}")
            pass_count += 1
        else:
            print(f"FAIL {fpath} computed={computed} expected={expected_hash}")
            fail_count += 1

    if fail_count > 0:
        print(f"RESULT:FAIL pass={pass_count} fail={fail_count}")
        sys.exit(1)
    else:
        print(f"RESULT:PASS files={pass_count}")
        sys.exit(0)


__all__ = ["cmd_integrity_check"]
