#!/usr/bin/env bash
set -euo pipefail

# NightClaw v0.1.0 — Installation Script
# Automates placeholder substitution and first-sign hash generation.
# Run from the workspace root after copying NightClaw files.

# --- Color output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Input validation ---
validate_input() {
    local name="$1"
    local value="$2"
    # Allow alphanumeric, hyphens, underscores, forward slashes, periods, tildes
    # Spaces are intentionally excluded — they break downstream sed substitutions
    if [[ ! "$value" =~ ^[a-zA-Z0-9_./~-]+$ ]]; then
        error "$name contains invalid characters. Use only: a-z A-Z 0-9 _ - . / ~"
    fi
    if [[ "$value" =~ \.\.  ]]; then
        error "$name contains a path traversal sequence (..) which is not allowed"
    fi
    # Resolve to absolute path and verify it doesn't escape expected boundaries
    local resolved
    resolved=$(realpath -m "$value" 2>/dev/null || echo "$value")
    if [[ "$resolved" != /* ]]; then
        error "$name must resolve to an absolute path"
    fi
}

# --- Collect values ---
echo ""
echo "NightClaw v0.1.0 — Installation"
echo "==============================="
echo ""
echo "This script will substitute placeholders and generate integrity hashes."
echo "Values must contain only alphanumeric characters, hyphens, underscores,"
echo "forward slashes, periods, and tildes."
echo ""

read -rp "Your name or handle (OWNER): " OWNER
validate_input "OWNER" "$OWNER"

read -rp "Workspace root path [~/.openclaw/workspace]: " WORKSPACE_ROOT
WORKSPACE_ROOT="${WORKSPACE_ROOT:-$HOME/.openclaw/workspace}"
validate_input "WORKSPACE_ROOT" "$WORKSPACE_ROOT"

read -rp "Cron directory [~/.openclaw/cron]: " CRON_DIR
CRON_DIR="${CRON_DIR:-$HOME/.openclaw/cron}"
validate_input "CRON_DIR" "$CRON_DIR"

read -rp "Logs directory [~/.openclaw/logs]: " LOGS_DIR
LOGS_DIR="${LOGS_DIR:-$HOME/.openclaw/logs}"
validate_input "LOGS_DIR" "$LOGS_DIR"

read -rp "Platform (e.g., Ubuntu/WSL2, macOS, Linux): " PLATFORM
PLATFORM="${PLATFORM:-Linux}"
validate_input "PLATFORM" "$PLATFORM"

INSTALL_DATE=$(date +%Y-%m-%d)

echo ""
info "Configuration:"
echo "  OWNER:          $OWNER"
echo "  WORKSPACE_ROOT: $WORKSPACE_ROOT"
echo "  CRON_DIR:       $CRON_DIR"
echo "  LOGS_DIR:       $LOGS_DIR"
echo "  PLATFORM:       $PLATFORM"
echo "  INSTALL_DATE:   $INSTALL_DATE"
echo ""
read -rp "Proceed? (y/N): " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# --- Step 1: Substitute placeholders ---
info "Substituting placeholders across all .md files..."

# Substitute placeholders in all .md files EXCEPT scripts/ — validate.sh contains
# placeholder patterns that must not be substituted (they are the search patterns).
find . -name "*.md" -not -path './scripts/*' -exec sed -i \
    -e "s|{OWNER}|$OWNER|g" \
    -e "s|{WORKSPACE_ROOT}|$WORKSPACE_ROOT|g" \
    -e "s|{OPENCLAW_CRON_DIR}|$CRON_DIR|g" \
    -e "s|{OPENCLAW_LOGS_DIR}|$LOGS_DIR|g" \
    -e "s|{PLATFORM}|$PLATFORM|g" \
    -e "s|{INSTALL_DATE}|$INSTALL_DATE|g" \
    {} \;

# Also substitute in VERSION file (not .md)
sed -i \
    -e "s|{INSTALL_DATE}|$INSTALL_DATE|g" \
    -e "s|{WORKSPACE_ROOT}|$WORKSPACE_ROOT|g" \
    VERSION 2>/dev/null || true

info "Placeholders substituted."

# --- Step 2: Generate integrity hashes ---
info "Generating SHA-256 hashes for protected files..."

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

MANIFEST="audit/INTEGRITY-MANIFEST.md"
HASHES_OK=true

for f in "${PROTECTED_FILES[@]}"; do
    if [[ -f "$f" ]]; then
        HASH=$(sha256sum "$f" | cut -d' ' -f1)
        # Update the manifest: replace the placeholder line for this file
        # Use Python to update the manifest row; sed pipe-delimiter conflicts make
        # inline sed unreliable here.  Falls back gracefully if the row is not found.
        python3 -c "
import sys, re, pathlib
f, h, d, o, m = sys.argv[1:]
p = pathlib.Path(m)
t = p.read_text()
pat = r'(\| \x60' + re.escape(f) + r'\x60 \|)[^\n]*'
rep = r'\1 ' + h + ' | ' + d + ' | ' + o + '-signed-v0.1.0 |'
p.write_text(re.sub(pat, rep, t))
" "$f" "$HASH" "$INSTALL_DATE" "$OWNER" "$MANIFEST" 2>/dev/null || \
            warn "  Could not auto-update manifest row for $f — paste the hash manually."
        info "  $f: $HASH"
    else
        warn "  $f: NOT FOUND"
        HASHES_OK=false
    fi
done

if $HASHES_OK; then
    info "All hashes generated. Paste them into $MANIFEST if auto-update failed."
else
    warn "Some protected files were not found. Check your file structure."
fi

# --- Step 3: Create directories ---
info "Ensuring required directories exist..."
mkdir -p memory/ skills/ PROJECTS/

# --- Step 4: Model configuration check ---
echo ""
info "Checking model configuration..."
if command -v openclaw &>/dev/null; then
    OC_MODEL=$(openclaw models status 2>/dev/null | grep '^Default' | awk '{print $NF}' || true)
    OC_AUTH=$(openclaw models status 2>/dev/null | grep 'Providers w/ OAuth' || true)
    if [[ -n "$OC_MODEL" ]]; then
        info "Default model: $OC_MODEL"
    else
        warn "Could not detect default model. Run: openclaw models status"
    fi
    if [[ -n "$OC_AUTH" ]]; then
        info "Auth: $OC_AUTH"
    else
        warn "No authenticated providers detected."
        warn "NightClaw requires a working model to run cron passes."
        warn "Recommended: OpenAI OAuth (openclaw models auth login) or Google Gemini API key."
        warn "See DEPLOY.md §Model Configuration for setup instructions."
    fi
else
    warn "openclaw not found in PATH — skipping model check. Verify model config before starting crons."
fi

# --- Done ---
echo ""
info "Installation complete."
echo ""
echo "Next steps:"
echo "  1. Open audit/INTEGRITY-MANIFEST.md and confirm each hash row was updated"
echo "     by this script. If any row shows a stale or placeholder hash value,"
echo "     paste the hash printed above for that file manually."
echo "  2. Open SOUL.md and replace {DOMAIN_ANCHOR} with your domain focus"
echo "     (see the inline comments in SOUL.md for guidance and an example)"
echo "  3. Configure USER.md with your profile and any domain restrictions"
echo "  4. Run: openclaw config set agents.defaults.timeoutSeconds 600"
echo "  5. Create two crons per DEPLOY.md §Step 5"
echo "  6. Run: bash scripts/validate.sh to check internal consistency"
echo "  7. Start a new project: bash scripts/new-project.sh <slug>"
echo ""
