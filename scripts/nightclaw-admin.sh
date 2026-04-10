#!/usr/bin/env bash
set -euo pipefail

# nightclaw-admin — Deterministic owner CLI for NightClaw
# Usage: bash scripts/nightclaw-admin.sh <command> [args...]
# Run from workspace root.
#
# Commands:
#   status                      Show active projects, phase, last pass, next objective
#   alerts                      Show current unresolved notifications
#   approve <slug>              Approve a LONGRUNNER-DRAFT → activate project
#   decline <slug> [reason]     Decline a draft → delete it
#   pause <slug>                Pause an active project
#   unpause <slug>              Resume a paused project
#   priority <slug> <n>         Set project priority
#   done <line-number>          Mark a NOTIFICATIONS.md entry resolved
#   guide <message>             Inject guidance the worker picks up at T1.5
#   arm [PA-NNN] [expires]      Activate a pre-approval for overnight runs
#   disarm [PA-NNN]             Deactivate a pre-approval
#   log                         Show recent audit log entries
#
# All write commands log to audit/AUDIT-LOG.md and audit/CHANGE-LOG.md
# in the same format the cron sessions use.

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info()  { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
dim()   { echo -e "${DIM}$1${NC}"; }

# ── Workspace detection ─────────────────────────────────────────────────────
# Detect workspace root: prefer NIGHTCLAW_ROOT env var, then walk up from cwd
detect_root() {
    if [[ -n "${NIGHTCLAW_ROOT:-}" ]] && [[ -f "$NIGHTCLAW_ROOT/ACTIVE-PROJECTS.md" ]]; then
        echo "$NIGHTCLAW_ROOT"
        return
    fi
    local dir="$PWD"
    while [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/ACTIVE-PROJECTS.md" ]] && [[ -d "$dir/orchestration-os" ]]; then
            echo "$dir"
            return
        fi
        dir="$(dirname "$dir")"
    done
    error "Cannot find NightClaw workspace. Run from workspace root or set NIGHTCLAW_ROOT."
}

ROOT="$(detect_root)"
cd "$ROOT"

ACTIVE_PROJECTS="ACTIVE-PROJECTS.md"
NOTIFICATIONS="NOTIFICATIONS.md"
AUDIT_LOG="audit/AUDIT-LOG.md"
CHANGE_LOG="audit/CHANGE-LOG.md"
PREAPPROVAL="orchestration-os/OPS-PREAPPROVAL.md"

NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
NOW_HUMAN=$(date +"%Y-%m-%d %H:%M")
TODAY=$(date +%Y-%m-%d)

# ── Audit helpers ───────────────────────────────────────────────────────────
# All writes go through these so the audit trail matches cron format exactly.

audit_log() {
    # Usage: audit_log "TYPE:ACTION | RESULT:SUCCESS | key=value"
    echo "TASK:ADMIN.${NOW_ISO} | $1" >> "$AUDIT_LOG"
}

change_log() {
    # Usage: change_log "field_path" "old_value" "new_value" "reason"
    echo "$1|$2|$3|owner|ADMIN|${NOW_ISO}|${NOW_ISO}|$4|none" >> "$CHANGE_LOG"
}

# ── Slug validation ─────────────────────────────────────────────────────────
validate_slug() {
    local slug="$1"
    [[ -n "$slug" ]] || error "Slug required."
    [[ "$slug" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || error "Invalid slug format: $slug"
}

# ── Table helpers ───────────────────────────────────────────────────────────
# Parse ACTIVE-PROJECTS.md table. Returns pipe-delimited fields.
# Table columns: Priority | Project Slug | LONGRUNNER Path | Phase | Status | Last Worker Pass | Escalation Pending

get_project_row() {
    local slug="$1"
    grep -E "^\|[^|]*\|[[:space:]]*${slug}[[:space:]]*\|" "$ACTIVE_PROJECTS" || true
}

get_project_field() {
    # Usage: get_project_field <slug> <field-number>
    # Split by |: [0]="" [1]=priority [2]=slug [3]=path [4]=phase [5]=status [6]=last-pass [7]=escalation
    # So field-number maps directly to the split index.
    local slug="$1" field="$2"
    local row
    row=$(get_project_row "$slug")
    [[ -n "$row" ]] || return 1
    echo "$row" | awk -F'|' -v f="$field" '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $(f+1)); print $(f+1)}'
}

update_project_field() {
    # Usage: update_project_field <slug> <field-number> <new-value>
    local slug="$1" field="$2" new_value="$3"
    python3 -c "
import sys, re

slug = sys.argv[1]
field_idx = int(sys.argv[2])
new_val = sys.argv[3]
filepath = sys.argv[4]

with open(filepath, 'r') as f:
    lines = f.readlines()

found = False
for i, line in enumerate(lines):
    if not line.startswith('|'):
        continue
    cols = line.split('|')
    if len(cols) < 8:
        continue
    if cols[2].strip() == slug:
        old_val = cols[field_idx].strip()
        # Preserve column width with padding
        width = len(cols[field_idx]) - 1  # subtract one for leading space
        cols[field_idx] = ' ' + new_val.ljust(width)
        lines[i] = '|'.join(cols)
        found = True
        print(f'OLD:{old_val}')
        print(f'NEW:{new_val}')
        break

if not found:
    print('NOT_FOUND', file=sys.stderr)
    sys.exit(1)

with open(filepath, 'w') as f:
    f.writelines(lines)
" "$slug" "$field" "$new_value" "$ACTIVE_PROJECTS"
}

# ── Commands ────────────────────────────────────────────────────────────────

cmd_status() {
    echo ""
    echo -e "${BOLD}NightClaw Status${NC}"
    echo -e "${DIM}$(date)${NC}"
    echo ""

    # Run dispatch to get structured view
    local dispatch_output
    dispatch_output=$(python3 scripts/nightclaw-ops.py dispatch 2>/dev/null || echo "DISPATCH_ERROR")

    if [[ "$dispatch_output" == "IDLE" ]]; then
        echo -e "  ${CYAN}No active projects.${NC} System is idle."
        echo ""
    elif [[ "$dispatch_output" == "DISPATCH_ERROR" ]]; then
        warn "Could not run dispatch. Falling back to file read."
    fi

    # Parse ACTIVE-PROJECTS.md — only the Active Project Scoreboard table
    # The scoreboard has columns: Priority | Slug | Path | Phase | Status | Last Pass | Escalation
    # We identify data rows by: starts with |, has 8 pipe-delimited fields, and field 4 contains a path (PROJECTS/)
    local has_projects=false
    local in_scoreboard=false
    while IFS= read -r line; do
        # Detect the scoreboard section
        if [[ "$line" == *"Active Project Scoreboard"* ]]; then
            in_scoreboard=true
            continue
        fi
        # Stop at next heading after scoreboard
        if [[ "$in_scoreboard" == "true" ]] && [[ "$line" =~ ^##\  ]] && [[ ! "$line" == *"Scoreboard"* ]]; then
            break
        fi
        [[ "$in_scoreboard" == "true" ]] || continue

        # Skip non-table lines, header, separator, placeholder
        [[ "$line" =~ ^\| ]] || continue
        [[ ! "$line" =~ "Priority" ]] || continue
        [[ ! "$line" =~ "---" ]] || continue
        [[ ! "$line" =~ "no projects yet" ]] || continue

        # Validate this looks like a data row (has PROJECTS/ or LONGRUNNER in path field)
        local path_field
        path_field=$(echo "$line" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $4); print $4}')
        [[ "$path_field" == *"PROJECTS/"* ]] || [[ "$path_field" == *"LONGRUNNER"* ]] || continue

        has_projects=true
        local priority slug phase status last_pass escalation
        priority=$(echo "$line" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2}')
        slug=$(echo "$line" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $3); print $3}')
        phase=$(echo "$line" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $5); print $5}')
        status=$(echo "$line" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $6); print $6}')
        last_pass=$(echo "$line" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $7); print $7}')
        escalation=$(echo "$line" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $8); print $8}')

        # Color-code status
        local status_color="$NC"
        case "$status" in
            active) status_color="$GREEN" ;;
            paused) status_color="$YELLOW" ;;
            blocked|TRANSITION-HOLD) status_color="$RED" ;;
            complete) status_color="$DIM" ;;
        esac

        echo -e "  ${BOLD}[$priority]${NC} ${CYAN}$slug${NC}  ${status_color}$status${NC}  phase: $phase"

        # Get next objective from longrunner-extract if active
        if [[ "$status" == "active" ]]; then
            local extract_output
            extract_output=$(python3 scripts/nightclaw-ops.py longrunner-extract "$slug" 2>/dev/null || true)
            if [[ -n "$extract_output" ]]; then
                local next_obj
                next_obj=$(echo "$extract_output" | grep "^next_objective:" | sed 's/^next_objective://' | xargs)
                [[ -n "$next_obj" ]] && echo -e "       ${DIM}next: $next_obj${NC}"
            fi
        fi

        if [[ "$escalation" != "none" ]] && [[ "$escalation" != "—" ]] && [[ -n "$escalation" ]]; then
            echo -e "       ${RED}escalation: $escalation${NC}"
        fi
        [[ "$last_pass" != "—" ]] && [[ -n "$last_pass" ]] && echo -e "       ${DIM}last pass: $last_pass${NC}"

    done < "$ACTIVE_PROJECTS"

    if ! $has_projects; then
        echo -e "  ${DIM}No projects in ACTIVE-PROJECTS.md${NC}"
    fi

    # Check for pending drafts
    echo ""
    local drafts
    drafts=$(find PROJECTS/ -name "LONGRUNNER-DRAFT.md" 2>/dev/null || true)
    if [[ -n "$drafts" ]]; then
        echo -e "  ${YELLOW}Pending drafts:${NC}"
        while IFS= read -r draft; do
            local draft_slug
            draft_slug=$(echo "$draft" | sed 's|PROJECTS/||;s|/LONGRUNNER-DRAFT.md||')
            echo -e "    ${CYAN}$draft_slug${NC}  →  nightclaw-admin approve $draft_slug"
        done <<< "$drafts"
    fi

    # Lock status — read LOCK.md directly (check-lock.py expects a session arg)
    echo ""
    if [[ -f "LOCK.md" ]]; then
        local lock_status_val
        lock_status_val=$(grep -m1 '^status:' LOCK.md | awk '{print $2}' || echo "unknown")
        if [[ "$lock_status_val" == "locked" ]]; then
            local holder
            holder=$(grep -m1 '^holder:' LOCK.md | awk '{print $2}' || echo "unknown")
            echo -e "  ${RED}Lock: HELD${NC} (holder: $holder)"
        else
            echo -e "  ${DIM}Lock: released${NC}"
        fi
    else
        echo -e "  ${DIM}Lock: no lock file${NC}"
    fi
    echo ""
}

