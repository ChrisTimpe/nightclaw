#!/usr/bin/env bash
set -euo pipefail

# NightClaw — Integrity Verification Script
# Computes SHA-256 hashes for all protected files and compares against the manifest.
# Run from the workspace root.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MANIFEST="audit/INTEGRITY-MANIFEST.md"
PASS=0
FAIL=0
MISSING=0

if [[ ! -f "$MANIFEST" ]]; then
    echo -e "${RED}[ERROR]${NC} $MANIFEST not found. Run from workspace root."
    exit 1
fi

PROTECTED_FILES=(
    "SOUL.md"
    "USER.md"
    "IDENTITY.md"
    "MEMORY.md"
    "AGENTS-CORE.md"
    "orchestration-os/CRON-WORKER-PROMPT.md"
    "orchestration-os/CRON-MANAGER-PROMPT.md"
    "orchestration-os/OPS-PREAPPROVAL.md"
    "orchestration-os/OPS-AUTONOMOUS-SAFETY.md"
    "orchestration-os/CRON-HARDLINES.md"
    "orchestration-os/REGISTRY.md"
)

echo ""
echo "NightClaw Integrity Verification"
echo "================================="
echo ""

for f in "${PROTECTED_FILES[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo -e "${RED}[MISSING]${NC} $f"
        ((MISSING++)) || true
        continue
    fi

    COMPUTED=$(sha256sum "$f" | cut -d' ' -f1)

    # Check if the hash exists in the manifest
    if grep -q "$COMPUTED" "$MANIFEST" 2>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $f"
        ((PASS++)) || true
    else
        echo -e "${RED}[FAIL]${NC} $f"
        echo "         Computed: $COMPUTED"
        ((FAIL++)) || true
    fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed, $MISSING missing"
echo ""

if [[ $FAIL -gt 0 || $MISSING -gt 0 ]]; then
    echo -e "${RED}Integrity check FAILED.${NC}"
    echo "If you intentionally modified a protected file, re-sign the manifest:"
    echo "  sha256sum [edited-file] | cut -d' ' -f1"
    echo "  Then update the hash in $MANIFEST"
    exit 1
else
    echo -e "${GREEN}All protected files verified.${NC}"
    exit 0
fi
