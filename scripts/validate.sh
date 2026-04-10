#!/usr/bin/env bash
set -euo pipefail

# NightClaw v0.1.0 — Internal Consistency Validation
# Checks that all file references, bundle references, and structural assumptions hold.
# Run from the workspace root.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check_pass()  { echo -e "${GREEN}[PASS]${NC} $1"; ((++PASS)); }
check_fail()  { echo -e "${RED}[FAIL]${NC} $1"; ((++FAIL)); }
check_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; ((++WARN)); }

echo ""
echo "NightClaw Internal Consistency Validation"
echo "==========================================="
echo ""

# --- Check 1: All files referenced in README exist ---
echo "--- File existence checks ---"
EXPECTED_FILES=(
    "SOUL.md" "AGENTS.md" "AGENTS-CORE.md" "AGENTS-LESSONS.md" "IDENTITY.md" "USER.md" "MEMORY.md"
    "HEARTBEAT.md" "WORKING.md" "ACTIVE-PROJECTS.md" "NOTIFICATIONS.md" "LOCK.md"
    "TOOLS.md" "VERSION" "INSTALL.md" "DEPLOY.md" "LICENSE"
    "README.md" "CONTRIBUTING.md" "UPGRADING.md" "CHANGELOG.md" "CODE_OF_CONDUCT.md" "SECURITY.md" "TROUBLESHOOTING.md"
    "audit/AUDIT-LOG.md" "audit/INTEGRITY-MANIFEST.md" "audit/APPROVAL-CHAIN.md"
    "audit/SESSION-REGISTRY.md" "audit/CHANGE-LOG.md"
    "orchestration-os/START-HERE.md" "orchestration-os/ORCHESTRATOR.md"
    "orchestration-os/CRON-WORKER-PROMPT.md" "orchestration-os/CRON-MANAGER-PROMPT.md"
    "orchestration-os/CRON-HARDLINES.md" "orchestration-os/REGISTRY.md"
    "orchestration-os/OPS-CRON-SETUP.md" "orchestration-os/OPS-AUTONOMOUS-SAFETY.md"
    "orchestration-os/OPS-PREAPPROVAL.md" "orchestration-os/OPS-QUALITY-STANDARD.md"
    "orchestration-os/OPS-FAILURE-MODES.md" "orchestration-os/OPS-KNOWLEDGE-EXECUTION.md"
    "orchestration-os/OPS-TOOL-REGISTRY.md" "orchestration-os/OPS-IDLE-CYCLE.md"
    "orchestration-os/OPS-PASS-LOG-FORMAT.md" "orchestration-os/LONGRUNNER-TEMPLATE.md"
    "orchestration-os/PROJECT-SCHEMA-TEMPLATE.md" "orchestration-os/TOOL-STATUS.md"
    "PROJECTS/MANAGER-REVIEW-REGISTRY.md"
    "PROJECTS/example-research/LONGRUNNER.md"
)

for f in "${EXPECTED_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        check_pass "$f exists"
    else
        check_fail "$f MISSING"
    fi
done

# --- Check 2: Bundle references in REGISTRY.md R3 resolve to R5 ---
echo ""
echo "--- Bundle reference checks ---"
if [[ -f "orchestration-os/REGISTRY.md" ]]; then
    # Extract bundle names from R3 (write routing)
    R3_BUNDLES=$(grep -oP 'BUNDLE:\w+' orchestration-os/REGISTRY.md | sort -u)
    for bundle in $R3_BUNDLES; do
        if grep -q "^$bundle$" orchestration-os/REGISTRY.md 2>/dev/null || \
           grep -q "^$bundle\b" orchestration-os/REGISTRY.md 2>/dev/null; then
            check_pass "$bundle defined in REGISTRY.md"
        else
            check_warn "$bundle referenced but definition not confirmed (manual check recommended)"
        fi
    done
else
    check_fail "orchestration-os/REGISTRY.md not found"
fi

# --- Check 3: Protected files in manifest match REGISTRY R3 PROTECTED tier ---
echo ""
echo "--- Protected file consistency ---"
if [[ -f "audit/INTEGRITY-MANIFEST.md" ]]; then
    # Extract all backtick-quoted paths from manifest table rows
    MANIFEST_FILES=$(awk -F'`' '/^\| `/{print $2}' audit/INTEGRITY-MANIFEST.md)
    MANIFEST_COUNT=0
    for f in $MANIFEST_FILES; do
        MANIFEST_COUNT=$((MANIFEST_COUNT + 1))
        if [[ -f "$f" ]]; then
            check_pass "Manifest file $f exists"
        else
            check_fail "Manifest file $f MISSING from disk"
        fi
    done
    # Verify manifest has exactly 11 protected files (10 original + AGENTS-CORE.md)
    if [[ $MANIFEST_COUNT -eq 11 ]]; then
        check_pass "Manifest contains expected 11 protected files"
    else
        check_warn "Manifest contains $MANIFEST_COUNT protected files (expected 11)"
    fi
else
    check_fail "audit/INTEGRITY-MANIFEST.md not found"