cmd_alerts() {
    echo ""
    echo -e "${BOLD}Current Alerts${NC}"
    echo ""

    local scan_output
    scan_output=$(python3 scripts/nightclaw-ops.py scan-notifications 2>/dev/null || echo "ERROR")

    if [[ "$scan_output" == "NONE" ]]; then
        echo -e "  ${DIM}No unresolved alerts.${NC}"
        echo ""
        return
    fi

    if [[ "$scan_output" == "ERROR" ]]; then
        warn "Could not run scan-notifications. Reading file directly."
        # Fall through to raw display
        local in_alerts=false
        while IFS= read -r line; do
            if [[ "$line" == "## Current Alerts" ]]; then
                in_alerts=true
                continue
            fi
            $in_alerts && [[ -n "$line" ]] && echo "  $line"
        done < "$NOTIFICATIONS"
        echo ""
        return
    fi

    # Parse FOUND entries
    local entry_num=0
    while IFS= read -r line; do
        [[ "$line" == FOUND:* ]] || continue
        entry_num=$((entry_num + 1))
        local line_num priority summary
        line_num=$(echo "$line" | sed 's/FOUND:line=\([0-9]*\).*/\1/')
        priority=$(echo "$line" | sed 's/.*priority=\([^:]*\).*/\1/')
        summary=$(echo "$line" | sed 's/.*priority=[^:]*://')

        local pcolor="$NC"
        case "$priority" in
            CRITICAL) pcolor="$RED" ;;
            HIGH) pcolor="$RED" ;;
            MEDIUM) pcolor="$YELLOW" ;;
            LOW|INFO) pcolor="$DIM" ;;
        esac

        echo -e "  ${BOLD}#${entry_num}${NC} ${pcolor}[$priority]${NC} $summary"
        echo -e "       ${DIM}line $line_num — resolve: nightclaw-admin done $line_num${NC}"
    done <<< "$scan_output"

    echo ""
}

