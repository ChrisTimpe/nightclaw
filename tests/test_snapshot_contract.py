import pytest
from nightclaw_bridge.snapshot_contract import (
    build_sessionssnapshot_payload, validate_sessionssnapshot_payload
)

def test_build_then_validate_roundtrip():
    snap = {"sessions": {"RUN-1": {"kinds": ["open"]}},
            "ops_timeline": {"RUN-1": [{"tier":"T1","cmd":"dispatch"}]}}
    p = build_sessionssnapshot_payload(snap, "2026-04-17T16:51:00Z")
    out = validate_sessionssnapshot_payload(p)
    assert out["type"] == "sessionssnapshot"
    assert out["snapshot"]["ops_timeline"]["RUN-1"][0]["cmd"] == "dispatch"

def test_validate_rejects_missing_fields():
    with pytest.raises(ValueError):
        validate_sessionssnapshot_payload({"type":"sessionssnapshot"})

def test_validate_rejects_wrong_type():
    with pytest.raises(ValueError):
        validate_sessionssnapshot_payload(
            {"type":"other","snapshot":{"sessions":{},"ops_timeline":{}},
             "t_emitted":"2026-04-17T16:51:00Z"})

def test_validate_rejects_bad_snapshot_shape():
    with pytest.raises(ValueError):
        validate_sessionssnapshot_payload(
            {"type":"sessionssnapshot","snapshot":{"sessions":{}},
             "t_emitted":"2026-04-17T16:51:00Z"})