fi

# --- Check 4: Required directories exist ---
echo ""
echo "--- Directory checks ---"
for d in audit orchestration-os PROJECTS memory skills scripts; do
    if [[ -d "$d" ]]; then
        check_pass "Directory $d/ exists"
    else
        check_fail "Directory $d/ MISSING"
    fi
done

# --- Check 4b: SCR-08 — LOCK.md structural check ---
echo ""
echo "--- LOCK.md integrity ---"
if [[ -f "LOCK.md" ]]; then
    if grep -q 'status:' LOCK.md; then
        check_pass "LOCK.md has status field"
    else
        check_fail "LOCK.md missing status field"
    fi
    if grep -q 'expires_at:' LOCK.md; then
        check_pass "LOCK.md has expires_at field"
    else
        check_fail "LOCK.md missing expires_at field"
    fi
else
    check_fail "LOCK.md MISSING"
fi

# --- Check 5: No deprecated files ---
echo ""
echo "--- Deprecated file checks ---"
DEPRECATED=("orchestration-os/IMPACT-GRAPH.md" "orchestration-os/OPS-GOVERNANCE.md" 
            "orchestration-os/SCHEMA.md" "orchestration-os/WRITE-GATE.md")
for f in "${DEPRECATED[@]}"; do
    if [[ -f "$f" ]]; then
        check_warn "Deprecated file $f still present"
    else
        check_pass "Deprecated file $f not present"
    fi
done

# --- Check 6: Scripts are executable ---
echo ""
echo "--- Script permission checks ---"
for s in scripts/install.sh scripts/verify-integrity.sh scripts/validate.sh scripts/check-lock.py scripts/nightclaw-ops.py; do
    if [[ -f "$s" ]]; then
        if [[ -x "$s" ]]; then
            check_pass "$s is executable"
        else
            check_warn "$s exists but is not executable (run: chmod +x $s)"
        fi
    else
        check_fail "$s MISSING"
    fi
done

# --- Check 7: Unfilled placeholder detection ---
# Catches failed or skipped installs before the agent runs T0 and fails opaquely.
# {DOMAIN_ANCHOR} is intentionally set manually in SOUL.md — excluded from this check.
echo ""
echo "--- Unfilled placeholder checks ---"
PLACEHOLDER_FILES=$(grep -rl '{OWNER}\|{WORKSPACE_ROOT}\|{OPENCLAW_CRON_DIR}\|{OPENCLAW_LOGS_DIR}\|{PLATFORM}\|{INSTALL_DATE}\|{EXAMPLE_API}' \
    --include="*.md" . 2>/dev/null | grep -v 'INSTALL.md\|README.md\|DEPLOY.md\|CONTRIBUTING.md\|LONGRUNNER-TEMPLATE.md\|PROJECT-SCHEMA-TEMPLATE.md\|OPS-KNOWLEDGE-EXECUTION.md\|OPS-CRON-SETUP.md' || true)
if [[ -n "$PLACEHOLDER_FILES" ]]; then
    while IFS= read -r f; do
        check_fail "Unfilled placeholder found in $f — run scripts/install.sh to substitute"
    done <<< "$PLACEHOLDER_FILES"
else
    check_pass "No unfilled install placeholders detected in runtime files"
fi

# --- Check 7b: Domain Anchor configuration check ---
# {DOMAIN_ANCHOR} is excluded from Check 7 because it is set manually, not by install.sh.
# If still unfilled, the first autonomous idle cycle (Tier 4) will produce a meaningless
# project proposal from the literal string {DOMAIN_ANCHOR}.
echo ""
echo "--- Domain Anchor check ---"
if [[ -f "SOUL.md" ]]; then
    if grep -q '{DOMAIN_ANCHOR}' SOUL.md 2>/dev/null; then
        check_warn "SOUL.md: Domain Anchor not configured — fill in before first autonomous pass (Tier 4 idle will produce a nonsense project proposal without it)"
    else
        check_pass "SOUL.md: Domain Anchor appears configured"
    fi
fi

# --- Check 8: Bootstrap file size limits ---
# OpenClaw truncates bootstrap files at 20,000 chars (70% head / 20% tail / 10% marker).
# Files approaching this limit risk silent truncation of content at the tail.
# Hard limit: 20,000 chars per file. Warn at 16,000 (80% of limit).
echo ""
echo "--- Bootstrap file size checks ---"
BOOTSTRAP_FILES=("AGENTS.md" "SOUL.md" "TOOLS.md" "IDENTITY.md" "USER.md" "HEARTBEAT.md" "MEMORY.md")
BOOTSTRAP_TOTAL=0
for f in "${BOOTSTRAP_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        chars=$(wc -m < "$f" 2>/dev/null || echo 0)
        BOOTSTRAP_TOTAL=$((BOOTSTRAP_TOTAL + chars))
        if [[ $chars -gt 20000 ]]; then
            check_fail "$f is ${chars} chars — exceeds 20,000 char limit, OpenClaw WILL truncate it"
        elif [[ $chars -gt 16000 ]]; then
            check_warn "$f is ${chars} chars — approaching 20,000 char limit (>80%), review for pruning"
        else
            check_pass "$f size OK (${chars} chars)"
        fi
    fi