cmd_approve() {
    local slug="${1:-}"
    validate_slug "$slug"

    local draft_path="PROJECTS/$slug/LONGRUNNER-DRAFT.md"
    local longrunner_path="PROJECTS/$slug/LONGRUNNER.md"

    [[ -f "$draft_path" ]] || error "No draft found at $draft_path"
    [[ ! -f "$longrunner_path" ]] || error "LONGRUNNER.md already exists for $slug — cannot approve over existing project"

    # --- Atomic approve: copy first, insert row, then delete draft ---
    # If any step fails, the draft still exists and the copy is cleaned up.

    # Step 1: Copy draft → LONGRUNNER (draft stays as rollback anchor)
    cp "$draft_path" "$longrunner_path"

    # Step 2: Insert/update ACTIVE-PROJECTS row
    local row_result=0
    local existing_row
    existing_row=$(get_project_row "$slug")
    if [[ -n "$existing_row" ]]; then
        local old_status
        old_status=$(get_project_field "$slug" 5) || true
        update_project_field "$slug" 5 "active" || row_result=$?
        if [[ $row_result -ne 0 ]]; then
            rm -f "$longrunner_path"
            error "Failed to update ACTIVE-PROJECTS.md row. Rolled back — draft preserved at $draft_path"
        fi
        change_log "FILE:ACTIVE-PROJECTS.md#${slug}.status" "${old_status:-unknown}" "active" "owner approved draft via nightclaw-admin"
        info "Updated existing row in ACTIVE-PROJECTS.md → active"
    else
        local max_priority
        max_priority=$(awk -F'|' 'NR>3 && /\|/ {gsub(/ /,"",$2); if ($2 ~ /^[0-9]+$/) print $2}' \
            "$ACTIVE_PROJECTS" 2>/dev/null | sort -n | tail -1)
        local next_priority=$((${max_priority:-0} + 1))

        local new_row="| $next_priority | $slug | PROJECTS/$slug/LONGRUNNER.md | exploration | active | — | none |"

        python3 -c "
import sys
filepath = sys.argv[1]
new_row = sys.argv[2]

with open(filepath, 'r') as f:
    content = f.read()

placeholder = '| — | _(no projects yet)_ | — | — | — | — | — |'
if placeholder in content:
    content = content.replace(placeholder, new_row, 1)
else:
    lines = content.split('\n')
    last_table_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('|') and '---' not in stripped and 'Priority' not in stripped:
            last_table_idx = i
    if last_table_idx >= 0:
        lines.insert(last_table_idx + 1, new_row)
    else:
        lines.append(new_row)
    content = '\n'.join(lines)

with open(filepath, 'w') as f:
    f.write(content)
" "$ACTIVE_PROJECTS" "$new_row" || row_result=$?

        if [[ $row_result -ne 0 ]]; then
            rm -f "$longrunner_path"
            error "Failed to insert ACTIVE-PROJECTS.md row. Rolled back — draft preserved at $draft_path"
        fi

        change_log "FILE:ACTIVE-PROJECTS.md#${slug}" "NONE" "priority=${next_priority},status=active,phase=exploration" "owner approved draft via nightclaw-admin"
        info "Added row to ACTIVE-PROJECTS.md (priority $next_priority)"
    fi

    # Step 3: Both writes succeeded — delete the draft (completes the rename)
    rm -f "$draft_path"
    info "Removed draft (LONGRUNNER-DRAFT.md → LONGRUNNER.md)"

    # Step 4: Audit + notification (non-critical — failure here doesn't break state)
    audit_log "TYPE:ADMIN_APPROVE | RESULT:SUCCESS | PROJECT:$slug | DRAFT:$draft_path"

    echo "" >> "$NOTIFICATIONS"
    echo "[$NOW_HUMAN] | Priority: INFO | Project: $slug | Status: APPROVED" >> "$NOTIFICATIONS"
    echo "Context: Owner approved project draft via nightclaw-admin CLI." >> "$NOTIFICATIONS"
    echo "Action required: NONE — worker will pick up on next pass." >> "$NOTIFICATIONS"

    info "Project '$slug' approved. Worker picks it up on next pass."
}

