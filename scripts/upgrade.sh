#!/usr/bin/env bash
set -euo pipefail

# NightClaw — Upgrade from a new release zip
# Usage: bash scripts/upgrade.sh <path-to-zip>
# Example: bash scripts/upgrade.sh ~/.openclaw/nightclaw-v0.1.1-release.zip
# Run from workspace root.
#
# This script:
#   1. Extracts the new zip to a temp directory
#   2. Reads your current owner/path config from installed files
#   3. Copies updated files over the live workspace
#   4. Substitutes {OWNER} and {WORKSPACE_ROOT} in any new file that needs it
#   5. Re-signs any protected files that changed
#   6. Runs validate.sh to confirm integrity

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()  { echo -e "${CYAN}[STEP]${NC} $1"; }

ZIP="${1:-}"
WS="$(pwd)"

# --- Usage check ---
if [[ -z "$ZIP" ]]; then
    echo "Usage: bash scripts/upgrade.sh <path-to-zip>"
    echo "Example: bash scripts/upgrade.sh ~/.openclaw/nightclaw-v0.1.1-release.zip"
    exit 0
fi

[[ -f "$ZIP" ]] || error "Zip not found: $ZIP"
[[ -f "scripts/validate.sh" ]] || error "Run from workspace root (scripts/validate.sh not found)"
[[ -f "audit/INTEGRITY-MANIFEST.md" ]] || error "Integrity manifest not found — is this a NightClaw workspace?"

echo ""
echo "NightClaw Upgrade"
echo "================="
echo "Zip:       $ZIP"
echo "Workspace: $WS"
echo ""

# --- Detect current config from installed files ---
step "Detecting current installation config..."

# Read OWNER from installed USER.md (- **Name:** field) or manifest verified_by column
OWNER=$(grep -h '\*\*Name:\*\*' USER.md 2>/dev/null | head -1 | sed 's/.*Name:\*\* *//' | tr -d ' ' || true)
if [[ -z "$OWNER" || "$OWNER" == '{OWNER}' ]]; then
    # Fallback: read from INTEGRITY-MANIFEST.md verified_by column
    OWNER=$(awk -F'|' 'NR>3 && /signed/{print $4}' audit/INTEGRITY-MANIFEST.md 2>/dev/null | head -1 | sed 's/-signed.*//' | tr -d ' ' || true)
fi
if [[ -z "$OWNER" ]]; then
    read -rp "Could not detect owner from installed files. Enter your handle: " OWNER
fi

WORKSPACE_ROOT="$WS"
INSTALL_DATE=$(date +%Y-%m-%d)
PLATFORM=$(grep -h 'Platform\|platform' USER.md SOUL.md 2>/dev/null | grep -v '^#\|<!--' | head -1 | sed 's/.*: //' | tr -d ' ' || echo "Linux")
[[ -z "$PLATFORM" ]] && PLATFORM="Linux"

info "Owner:     $OWNER"
info "Workspace: $WORKSPACE_ROOT"
echo ""
read -rp "Proceed with upgrade? (y/N): " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# --- Extract zip ---
step "Extracting $ZIP..."
EXTRACT="/tmp/nightclaw-upgrade-$$"
rm -rf "$EXTRACT"
unzip -q "$ZIP" -d "$EXTRACT"

# Find the release directory inside the zip
# Find the release directory — locate scripts/install.sh then go up two levels
INSTALL_SH=$(find "$EXTRACT" -maxdepth 3 -type f -name "install.sh" | head -1)
[[ -n "$INSTALL_SH" ]] || error "Could not find install.sh inside zip"
SCRIPTS_DIR=$(dirname "$INSTALL_SH")
RELEASE_DIR=$(dirname "$SCRIPTS_DIR")
[[ -d "$RELEASE_DIR" ]] || error "Could not find release directory inside zip"
info "Release dir: $RELEASE_DIR"

# --- Determine which files to upgrade ---
# Category A: safe to overwrite directly (docs, non-protected orchestration files, scripts)
CATEGORY_A=(
    "README.md"
    "DEPLOY.md"
    "INSTALL.md"
    "UPGRADING.md"
    "CHANGELOG.md"
    "CONTRIBUTING.md"
    "SECURITY.md"
    "CODE_OF_CONDUCT.md"
    "TROUBLESHOOTING.md"
    "scripts/install.sh"
    "scripts/validate.sh"
    "scripts/verify-integrity.sh"
    "scripts/resign.sh"
    "scripts/upgrade.sh"
    "scripts/smoke-test.sh"
    "scripts/new-project.sh"
    "scripts/check-lock.py"
    "orchestration-os/START-HERE.md"
    "orchestration-os/ORCHESTRATOR.md"
    "orchestration-os/OPS-CRON-SETUP.md"
    "orchestration-os/OPS-PASS-LOG-FORMAT.md"
    "orchestration-os/LONGRUNNER-TEMPLATE.md"
    "orchestration-os/PROJECT-SCHEMA-TEMPLATE.md"
    "orchestration-os/TOOL-STATUS.md"
    "WORKING.md"
    "PROJECTS/example-research/LONGRUNNER.md"
    "PROJECTS/MANAGER-REVIEW-REGISTRY.md"
)

