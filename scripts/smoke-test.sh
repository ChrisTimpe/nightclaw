#!/usr/bin/env bash
# NightClaw v0.1.0 — First-Run Smoke Test
#
# Simulates a new user's complete setup flow and verifies the system
# reaches a valid running state without T0 HALT.
#
# Usage:
#   bash scripts/smoke-test.sh                    # uses zip in current dir
#   bash scripts/smoke-test.sh /path/to/file.zip  # explicit zip path
#
# Run from the workspace root of an installed deployment, or point at a zip.
# All tests run in an isolated temp directory — your workspace is never touched.

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS=0; FAIL=0; WARN_COUNT=0

pass()  { echo -e "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; WARN_COUNT=$((WARN_COUNT+1)); }
step()  { echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }
detail(){ echo "       → $1"; }

# ── Cleanup ──────────────────────────────────────────────────────────────────
SMOKE_DIR=""
cleanup() { [[ -n "$SMOKE_DIR" ]] && rm -rf "$SMOKE_DIR"; }
trap cleanup EXIT

# ── Locate zip ───────────────────────────────────────────────────────────────
ZIP="${1:-}"
if [[ -z "$ZIP" ]]; then
    ZIP=$(ls nightclaw-v*.zip 2>/dev/null | head -1 || true)
fi
if [[ -z "$ZIP" || ! -f "$ZIP" ]]; then
    echo "Usage: bash scripts/smoke-test.sh [path-to-zip]"
    echo "Zip not found. Provide path or run from a directory containing nightclaw-v*.zip"
    exit 1
fi

echo ""
echo "NightClaw v0.1.0 — First-Run Smoke Test"
echo "========================================"
echo "Zip:  $ZIP"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ── Step 0: Extract ──────────────────────────────────────────────────────────
step "0  Extract zip to isolated temp directory"

SMOKE_DIR=$(mktemp -d)
WS="$SMOKE_DIR/ws"

unzip -q "$ZIP" -d "$SMOKE_DIR" 2>/dev/null

# Accept any top-level folder name
SOUL=$(find "$SMOKE_DIR" -maxdepth 3 -name "SOUL.md" | head -1)
if [[ -z "$SOUL" ]]; then
    fail "SOUL.md not found inside zip — is this a NightClaw zip?"; exit 1
fi
EXTRACTED_ROOT=$(dirname "$SOUL")
mv "$EXTRACTED_ROOT" "$WS"
cd "$WS"
chmod +x scripts/*.sh 2>/dev/null || true

pass "Extracted to isolated workspace"

# ── Step 1: install.sh ───────────────────────────────────────────────────────
step "1  install.sh — placeholder substitution and initial signing"

OWNER="smoketestuser"
WSROOT="$WS"

printf "${OWNER}\n${WSROOT}\n${WSROOT}/.cron\n${WSROOT}/.logs\nLinux\ny\n" \
    | bash scripts/install.sh > /tmp/nc-smoke-install.txt 2>&1
INSTALL_EXIT=$?

if [[ $INSTALL_EXIT -eq 0 ]]; then
    pass "install.sh completed (exit 0)"
else
    fail "install.sh failed (exit $INSTALL_EXIT)"
    cat /tmp/nc-smoke-install.txt
    echo "Cannot continue without a successful install."; exit 1
fi

# Verify {OWNER} was substituted
if grep -q '{OWNER}' SOUL.md 2>/dev/null; then
    # The Domain Anchor placeholder is intentionally left — check real {OWNER} tokens
    REMAINING=$(grep -c '{OWNER}' SOUL.md || true)
    if [[ "$REMAINING" -gt 1 ]]; then
        fail "install.sh: {OWNER} not substituted in SOUL.md ($REMAINING occurrences remain)"
    else
        pass "install.sh: {OWNER} substituted (Domain Anchor placeholder retained as expected)"
    fi
else
    pass "install.sh: all {OWNER} tokens substituted"
fi

# Integrity immediately after install: must be 11/11
INTEGRITY=$(bash scripts/verify-integrity.sh 2>&1 | grep "^Results:")
if [[ "$INTEGRITY" == *"11 passed, 0 failed"* ]]; then
    pass "Initial integrity: 11/11 — install.sh signed all protected files correctly"
else
    fail "Initial integrity failed right after install.sh: $INTEGRITY"
fi

# ── Step 2: Domain Anchor edit + resign ─────────────────────────────────────
step "2  Domain Anchor edit → T0 would HALT → resign → T0 clear"

# Simulate user editing SOUL.md (required per DEPLOY.md Step 2.5)
python3 - << 'PY'
import pathlib, sys
p = pathlib.Path('SOUL.md')
content = p.read_text()
if '{DOMAIN_ANCHOR}' in content:
    new = 'AI agent orchestration and governance research. Evaluating LLM agent frameworks, behavioral discipline patterns, and overnight autonomous operation for developer tooling workflows.'
    p.write_text(content.replace('{DOMAIN_ANCHOR}', new))
    print('Domain Anchor set')
else:
    print('WARNING: {DOMAIN_ANCHOR} not found — Domain Anchor may already be set')
PY

# Confirm hash is now stale (this is the bug we found)
STALE_CHECK=$(bash scripts/verify-integrity.sh 2>&1)
SOUL_STALE=$(echo "$STALE_CHECK" | grep "SOUL.md" | grep -c "FAIL" || true)
if [[ "$SOUL_STALE" -gt 0 ]]; then
    pass "Confirmed: editing SOUL.md without resign produces stale hash (T0 would HALT)"
else
    warn "SOUL.md hash did not change — Domain Anchor edit may not have modified content"
fi

# Resign and re-verify
bash scripts/resign.sh SOUL.md > /dev/null 2>&1
INTEGRITY=$(bash scripts/verify-integrity.sh 2>&1 | grep "^Results:")
if [[ "$INTEGRITY" == *"11 passed, 0 failed"* ]]; then
    pass "After resign.sh SOUL.md: 11/11 — T0 would proceed"
else
    fail "After resign.sh SOUL.md: integrity still failing ($INTEGRITY)"
fi

# ── Step 3: USER.md edit + resign ────────────────────────────────────────────
step "3  USER.md edit (name + timezone) → resign → verify"

python3 - << 'PY'
import pathlib
p = pathlib.Path('USER.md')
content = p.read_text()
content = content.replace(
    '- **What to call them:**',
    '- **What to call them:** SmokeTestUser'
).replace(
    '- **Pronouns:** _(optional)_',
    '- **Pronouns:** they/them'
).replace(
    '- **Timezone:**',
    '- **Timezone:** America/Los_Angeles'
)
p.write_text(content)
print('USER.md updated with name, pronouns, timezone')
PY

USER_STALE=$(bash scripts/verify-integrity.sh 2>&1 | grep "USER.md" | grep -c "FAIL" || true)
if [[ "$USER_STALE" -gt 0 ]]; then
    pass "Confirmed: editing USER.md without resign produces stale hash (T0 would HALT)"
else
    warn "USER.md hash did not change after edit — check if content actually differed"
fi

bash scripts/resign.sh USER.md > /dev/null 2>&1
INTEGRITY=$(bash scripts/verify-integrity.sh 2>&1 | grep "^Results:")
if [[ "$INTEGRITY" == *"11 passed, 0 failed"* ]]; then
    pass "After resign.sh USER.md: 11/11 — T0 would proceed"
else
    fail "After resign.sh USER.md: integrity still failing ($INTEGRITY)"
fi

# ── Step 4: PA activation + resign ──────────────────────────────────────────
step "4  Activate PA-001 + PA-002 (pre-overnight) → resign → verify"

TOMORROW=$(python3 -c "from datetime import date, timedelta; print((date.today() + timedelta(days=1)).strftime('%Y-%m-%d 08:00'))")

python3 - << PY
import pathlib
p = pathlib.Path('orchestration-os/OPS-PREAPPROVAL.md')
content = p.read_text()
content = content.replace(
    '## PA-001 | Status: INACTIVE | Expires: \u2014',
    '## PA-001 | Status: ACTIVE | Expires: $TOMORROW'
).replace(
    '## PA-002 | Status: INACTIVE | Expires: \u2014',
    '## PA-002 | Status: ACTIVE | Expires: $TOMORROW'
)
p.write_text(content)
print('PA-001 and PA-002 activated (expires: $TOMORROW)')
PY

PA_STALE=$(bash scripts/verify-integrity.sh 2>&1 | grep "OPS-PREAPPROVAL" | grep -c "FAIL" || true)
if [[ "$PA_STALE" -gt 0 ]]; then
    pass "Confirmed: editing OPS-PREAPPROVAL.md without resign produces stale hash (T0 would HALT)"
else
    warn "OPS-PREAPPROVAL.md hash did not change — PA status may already have been ACTIVE"
fi

bash scripts/resign.sh orchestration-os/OPS-PREAPPROVAL.md > /dev/null 2>&1
INTEGRITY=$(bash scripts/verify-integrity.sh 2>&1 | grep "^Results:")
if [[ "$INTEGRITY" == *"11 passed, 0 failed"* ]]; then
    pass "After resign.sh OPS-PREAPPROVAL.md: 11/11 — T0 would proceed"
else
    fail "After resign.sh OPS-PREAPPROVAL.md: integrity still failing ($INTEGRITY)"
fi

# ── Step 5: validate.sh ──────────────────────────────────────────────────────
step "5  validate.sh — internal consistency (96 checks, 0 failures)"

VALIDATE_OUT=$(bash scripts/validate.sh 2>&1)
RESULTS=$(echo "$VALIDATE_OUT" | grep "^Results:")
VFAILED=$(echo "$RESULTS" | grep -oP '\d+ failed' | grep -oP '\d+' || echo "0")
VPASSED=$(echo "$RESULTS" | grep -oP '\d+ passed' | grep -oP '\d+' || echo "0")
VWARN=$(echo "$RESULTS" | grep -oP '\d+ warnings' | grep -oP '\d+' || echo "0")

if [[ "$VFAILED" -eq 0 ]]; then
    pass "validate.sh: $RESULTS"
    if [[ "$VWARN" -gt 0 ]]; then
        detail "$VWARN non-blocking warning(s) (Domain Anchor check, openclaw version — expected)"
    fi
else
    fail "validate.sh: $VFAILED check(s) failed"
    echo "$VALIDATE_OUT" | grep "\[FAIL\]" | while read line; do detail "$line"; done
fi

# ── Step 6: new-project.sh ───────────────────────────────────────────────────
step "6  new-project.sh — create and register first project"

printf "y\n" | bash scripts/new-project.sh smoke-first-project > /tmp/nc-smoke-np.txt 2>&1
NP_EXIT=$?

if [[ $NP_EXIT -eq 0 ]]; then
    pass "new-project.sh: exit 0"
else
    fail "new-project.sh: exit $NP_EXIT"
    cat /tmp/nc-smoke-np.txt
fi

if [[ -f "PROJECTS/smoke-first-project/LONGRUNNER.md" ]]; then
    pass "LONGRUNNER.md scaffolded at PROJECTS/smoke-first-project/"
else
    fail "LONGRUNNER.md not created"
fi

if grep -q "smoke-first-project" ACTIVE-PROJECTS.md 2>/dev/null; then
    ROW=$(grep "smoke-first-project" ACTIVE-PROJECTS.md)
    pass "Project row registered in ACTIVE-PROJECTS.md"
    detail "$ROW"
else
    fail "Project row NOT found in ACTIVE-PROJECTS.md — dispatch table won't route to it"
fi

# ── Step 7: T0 hash simulation ───────────────────────────────────────────────
step "7  T0 simulation — direct hash check for all 11 protected files"
echo "   (This is exactly what the worker computes at T0 before each cron pass)"

T0_PASS=0; T0_FAIL=0

python3 - << 'PY'
import pathlib, hashlib, re, sys

manifest = pathlib.Path('audit/INTEGRITY-MANIFEST.md').read_text()
t0_pass = 0; t0_fail = 0

for line in manifest.splitlines():
    m = re.match(r'\|\s*`([^`]+)`\s*\|\s*([a-f0-9]{64})\s*\|', line)
    if not m:
        continue
    filepath, expected = m.group(1), m.group(2)
    p = pathlib.Path(filepath)
    if not p.exists():
        print(f'  [FAIL] {filepath}: FILE MISSING')
        t0_fail += 1
        continue
    computed = hashlib.sha256(p.read_bytes()).hexdigest()
    if computed == expected:
        print(f'  [PASS] {filepath}')
        t0_pass += 1
    else:
        print(f'  [FAIL] {filepath}')
        print(f'         expected: {expected}')
        print(f'         computed: {computed}')
        t0_fail += 1

print(f'T0_RESULT:{t0_pass}:{t0_fail}')
PY

T0_LINE=$(python3 - << 'PY'
import pathlib, hashlib, re
manifest = pathlib.Path('audit/INTEGRITY-MANIFEST.md').read_text()
t0_pass = 0; t0_fail = 0
for line in manifest.splitlines():
    m = re.match(r'\|\s*`([^`]+)`\s*\|\s*([a-f0-9]{64})\s*\|', line)
    if not m: continue
    p = pathlib.Path(m.group(1))
    if not p.exists(): t0_fail += 1; continue
    computed = hashlib.sha256(p.read_bytes()).hexdigest()
    if computed == m.group(2): t0_pass += 1
    else: t0_fail += 1
print(f'{t0_pass}:{t0_fail}')
PY
)

T0P=$(echo "$T0_LINE" | cut -d: -f1)
T0F=$(echo "$T0_LINE" | cut -d: -f2)

if [[ "$T0F" -eq 0 ]]; then
    pass "T0 simulation: $T0P/$T0P files match — worker would NOT halt on first pass"
else
    fail "T0 simulation: $T0F file(s) would cause BUNDLE:integrity_fail → HALT"
fi

# ── Step 8: LOCK.md state ────────────────────────────────────────────────────
step "8  LOCK.md — ready to accept first cron"

LOCK_STATUS=$(grep "^status:" LOCK.md 2>/dev/null | head -1 | awk '{print $2}' || echo "MISSING")
if [[ "$LOCK_STATUS" == "released" ]]; then
    pass "LOCK.md: status=released — worker can acquire lock on first STARTUP"
else
    fail "LOCK.md: status=$LOCK_STATUS — system would defer or crash on first STARTUP"
fi

# Verify stale check logic works for released state
LOCK_CHECK=$(python3 scripts/check-lock.py "smoke-test" 2>/dev/null || echo "ERROR")
if [[ "$LOCK_CHECK" == "PROCEED"* ]]; then
    pass "check-lock.py: PROCEED for released lock — STARTUP would proceed"
else
    fail "check-lock.py: unexpected output '$LOCK_CHECK' for released lock"
fi

# Verify stale check for partial lock (BUG-3 fix validation)
ORIG_LOCK=$(cat LOCK.md)
python3 - << 'PY'
import pathlib
p = pathlib.Path('LOCK.md')
content = p.read_text()
# Simulate a crash after writing status:locked but before writing timestamps
content = content.replace('status: released', 'status: locked')
content = content.replace('holder: —', 'holder: session:nightclaw-worker')
content = content.replace('run_id: —', 'run_id: RUN-20260407-001')
# Intentionally leave locked_at and expires_at as em-dashes (crash scenario)
p.write_text(content)
print('Simulated crash-partial lock written')
PY

PARTIAL_CHECK=$(python3 scripts/check-lock.py "smoke-test" 2>/dev/null || echo "ERROR")
if [[ "$PARTIAL_CHECK" == "PROCEED"* ]]; then
    pass "check-lock.py: PROCEED for crash-partial lock (missing timestamps → stale, BUG-3 fix confirmed)"
elif [[ "$PARTIAL_CHECK" == "DEFER"* ]]; then
    fail "check-lock.py: DEFER for crash-partial lock — BUG-3 fix not working, system would deadlock"
else
    warn "check-lock.py: unexpected output '$PARTIAL_CHECK' for partial lock"
fi

# Restore LOCK.md
echo "$ORIG_LOCK" > LOCK.md

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "========================================="
printf "Smoke Test:  %d passed  %d failed" $PASS $FAIL
[[ $WARN_COUNT -gt 0 ]] && printf "  %d warnings" $WARN_COUNT
echo ""
echo "========================================="

if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}All checks passed.${NC}"
    echo "System reaches a valid running state. Ready for first cron pass."
    exit 0
else
    echo -e "${RED}$FAIL check(s) failed.${NC}"
    echo "The system would halt before completing a useful pass."
    echo "Fix the failures above before starting crons."
    exit 1
fi