cmd_decline() {
    local slug="${1:-}"
    local reason="${2:-Owner declined without stated reason}"
    validate_slug "$slug"

    local draft_path="PROJECTS/$slug/LONGRUNNER-DRAFT.md"
    [[ -f "$draft_path" ]] || error "No draft found at $draft_path"

    # Confirm
    echo -e "Declining draft: ${CYAN}$slug${NC}"
    echo -e "Reason: $reason"
    read -rp "Confirm? (y/N): " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

    rm "$draft_path"
    info "Deleted $draft_path"

    # Remove empty project dir if nothing else in it
    local project_dir="PROJECTS/$slug"
    if [[ -d "$project_dir" ]] && [[ -z "$(ls -A "$project_dir" 2>/dev/null)" ]]; then
        rmdir "$project_dir"
        dim "Removed empty directory $project_dir"
    fi

    audit_log "TYPE:ADMIN_DECLINE | RESULT:SUCCESS | PROJECT:$slug | REASON:${reason:0:200}"
    change_log "FILE:PROJECTS/${slug}/LONGRUNNER-DRAFT.md" "EXISTS" "DELETED" "owner declined draft via nightclaw-admin: $reason"

    echo "" >> "$NOTIFICATIONS"
    echo "[$NOW_HUMAN] | Priority: INFO | Project: $slug | Status: DECLINED" >> "$NOTIFICATIONS"
    echo "Context: Owner declined project draft via nightclaw-admin CLI. Reason: $reason" >> "$NOTIFICATIONS"
    echo "Action required: NONE" >> "$NOTIFICATIONS"

    info "Draft '$slug' declined."
}