# Category MERGE: agent-extended files — do NOT overwrite automatically.
# These files accumulate knowledge written by the agent at runtime.
# Overwriting them on upgrade silently destroys operational memory.
# Action required: manually diff and merge each file after upgrade.
CATEGORY_MERGE=(
    "orchestration-os/OPS-FAILURE-MODES.md"
    "orchestration-os/OPS-KNOWLEDGE-EXECUTION.md"
    "orchestration-os/OPS-TOOL-REGISTRY.md"
    "orchestration-os/OPS-QUALITY-STANDARD.md"
    "orchestration-os/OPS-IDLE-CYCLE.md"
    "AGENTS-LESSONS.md"
)

# Category B: protected files — copy, substitute, re-sign
CATEGORY_B=(
    "orchestration-os/CRON-WORKER-PROMPT.md"
    "orchestration-os/CRON-MANAGER-PROMPT.md"
    "orchestration-os/REGISTRY.md"
    "orchestration-os/OPS-PREAPPROVAL.md"
    "orchestration-os/OPS-AUTONOMOUS-SAFETY.md"
    "orchestration-os/CRON-HARDLINES.md"
)

# Category C: identity files — NEVER overwrite automatically
# SOUL.md, USER.md, IDENTITY.md, MEMORY.md, AGENTS-CORE.md, AGENTS.md, HEARTBEAT.md, TOOLS.md, LOCK.md

# --- Category MERGE advisory (never auto-copy) ---
echo ""
warn "Category MERGE files (agent-extended — manual merge required):"
warn "These files accumulate agent knowledge at runtime. Overwriting destroys it."
for f in "${CATEGORY_MERGE[@]}"; do
    if [[ -f "$RELEASE_DIR/$f" ]]; then
        echo "  → diff \"$f\" \"$RELEASE_DIR/$f\" | less"
    fi
done
warn "NOTIFICATIONS.md is live state (pending alerts) — never overwrite on upgrade."
warn "Review it manually if the format changed between versions."
echo ""

# --- Copy Category A files ---
echo ""
step "Copying Category A files (safe overwrites)..."
A_UPDATED=0
for f in "${CATEGORY_A[@]}"; do
    if [[ -f "$RELEASE_DIR/$f" ]]; then
        mkdir -p "$(dirname "$f")"
        cp "$RELEASE_DIR/$f" "$f"
        # Substitute placeholders — skip scripts/ (validate.sh patterns must not be substituted)
        if [[ "$f" != scripts/* ]]; then
            sed -i \
                -e "s|{OWNER}|$OWNER|g" \
                -e "s|{WORKSPACE_ROOT}|$WORKSPACE_ROOT|g" \
                -e "s|{OPENCLAW_CRON_DIR}|$HOME/.openclaw/cron|g" \
                -e "s|{OPENCLAW_LOGS_DIR}|$HOME/.openclaw/logs|g" \
                -e "s|{INSTALL_DATE}|$INSTALL_DATE|g" \
                -e "s|{PLATFORM}|$PLATFORM|g" \
                "$f" 2>/dev/null || true
        fi
        chmod +x "$f" 2>/dev/null || true
        A_UPDATED=$((A_UPDATED + 1))
    fi
done
info "$A_UPDATED Category A files updated"

# --- Copy and re-sign Category B files ---
echo ""
step "Copying and re-signing Category B (protected) files..."
B_UPDATED=0
B_RESIGN_NEEDED=()
for f in "${CATEGORY_B[@]}"; do
    if [[ -f "$RELEASE_DIR/$f" ]]; then
        mkdir -p "$(dirname "$f")"
        cp "$RELEASE_DIR/$f" "$f"
        # Substitute all placeholders
        sed -i \
            -e "s|{OWNER}|$OWNER|g" \
            -e "s|{WORKSPACE_ROOT}|$WORKSPACE_ROOT|g" \
            -e "s|{OPENCLAW_CRON_DIR}|$HOME/.openclaw/cron|g" \
            -e "s|{OPENCLAW_LOGS_DIR}|$HOME/.openclaw/logs|g" \
            -e "s|{INSTALL_DATE}|$INSTALL_DATE|g" \
            -e "s|{PLATFORM}|$PLATFORM|g" \
            "$f" 2>/dev/null || true
        B_RESIGN_NEEDED+=("$f")
        B_UPDATED=$((B_UPDATED + 1))
    fi
done

# Re-sign all updated protected files
for f in "${B_RESIGN_NEEDED[@]}"; do
    if bash scripts/resign.sh "$f" 2>/dev/null; then
        info "Re-signed: $f"
    else
        warn "Re-sign failed for $f — check manually"
    fi
done
info "$B_UPDATED Category B files updated and re-signed"

# --- Category C notice ---
echo ""
step "Category C (identity files) — skipped, never auto-overwritten"
warn "SOUL.md, USER.md, AGENTS-CORE.md and other identity files are yours — check UPGRADING.md"
warn "for any manual changes needed in this release."

# --- Cleanup ---
rm -rf "$EXTRACT"

# --- Validate ---
echo ""
step "Running validation..."
bash scripts/validate.sh

echo ""
info "Upgrade complete."
