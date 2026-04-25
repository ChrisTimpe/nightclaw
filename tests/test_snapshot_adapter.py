import json, pytest
from nightclaw_monitor.snapshot_adapter import to_json_for_html, safe_parse_from_html
from nightclaw_bridge.snapshot_contract import build_sessionssnapshot_payload

def test_roundtrip_json_for_html():
    p = build_sessionssnapshot_payload({"sessions":{}, "ops_timeline":{}},
                                       "2026-04-17T16:51:00Z")
    raw = to_json_for_html(p)
    parsed = safe_parse_from_html(raw)
    assert parsed["type"] == "sessionssnapshot"

def test_adapter_rejects_invalid():
    with pytest.raises(ValueError):
        to_json_for_html({"type":"wrong"})
    with pytest.raises(ValueError):
        safe_parse_from_html(json.dumps({"type":"wrong"}))