cmd_pause() {
    local slug="${1:-}"
    validate_slug "$slug"

    local current_status
    current_status=$(get_project_field "$slug" 5) || error "Project '$slug' not found in ACTIVE-PROJECTS.md"

    [[ "$current_status" == "active" ]] || [[ "$current_status" == "TRANSITION-HOLD" ]] || \
        error "Cannot pause project with status '$current_status'. Must be 'active' or 'TRANSITION-HOLD'."

    update_project_field "$slug" 5 "paused" > /dev/null
    change_log "FILE:ACTIVE-PROJECTS.md#${slug}.status" "$current_status" "paused" "owner paused via nightclaw-admin"
    audit_log "TYPE:ADMIN_PAUSE | RESULT:SUCCESS | PROJECT:$slug | PREV_STATUS:$current_status"

    info "Project '$slug' paused (was: $current_status). Worker will skip on next pass."
}

cmd_unpause() {
    local slug="${1:-}"
    validate_slug "$slug"

    local current_status
    current_status=$(get_project_field "$slug" 5) || error "Project '$slug' not found in ACTIVE-PROJECTS.md"

    [[ "$current_status" == "paused" ]] || error "Cannot unpause project with status '$current_status'. Must be 'paused'."

    update_project_field "$slug" 5 "active" > /dev/null
    change_log "FILE:ACTIVE-PROJECTS.md#${slug}.status" "paused" "active" "owner unpaused via nightclaw-admin"
    audit_log "TYPE:ADMIN_UNPAUSE | RESULT:SUCCESS | PROJECT:$slug"

    info "Project '$slug' resumed. Worker will route to it based on priority."
}

