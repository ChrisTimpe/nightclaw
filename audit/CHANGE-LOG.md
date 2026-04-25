# CHANGE-LOG.md
<!-- APPEND-ONLY. Field-level bi-temporal change log. Never edit or delete entries. -->
<!-- Format spec: orchestration-os/REGISTRY.md §R7 —  CHANGE-LOG FORMAT SPECIFICATION -->
<!-- Distinct from AUDIT-LOG.md: AUDIT-LOG = actions. CHANGE-LOG = field state deltas. -->
<!-- Written by: worker T4 (STANDARD/PROTECTED writes). Read by: manager T8 SCR-10 check. -->

---

## Entry Format (reference)
<!-- field_path|old_value|new_value|agent_id|run_id|t_written|t_valid|reason|bundle -->

---

## Log

<!-- Genesis entry — file initialized, no field changes yet -->
FILE:audit/CHANGE-LOG.md#genesis|NONE|INITIALIZED|{OWNER}|RUN-2026-04-21-000|2026-04-21T00:00:00Z|2026-04-21T00:00:00Z|NightClaw orchestration framework bootstrap — file created|none
