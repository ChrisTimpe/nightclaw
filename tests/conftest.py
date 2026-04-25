"""tests/conftest.py — shared pytest fixtures for the NightClaw test suite.

This file holds autouse fixtures that reset process-global state after every
test. Without them, the test order affects outcomes:

* ``nightclaw_ops.telemetry._custom_transport`` is a module-level variable
  mutated by ``telemetry.set_transport(...)``. Four test files inject custom
  transports (capture lambdas, "boom" error transports) and never reset them.
  A test that expects the real UNIX-socket transport will see a stale
  injection if it runs after one of those tests. See HARDENING-TESTS.md
  finding H-TEST-01.

* ``os.environ["NIGHTCLAW_RUN_ID"]`` is set directly (not via monkeypatch) in
  several tests. Later tests inherit the stale value, which corrupts
  telemetry event assertions that check ``run_id`` equality. See
  HARDENING-TESTS.md finding H-TEST-02.

Both fixtures below are ``autouse=True`` so they apply to every test without
any test file needing to opt in. Neither fixture changes test behaviour for
well-behaved tests — they only cancel mutations left behind by ill-behaved
ones.

Lock compliance: this file adds test infrastructure only. No tool output
strings, no cron prompts, no schema, no bundle protocol, no state-file
format, and no SCR predicates are touched. All six locks hold.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_transport():
    """Reset ``nightclaw_ops.telemetry._custom_transport`` to ``None`` after
    every test. Imported lazily so that tests which never touch telemetry do
    not pay the import cost at collection time — though in practice
    ``nightclaw_ops`` is pure-Python and cheap to import.
    """
    yield
    try:
        from nightclaw_ops import telemetry
    except Exception:
        # If nightclaw_ops cannot be imported (e.g. a test is running in a
        # narrow sandbox that excludes it), there is nothing to reset.
        return
    telemetry.set_transport(None)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    """Guarantee ``NIGHTCLAW_RUN_ID`` is cleared between tests.

    Using ``monkeypatch.delenv(..., raising=False)`` means this is a no-op
    when the env var is unset (the default case) and removes it cleanly
    otherwise. Combined with ``monkeypatch`` teardown, any ``setenv`` inside
    a test is already undone; this extra delenv catches bare
    ``os.environ["NIGHTCLAW_RUN_ID"] = "..."`` assignments that bypass
    monkeypatch.
    """
    yield
    monkeypatch.delenv("NIGHTCLAW_RUN_ID", raising=False)