cmd_priority() {
    local slug="${1:-}"
    local new_priority="${2:-}"
    validate_slug "$slug"
    [[ -n "$new_priority" ]] || error "Usage: nightclaw-admin priority <slug> <number>"
    [[ "$new_priority" =~ ^[0-9]+$ ]] || error "Priority must be a positive integer."

    local old_priority
    old_priority=$(get_project_field "$slug" 1) || error "Project '$slug' not found in ACTIVE-PROJECTS.md"

    update_project_field "$slug" 1 "$new_priority" > /dev/null
    change_log "FILE:ACTIVE-PROJECTS.md#${slug}.priority" "$old_priority" "$new_priority" "owner reprioritized via nightclaw-admin"
    audit_log "TYPE:ADMIN_PRIORITY | RESULT:SUCCESS | PROJECT:$slug | OLD:$old_priority | NEW:$new_priority"

    info "Project '$slug' priority: $old_priority → $new_priority"
}

cmd_done() {
    local line_num="${1:-}"
    [[ -n "$line_num" ]] || error "Usage: nightclaw-admin done <line-number>"
    [[ "$line_num" =~ ^[0-9]+$ ]] || error "Line number must be a positive integer."

    # Read the line to confirm what we're resolving
    local target_line
    target_line=$(sed -n "${line_num}p" "$NOTIFICATIONS")
    [[ -n "$target_line" ]] || error "Line $line_num is empty or out of range."

    echo -e "Resolving: ${DIM}$target_line${NC}"
    read -rp "Mark as done? (y/N): " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

    # Prepend [DONE] to the line
    sed -i "${line_num}s/^/[DONE $NOW_HUMAN] /" "$NOTIFICATIONS"

    audit_log "TYPE:ADMIN_RESOLVE | RESULT:SUCCESS | FILE:NOTIFICATIONS.md | LINE:$line_num"

    info "Notification at line $line_num marked done."
}

cmd_guide() {
    local message="${*}"
    [[ -n "$message" ]] || error "Usage: nightclaw-admin guide <message>"

    # Write in the format the worker reads at T1.5 via scan-notifications
    echo "" >> "$NOTIFICATIONS"
    echo "[$NOW_HUMAN] | Priority: HIGH | Project: guidance | Status: OWNER-DIRECTIVE" >> "$NOTIFICATIONS"
    echo "Context: Owner guidance injected via nightclaw-admin CLI." >> "$NOTIFICATIONS"
    echo "Action required: $message" >> "$NOTIFICATIONS"

    audit_log "TYPE:ADMIN_GUIDE | RESULT:SUCCESS | MESSAGE:${message:0:200}"

    info "Guidance written to NOTIFICATIONS.md. Worker picks it up at T1.5."
    dim "To verify: nightclaw-admin alerts"
}