done
if [[ $BOOTSTRAP_TOTAL -gt 150000 ]]; then
    check_fail "Total bootstrap size ${BOOTSTRAP_TOTAL} chars exceeds 150,000 char aggregate cap"
else
    check_pass "Total bootstrap size OK (${BOOTSTRAP_TOTAL} chars of 150,000 cap)"
fi

# --- Check 9: OpenClaw version (warn-only — does not fail in CI) ---
# NightClaw requires OpenClaw 2026.4.5+ for --light-context to work correctly (PR #60776).
# This check warns if openclaw is available but below the required version.
echo ""
echo "--- OpenClaw version check ---"
if command -v openclaw &>/dev/null; then
    OC_VERSION=$(openclaw --version 2>/dev/null | grep -oP '\d{4}\.\d+\.\d+' | head -1)
    if [[ -n "$OC_VERSION" ]]; then
        # Compare as sortable strings (YYYY.M.P format sorts correctly)
        if [[ "$OC_VERSION" < "2026.4.5" ]]; then
            check_warn "OpenClaw $OC_VERSION detected — 2026.4.5+ required for --light-context fix (PR #60776). See FM-030."
        else
            check_pass "OpenClaw $OC_VERSION — meets 2026.4.5+ requirement"
        fi
    else
        check_warn "Could not parse OpenClaw version — verify manually: openclaw --version (need 2026.4.5+)"
    fi
else
    check_warn "openclaw not found in PATH — version check skipped (normal for CI). Verify 2026.4.5+ before deploying crons."
fi

# --- Check 10: ACTIVE-PROJECTS.md LONGRUNNER path validation ---
# Every active/blocked/transition-hold project row must point to a real LONGRUNNER.md.
# Missing LONGRUNNERs cause silent idle cycles — the cron shows 'ok' but does no work.
echo ""
echo "--- ACTIVE-PROJECTS.md LONGRUNNER path checks ---"
if [[ -f "ACTIVE-PROJECTS.md" ]]; then
    # Extract rows that have a status of active, blocked, or transition-hold
    # Table format: | Priority | Slug | LONGRUNNER Path | Phase | Status | ... |
    MISSING_LONGRUNNERS=0
    while IFS='|' read -r _ _ slug longrunner_path _ status _; do
        slug=$(echo "$slug" | tr -d ' ')
        longrunner_path=$(echo "$longrunner_path" | tr -d ' ')
        status=$(echo "$status" | tr -d ' ')
        # Skip header rows, separator rows, and empty slugs
        [[ -z "$slug" || "$slug" == "ProjectSlug" || "$slug" == "---" || "$slug" == *"---"* ]] && continue
        [[ -z "$longrunner_path" || "$longrunner_path" == "LONGRUNNERPath" ]] && continue
        # Only check rows with actionable statuses
        [[ "$status" =~ ^(active|blocked|transition-hold|TRANSITION-HOLD)$ ]] || continue
        if [[ -n "$longrunner_path" && ! -f "$longrunner_path" ]]; then
            check_fail "ACTIVE-PROJECTS: '$slug' ($status) points to missing LONGRUNNER: $longrunner_path"
            MISSING_LONGRUNNERS=$((MISSING_LONGRUNNERS + 1))
        elif [[ -n "$longrunner_path" && -f "$longrunner_path" ]]; then
            check_pass "ACTIVE-PROJECTS: '$slug' LONGRUNNER exists"
        fi
    done < <(grep '|' ACTIVE-PROJECTS.md 2>/dev/null)
    if [[ $MISSING_LONGRUNNERS -eq 0 ]]; then
        if ! grep '^|' ACTIVE-PROJECTS.md 2>/dev/null | grep -qiE '\|\s*(active|blocked|transition-hold)\s*\|'; then
            check_pass "ACTIVE-PROJECTS.md: no active projects (idle mode)"
        fi
    fi
else
    check_fail "ACTIVE-PROJECTS.md not found"
fi

# --- Check 11: scripts/resign.sh exists and is executable ---
echo ""
echo "--- Re-sign script check ---"
if [[ -f "scripts/resign.sh" ]]; then
    if [[ -x "scripts/resign.sh" ]]; then
        check_pass "scripts/resign.sh exists and is executable"
    else
        check_warn "scripts/resign.sh exists but is not executable (run: chmod +x scripts/resign.sh)"
    fi
else
    check_warn "scripts/resign.sh not found — manual hash updates required after protected file edits"
fi

# --- Summary ---
echo ""
echo "==========================================="
echo "Results: $PASS passed, $FAIL failed, $WARN warnings"
echo ""

if [[ $FAIL -gt 0 ]]; then
    echo -e "${RED}Validation FAILED. Fix the issues above before deploying.${NC}"
    exit 1
else
    echo -e "${GREEN}Validation passed.${NC}"
    exit 0
fi
