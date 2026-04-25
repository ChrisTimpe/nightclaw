"""nightclaw_engine.commands.model_tier — Model tier switching via platform CLI.

Single command:

* ``set-model-tier`` — reads MODEL-TIERS.md, resolves model ID for the given
  tier, calls ``openclaw models set`` + ``openclaw config apply``, then
  verifies the change took effect via ``openclaw config get``.

Design contract:
  - Called at T9, after BUNDLE:session_close fires and LOCK.md is released.
  - Never raises — all failures are logged to stdout as WARN lines so the
    session audit record captures them without crashing T9.
  - Does not write to any workspace file. Pure platform config call.
  - Manager cron is unaffected: it carries a hardcoded --model flag which
    takes precedence over the platform default this command sets.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from . import _shared


# ---------------------------------------------------------------------------
# MODEL-TIERS.md parser
# ---------------------------------------------------------------------------

_TIER_RE = re.compile(
    r"^(lightweight|standard|heavy)\s*:\s*(.+)$",
    re.IGNORECASE,
)

_VALID_TIERS = frozenset({"lightweight", "standard", "heavy"})


def _parse_model_tiers(root: Path) -> dict[str, str]:
    """Parse MODEL-TIERS.md and return {tier: model_id}.

    Reads the yaml block between ```yaml and ``` fences.
    Returns empty dict if the file is missing or unparseable.
    """
    path = root / "MODEL-TIERS.md"
    if not path.exists():
        return {}

    tiers: dict[str, str] = {}
    in_yaml = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "```yaml":
            in_yaml = True
            continue
        if stripped == "```" and in_yaml:
            break
        if not in_yaml:
            continue
        m = _TIER_RE.match(stripped)
        if not m:
            continue
        tier = m.group(1).lower()
        model_id = m.group(2).strip()
        # Skip unfilled install placeholders
        if model_id.startswith("{") and model_id.endswith("}"):
            continue
        tiers[tier] = model_id

    return tiers


# ---------------------------------------------------------------------------
# Platform CLI helpers — all failures are non-fatal (return False + print WARN)
# ---------------------------------------------------------------------------

def _run(cmd: list[str], label: str) -> tuple[bool, str]:
    """Run a subprocess command. Returns (success, stdout_stripped)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            print(
                f"WARN:SET_MODEL_TIER:{label}:exit={result.returncode}"
                f":{stderr[:120] if stderr else 'no stderr'}",
                file=sys.stderr,
            )
            return False, stdout
        return True, stdout
    except FileNotFoundError:
        print(
            f"WARN:SET_MODEL_TIER:{label}:openclaw not found in PATH"
            " — model tier switch skipped",
            file=sys.stderr,
        )
        return False, ""
    except subprocess.TimeoutExpired:
        print(
            f"WARN:SET_MODEL_TIER:{label}:timeout after 15s"
            " — model tier switch skipped",
            file=sys.stderr,
        )
        return False, ""
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARN:SET_MODEL_TIER:{label}:unexpected:{exc}",
            file=sys.stderr,
        )
        return False, ""


def _switch_model(model_id: str) -> bool:
    """Execute the three-step platform model switch. Returns True on full success."""

    # Step 1 — write new model to config
    ok1, _ = _run(["openclaw", "models", "set", model_id], "models_set")
    if not ok1:
        print("WARN:SET_MODEL_TIER:models_set failed — config not updated")
        return False

    # Step 2 — signal gateway hot reload
    ok2, _ = _run(["openclaw", "config", "apply"], "config_apply")
    if not ok2:
        # Non-fatal: config was written, gateway may still pick it up via
        # file-watch within seconds. Log and continue.
        print("WARN:SET_MODEL_TIER:config_apply failed — gateway may need restart")

    # Step 3 — verify the change is live
    ok3, stdout = _run(
        ["openclaw", "config", "get", "agents.defaults.model.primary"],
        "config_get",
    )
    if not ok3:
        print("WARN:SET_MODEL_TIER:config_get failed — cannot verify switch")
        return ok2  # partial success

    # stdout is the raw value returned by config get — may be JSON or plain
    # e.g. {"primary": "provider/model-id"} or just the model ID string
    if model_id in stdout:
        print(f"SET_MODEL_TIER:OK:tier={sys.argv[2] if len(sys.argv) > 2 else '?'}:model={model_id}")
        return True

    print(
        f"WARN:SET_MODEL_TIER:verify_mismatch"
        f":expected={model_id}:got={stdout[:80]}"
    )
    return False


# ---------------------------------------------------------------------------
# Command entry point
# ---------------------------------------------------------------------------

def cmd_set_model_tier():
    """Switch the platform default model to the one mapped to a given tier.

    Usage: set-model-tier <tier>
    Tier:  lightweight | standard | heavy

    Reads MODEL-TIERS.md for the model ID mapping.
    Calls: openclaw models set <id> → openclaw config apply → verify.
    All failures are non-fatal WARN lines — T9 never aborts on this step.
    """
    if len(sys.argv) < 3:
        print("ERROR:USAGE: set-model-tier <lightweight|standard|heavy>", file=sys.stderr)
        sys.exit(2)

    tier = sys.argv[2].strip().lower()
    if tier not in _VALID_TIERS:
        print(
            f"ERROR:SET_MODEL_TIER:invalid tier {tier!r}"
            f" — must be one of: {', '.join(sorted(_VALID_TIERS))}",
            file=sys.stderr,
        )
        sys.exit(2)

    tiers = _parse_model_tiers(_shared.ROOT)

    if not tiers:
        print(
            "WARN:SET_MODEL_TIER:MODEL-TIERS.md missing or empty"
            " — model tier switch skipped. Create MODEL-TIERS.md to enable."
        )
        sys.exit(0)  # non-fatal — feature simply not configured

    model_id = tiers.get(tier)
    if not model_id:
        print(
            f"WARN:SET_MODEL_TIER:tier={tier} not found in MODEL-TIERS.md"
            " — model tier switch skipped"
        )
        sys.exit(0)  # non-fatal — tier not mapped

    _switch_model(model_id)
    # Always exit 0 — set-model-tier failure must never abort T9
    sys.exit(0)


__all__ = ["cmd_set_model_tier"]