cmd_arm() {
    local pa_id="${1:-}"
    local expires="${2:-}"

    if [[ -z "$pa_id" ]]; then
        # Show current PA status
        echo ""
        echo -e "${BOLD}Pre-Approval Status${NC}"
        echo ""
        grep -E "^## PA-[0-9]+" "$PREAPPROVAL" | while IFS= read -r line; do
            local id status_val
            id=$(echo "$line" | grep -o "PA-[0-9]*")
            status_val=$(echo "$line" | sed 's/.*Status: \([A-Z]*\).*/\1/')
            if [[ "$status_val" == "ACTIVE" ]]; then
                echo -e "  ${GREEN}$id${NC}: ACTIVE"
            elif [[ "$status_val" == "INACTIVE" ]]; then
                echo -e "  ${DIM}$id${NC}: INACTIVE"
            else
                echo -e "  $id: $status_val"
            fi
        done
        echo ""
        echo "Usage: nightclaw-admin arm <PA-NNN> [expires-date]"
        echo "Example: nightclaw-admin arm PA-001 2026-04-11"
        return
    fi

    [[ "$pa_id" =~ ^PA-[0-9]+$ ]] || error "Invalid PA ID format. Use PA-NNN (e.g. PA-001)"

    # Verify PA exists in file
    grep -q "^## $pa_id " "$PREAPPROVAL" || error "$pa_id not found in OPS-PREAPPROVAL.md"

    # Set expires: if provided use it, otherwise default to tomorrow 08:00
    if [[ -z "$expires" ]]; then
        expires=$(date -d "+1 day" +%Y-%m-%d 2>/dev/null || date -v+1d +%Y-%m-%d 2>/dev/null || echo "")
        [[ -n "$expires" ]] && expires="${expires} 08:00"
    fi
    [[ -n "$expires" ]] || error "Could not calculate default expiry. Provide one: nightclaw-admin arm $pa_id YYYY-MM-DD"

    # Update Status: INACTIVE → ACTIVE and set Expires
    python3 -c "
import sys, re

pa_id = sys.argv[1]
expires = sys.argv[2]
filepath = sys.argv[3]

with open(filepath, 'r') as f:
    content = f.read()

# Match the PA header line and update status + expires
pattern = r'(## ' + re.escape(pa_id) + r' \| Status: )\w+( \| Expires: ).*'
replacement = r'\g<1>ACTIVE\g<2>' + expires

new_content, count = re.subn(pattern, replacement, content)
if count == 0:
    print(f'Could not find {pa_id} header to update', file=sys.stderr)
    sys.exit(1)

with open(filepath, 'w') as f:
    f.write(new_content)

print(f'UPDATED:{pa_id}:ACTIVE:expires={expires}')
" "$pa_id" "$expires" "$PREAPPROVAL" > /dev/null

    # Re-sign (PROTECTED file)
    if [[ -x scripts/resign.sh ]]; then
        bash scripts/resign.sh "$PREAPPROVAL" > /dev/null 2>&1
        info "Re-signed $PREAPPROVAL"
    else
        warn "resign.sh not found — run manually: bash scripts/resign.sh $PREAPPROVAL"
    fi

    change_log "FILE:${PREAPPROVAL}#${pa_id}.status" "INACTIVE" "ACTIVE" "owner armed via nightclaw-admin, expires $expires"
    audit_log "TYPE:ADMIN_ARM | RESULT:SUCCESS | PA:$pa_id | EXPIRES:$expires"

    info "$pa_id armed (expires: $expires). Crons will honor this on next pass."
}

cmd_disarm() {
    local pa_id="${1:-}"
    [[ -n "$pa_id" ]] || error "Usage: nightclaw-admin disarm <PA-NNN>"
    [[ "$pa_id" =~ ^PA-[0-9]+$ ]] || error "Invalid PA ID format. Use PA-NNN (e.g. PA-001)"

    grep -q "^## $pa_id " "$PREAPPROVAL" || error "$pa_id not found in OPS-PREAPPROVAL.md"

    python3 -c "
import sys, re

pa_id = sys.argv[1]
filepath = sys.argv[2]

with open(filepath, 'r') as f:
    content = f.read()

pattern = r'(## ' + re.escape(pa_id) + r' \| Status: )\w+( \| Expires: ).*'
replacement = r'\g<1>INACTIVE\g<2>—'

new_content, count = re.subn(pattern, replacement, content)
if count == 0:
    print(f'Could not find {pa_id} header to update', file=sys.stderr)
    sys.exit(1)

with open(filepath, 'w') as f:
    f.write(new_content)

print(f'UPDATED:{pa_id}:INACTIVE')
" "$pa_id" "$PREAPPROVAL" > /dev/null

    # Re-sign (PROTECTED file)
    if [[ -x scripts/resign.sh ]]; then
        bash scripts/resign.sh "$PREAPPROVAL" > /dev/null 2>&1
        info "Re-signed $PREAPPROVAL"
    else
        warn "resign.sh not found — run manually: bash scripts/resign.sh $PREAPPROVAL"
    fi

    change_log "FILE:${PREAPPROVAL}#${pa_id}.status" "ACTIVE" "INACTIVE" "owner disarmed via nightclaw-admin"
    audit_log "TYPE:ADMIN_DISARM | RESULT:SUCCESS | PA:$pa_id"

    info "$pa_id disarmed. Crons operate in conservative mode for this action class."
}

