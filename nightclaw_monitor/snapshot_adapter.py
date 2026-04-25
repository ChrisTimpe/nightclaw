"""nightclaw_monitor.snapshot_adapter -- validated JSON bridge for HTML apps.

The three HTML consoles under apps/monitor/ should only read JSON that has
passed validate_sessionssnapshot_payload. This adapter is the single exit
point and the single rejection point.
"""
from __future__ import annotations
import json
from typing import Any, Mapping
from nightclaw_bridge.snapshot_contract import validate_sessionssnapshot_payload

def to_json_for_html(payload: Mapping[str, Any]) -> str:
    validated = validate_sessionssnapshot_payload(payload)
    return json.dumps(validated, sort_keys=True)

def safe_parse_from_html(raw: str) -> dict:
    obj = json.loads(raw)
    return validate_sessionssnapshot_payload(obj)
