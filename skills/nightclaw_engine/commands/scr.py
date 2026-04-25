"""nightclaw_engine.commands.scr — SCR self-consistency driver.

Thin CLI wrapper around :mod:`nightclaw_engine.protocol.integrity`
which owns every predicate. Output format is preserved byte-for-byte
so downstream prompts still parse it the same way.
"""
from __future__ import annotations

import re
import sys

from . import _shared


def cmd_scr_verify():
    """R6 self-consistency rules SCR-01 through SCR-11 plus CL5 (12 predicates).

    Thin driver: the predicate registry in
    ``nightclaw_engine.protocol.integrity`` owns the rule bodies, and the
    list of rules + severities lives in ``orchestration-os/schema/scr_rules.yaml``.
    Output format is preserved byte-for-byte so downstream prompts still parse
    it the same way::

        SCR-NN:PASS|FAIL|SKIP|INFO <details>
        [indented continuation lines for INFO dumps]
        CL5:PASS|FAIL <details>
        RESULT:PASS | RESULT:FAIL rules=[...]
    """
    from nightclaw_engine.schema.loader import SchemaError, load as _load_schema
    from nightclaw_engine.protocol.integrity import run_scr_verify

    schema_dir = _shared.ROOT / "orchestration-os" / "schema"
    try:
        model = _load_schema(schema_dir)
    except SchemaError as exc:
        print(f"ERROR: schema_load_failed: {exc}")
        sys.exit(1)

    report = run_scr_verify(model, _shared.ROOT)
    for line in report.lines:
        print(line)
    if report.failed:
        sys.exit(1)
    sys.exit(0)


__all__ = ["cmd_scr_verify"]
