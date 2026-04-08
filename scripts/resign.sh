#!/usr/bin/env bash
set -euo pipefail

# NightClaw — Re-sign a protected file after editing
# Usage: bash scripts/resign.sh <file-path>
# Example: bash scripts/resign.sh SOUL.md
# Run from workspace root.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

MANIFEST="audit/INTEGRITY-MANIFEST.md"
FILE="${1:-}"

# --- Usage check ---
if [[ -z "$FILE" ]]; then
    echo "Usage: bash scripts/resign.sh <file-path>"
    echo "Example: bash scripts/resign.sh SOUL.md"
    echo "         bash scripts/resign.sh orchestration-os/REGISTRY.md"
    echo ""
    echo "Protected files that can be re-signed:"
    echo "  SOUL.md"
    echo "  USER.md"
    echo "  IDENTITY.md"
    echo "  MEMORY.md"
    echo "  AGENTS-CORE.md"
    echo "  orchestration-os/CRON-WORKER-PROMPT.md"
    echo "  orchestration-os/CRON-MANAGER-PROMPT.md"
    echo "  orchestration-os/OPS-PREAPPROVAL.md"
    echo "  orchestration-os/OPS-AUTONOMOUS-SAFETY.md"
    echo "  orchestration-os/CRON-HARDLINES.md"
    echo "  orchestration-os/REGISTRY.md"
    exit 0
fi

# --- Validate file exists ---
[[ -f "$FILE" ]] || error "File not found: $FILE"

# --- Validate manifest exists ---
[[ -f "$MANIFEST" ]] || error "Manifest not found: $MANIFEST — run from workspace root"

# --- Check file is in manifest ---
if ! grep -q "\`$FILE\`" "$MANIFEST"; then
    error "$FILE is not in the integrity manifest. Only protected files can be re-signed."
fi

# --- Compute new hash ---
NEW_HASH=$(sha256sum "$FILE" | cut -d' ' -f1)
TODAY=$(date +%Y-%m-%d)

info "File:     $FILE"
info "Hash:     $NEW_HASH"
info "Date:     $TODAY"

# --- Check if hash already matches manifest ---
CURRENT_MANIFEST_HASH=$(python3 -c "
import re, pathlib, sys
f, m = sys.argv[1:]
lines = pathlib.Path(m).read_text().splitlines()
for line in lines:
    match = re.match(r'\| \x60' + re.escape(f) + r'\x60 \| ([0-9a-f]{64})', line)
    if match:
        print(match.group(1))
        break
" "$FILE" "$MANIFEST" 2>/dev/null || echo "")

if [[ "$CURRENT_MANIFEST_HASH" == "$NEW_HASH" ]]; then
    info "Hash unchanged — manifest already current."
    exit 0
fi

if [[ -n "$CURRENT_MANIFEST_HASH" ]]; then
    info "Replacing: $CURRENT_MANIFEST_HASH"
fi
info "With:      $NEW_HASH"
echo ""

# --- Update manifest ---
python3 -c "
import sys, re, pathlib
f, new_hash, today, m = sys.argv[1:]
p = pathlib.Path(m)
lines = p.read_text().splitlines(keepends=True)
updated = False
new_lines = []
for line in lines:
    # Match table row for this exact file path
    if re.match(r'\| \x60' + re.escape(f) + r'\x60 \|', line):
        # Replace: | \`file\` | OLD_HASH | OLD_DATE | OLD_SIGNER |
        new_line = re.sub(
            r'(\| \x60' + re.escape(f) + r'\x60 \| )([0-9a-f]+)( \| )([0-9]{4}-[0-9]{2}-[0-9]{2})( \| )([^|\n]+)(\|)',
            lambda m: m.group(1) + new_hash + m.group(3) + today + m.group(5) + m.group(6) + m.group(7),
            line
        )
        if new_line != line:
            updated = True
        new_lines.append(new_line)
    else:
        new_lines.append(line)
if not updated:
    print('WARNING: Manifest row not updated — pattern did not match. Update manually.')
    sys.exit(1)
p.write_text(''.join(new_lines))
print('Manifest updated.')
" "$FILE" "$NEW_HASH" "$TODAY" "$MANIFEST"

echo ""
info "Re-sign complete. Run 'bash scripts/validate.sh' to confirm."
