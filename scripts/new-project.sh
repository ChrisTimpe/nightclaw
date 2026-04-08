#!/usr/bin/env bash
set -euo pipefail

# NightClaw — Scaffold a new project
# Usage: bash scripts/new-project.sh <slug>
# Example: bash scripts/new-project.sh market-research
# Run from workspace root.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()  { echo -e "${CYAN}[STEP]${NC} $1"; }

SLUG="${1:-}"

# --- Usage check ---
if [[ -z "$SLUG" ]]; then
    echo "Usage: bash scripts/new-project.sh <slug>"
    echo ""
    echo "The slug is a short lowercase identifier for your project."
    echo "Use hyphens, no spaces."
    echo ""
    echo "Examples:"
    echo "  bash scripts/new-project.sh market-research"
    echo "  bash scripts/new-project.sh competitor-analysis"
    echo "  bash scripts/new-project.sh q2-planning"
    exit 0
fi

# --- Validate slug format ---
if [[ ! "$SLUG" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$ ]]; then
    error "Slug must be lowercase alphanumeric with hyphens only (e.g. market-research)"
fi

PROJECT_DIR="PROJECTS/$SLUG"
LONGRUNNER_PATH="$PROJECT_DIR/LONGRUNNER.md"
OUTPUTS_DIR="$PROJECT_DIR/outputs"
TEMPLATE="orchestration-os/LONGRUNNER-TEMPLATE.md"
ACTIVE_PROJECTS="ACTIVE-PROJECTS.md"
TODAY=$(date +%Y-%m-%d)

# --- Check not already exists ---
if [[ -d "$PROJECT_DIR" ]]; then
    error "Project '$SLUG' already exists at $PROJECT_DIR"
fi

# --- Check template exists ---
[[ -f "$TEMPLATE" ]] || error "LONGRUNNER template not found: $TEMPLATE — run from workspace root"

# --- Check ACTIVE-PROJECTS.md exists ---
[[ -f "$ACTIVE_PROJECTS" ]] || error "ACTIVE-PROJECTS.md not found — run from workspace root"

echo ""
echo "NightClaw — New Project"
echo "======================="
echo ""
echo "Slug:    $SLUG"
echo "Path:    $LONGRUNNER_PATH"
echo "Outputs: $OUTPUTS_DIR"
echo ""

read -rp "Proceed? (y/N): " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# --- Create project directory and outputs folder ---
step "Creating $PROJECT_DIR/"
mkdir -p "$PROJECT_DIR" "$OUTPUTS_DIR"

# --- Copy and customize LONGRUNNER template ---
step "Scaffolding $LONGRUNNER_PATH"
cp "$TEMPLATE" "$LONGRUNNER_PATH"

# Replace template header with project-specific header
sed -i "s/# LONGRUNNER — \[PROJECT NAME\]/# LONGRUNNER — $SLUG/" "$LONGRUNNER_PATH"
sed -i "s|PROJECTS/\[slug\]/LONGRUNNER.md|$LONGRUNNER_PATH|" "$LONGRUNNER_PATH"

# Set started date
sed -i "s/started: \"\"/started: \"$TODAY\"/" "$LONGRUNNER_PATH"

# Set initial status
sed -i 's/status: "active"  # active | complete | blocked | abandoned/status: "active"/' "$LONGRUNNER_PATH"

# --- Determine next priority ---
# Find the highest current priority number and add 1
MAX_PRIORITY=$(awk -F'|' 'NR>3 && /\|/ {gsub(/ /,"",$2); if ($2 ~ /^[0-9]+$/) print $2}' \
    "$ACTIVE_PROJECTS" 2>/dev/null | sort -n | tail -1)
NEXT_PRIORITY=$((${MAX_PRIORITY:-0} + 1))

# --- Add row to ACTIVE-PROJECTS.md ---
step "Adding row to ACTIVE-PROJECTS.md (priority $NEXT_PRIORITY)"

# Find the placeholder row and replace it, or append after the last data row
python3 -c "
import pathlib, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text()
new_row = sys.argv[2]
placeholder = '| — | _(no projects yet)_ | — | — | — | — | — |'
if placeholder in t:
    p.write_text(t.replace(placeholder, new_row, 1))
    print('Placeholder row replaced.')
else:
    lines = t.split('\n')
    last_table_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('|') and '---' not in stripped and 'Priority' not in stripped:
            last_table_idx = i
    if last_table_idx == -1:
        print('Could not find table insertion point — add row manually', file=sys.stderr)
        sys.exit(1)
    lines.insert(last_table_idx + 1, new_row)
    p.write_text('\n'.join(lines))
    print('Row added after last table entry.')
" "$ACTIVE_PROJECTS" "| $NEXT_PRIORITY | $SLUG | $LONGRUNNER_PATH | exploration | active | — | none |"

# --- Done ---
echo ""
info "Project '$SLUG' created."
echo ""
echo "Next steps:"
echo "  1. Open $LONGRUNNER_PATH and fill in:"
echo "     - ## Mission (one sentence: what success looks like)"
echo "     - ## Conflict Check (confirm domain, check USER.md restrictions)"  
echo "     - ## Current Phase → objective and stop_condition"
echo "     - ## Next Pass → objective and tools_required"
echo "  2. Run: bash scripts/validate.sh (confirms LONGRUNNER path is recognized)"
echo "  3. The worker will pick it up on its next scheduled pass."
echo ""
warn "Do not start the worker until you've filled in the Mission and Conflict Check."
echo ""