cmd_log() {
    local count="${1:-10}"
    echo ""
    echo -e "${BOLD}Recent Audit Log${NC} (last $count entries)"
    echo ""
    # Show last N non-empty, non-comment lines from audit log
    grep -v "^$\|^#\|^---\|^<!--\|^\`\`\`" "$AUDIT_LOG" | tail -n "$count" | while IFS= read -r line; do
        # Color-code by result
        if echo "$line" | grep -q "RESULT:FAIL\|RESULT:BLOCKED"; then
            echo -e "  ${RED}$line${NC}"
        elif echo "$line" | grep -q "RESULT:PASS\|RESULT:SUCCESS"; then
            echo -e "  ${GREEN}$line${NC}"
        else
            echo -e "  $line"
        fi
    done
    echo ""
}

# ── Usage ───────────────────────────────────────────────────────────────────
usage() {
    echo ""
    echo -e "${BOLD}nightclaw-admin${NC} — Owner CLI for NightClaw"
    echo ""
    echo "Usage: bash scripts/nightclaw-admin.sh <command> [args...]"
    echo ""
    echo -e "${BOLD}Read commands:${NC}"
    echo "  status                      Active projects, phases, next objectives"
    echo "  alerts                      Current unresolved notifications"
    echo "  log [n]                     Last n audit log entries (default 10)"
    echo ""
    echo -e "${BOLD}Project commands:${NC}"
    echo "  approve <slug>              Approve a pending project draft"
    echo "  decline <slug> [reason]     Decline and delete a draft"
    echo "  pause <slug>                Pause an active project"
    echo "  unpause <slug>              Resume a paused project"
    echo "  priority <slug> <n>         Set project priority number"
    echo ""
    echo -e "${BOLD}Communication:${NC}"
    echo "  done <line-number>          Mark a notification resolved"
    echo "  guide <message>             Inject guidance for next worker pass"
    echo ""
    echo -e "${BOLD}Overnight control:${NC}"
    echo "  arm [PA-NNN] [expires]      Activate a pre-approval (re-signs automatically)"
    echo "  disarm <PA-NNN>             Deactivate a pre-approval (re-signs automatically)"
    echo ""
    echo "Run from workspace root, or set NIGHTCLAW_ROOT."
    echo ""
}

# ── Dispatch ────────────────────────────────────────────────────────────────
CMD="${1:-}"
shift 2>/dev/null || true

case "$CMD" in
    status)     cmd_status ;;
    alerts)     cmd_alerts ;;
    approve)    cmd_approve "$@" ;;
    decline)    cmd_decline "$@" ;;
    pause)      cmd_pause "$@" ;;
    unpause)    cmd_unpause "$@" ;;
    priority)   cmd_priority "$@" ;;
    done)       cmd_done "$@" ;;
    guide)      cmd_guide "$@" ;;
    arm)        cmd_arm "$@" ;;
    disarm)     cmd_disarm "$@" ;;
    log)        cmd_log "$@" ;;
    -h|--help|help|"") usage ;;
    *)          error "Unknown command: $CMD. Run with --help for usage." ;;
esac
