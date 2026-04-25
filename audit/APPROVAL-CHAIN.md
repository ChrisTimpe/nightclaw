# APPROVAL-CHAIN.md
<!-- APPEND-ONLY. Records every PA invocation with scope verification. -->
<!-- Purpose: creates a countersigned chain from {OWNER}'s authorization to the agent's action. -->
<!-- Written by: worker pass at point of PA invocation (before executing the authorized action). -->

---

## Purpose

OPS-PREAPPROVAL.md is where {OWNER} grants authorizations.
This file is where the agent records each invocation of those authorizations.

Together they form a complete chain:
  {OWNER} signs → OPS-PREAPPROVAL.md (entry)
  Agent invokes → APPROVAL-CHAIN.md (this file)
  Action executes → AUDIT-LOG.md (event record)

An invocation without a matching APPROVAL-CHAIN entry means the action bypassed the approval system.
{OWNER} can verify any action by cross-referencing all three files.

---

## Entry Format

```
## [PA-xxx]-INVOCATION-[NNN] | [ISO8601Z]
**Pre-approval:** [PA-xxx] (orchestration-os/OPS-PREAPPROVAL.md)
**Invoked by:** session:[session-name] run:[run-id]
**Action authorized:** [exact command or action — same as AUDIT-LOG entry]
**Scope verification:**
  - executable: [value from action] vs allowed: [value from PA entry] → [MATCH | MISMATCH]
  - network: [domain accessed] vs allowed: [PA network scope] → [MATCH | MISMATCH | N/A]
  - write path: [path written] vs allowed: [PA write scope] → [MATCH | MISMATCH]
**Expiry check:** PA expires [date] — invocation at [date] → [WITHIN BOUNDS | EXPIRED]
**Result:** [SUCCESS | BLOCKED — reason]
**{OWNER} notified:** [YES — NOTIFICATIONS.md | NO — within normal bounds]
**Audit entry:** AUDIT-LOG.md [approximate line / timestamp]
```

MISMATCH on any scope field → DO NOT EXECUTE. Append BLOCKED result. Surface to NOTIFICATIONS.md.
EXPIRED PA → DO NOT EXECUTE. Surface to NOTIFICATIONS.md. Set Escalation Pending.

---

## Invocation Log

<!-- Entries appended below. Most recent at bottom. -->
<!-- First real invocation will be PA-001 for your first authorized project pass. -->
