"""tests/engine_e2e/test_security_hardening.py — Pass 13 Chunk A.

Covers the four security hardenings landed in Pass 13 Chunk A:

  * H-SEC-01 — integrity-check emits ``WARN:UNSIGNED:<filepath>`` on
    stderr for every manifest row whose hash cell is the blank-hash
    ``_(blank — re-sign on install)_`` placeholder. Stdout must stay
    byte-identical to the pre-Pass-13 contract (Lock 1).
  * H-SEC-02 — ``longrunner-render`` and ``bundle-exec`` reject slugs
    that do not match the canonical ``^[a-z0-9]([a-z0-9-]*[a-z0-9])?$``
    regex (the same rule ``scripts/nightclaw-admin.sh:validate_slug``
    enforces at project creation).
  * H-SEC-03 — the ops ingest unix socket is chmod'd to ``0o600`` so
    local users cannot inject ``OpsStepEvent`` payloads into the bridge
    event log.
  * H-SEC-06 — ``idle-triage`` refuses to follow a ``knowledge-repo``
    path in USER.md that escapes the workspace via ``..`` segments.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_REL = Path("scripts") / "nightclaw-ops.py"


def _run(*args, cwd: Path | None = None):
    base = cwd if cwd is not None else REPO_ROOT
    script = base / SCRIPT_REL
    env = os.environ.copy()
    env["PYTHONPATH"] = str(base) + os.pathsep + env.get("PYTHONPATH", "")
    env["NIGHTCLAW_WORKSPACE"] = str(base)
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(base),
        env=env,
        capture_output=True,
        text=True,
    )


def _sandbox(tmp_path: Path) -> Path:
    dst = tmp_path / "nightclaw_sandbox"
    shutil.copytree(
        REPO_ROOT,
        dst,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", ".git",
            "node_modules", ".venv",
        ),
        dirs_exist_ok=False,
    )
    return dst


# ---------------------------------------------------------------------------
# H-SEC-01 — integrity-check unsigned warning
# ---------------------------------------------------------------------------

def test_integrity_check_stdout_contract_preserved():
    """Stdout must still be the Lock-1 contract: PASS/FAIL/MISSING lines +
    a terminating ``RESULT:PASS files=N`` (or ``RESULT:FAIL ...``) line.
    No ``WARN:`` prefixes are permitted on stdout because the cron prompt
    parsers consume stdout only."""
    r = _run("integrity-check")
    assert r.returncode == 0, f"integrity-check failed: stderr={r.stderr!r}"
    assert "WARN:" not in r.stdout, (
        "integrity-check leaked a WARN line to stdout — this would break "
        "the cron-prompt RESULT:PASS parser (Lock 1)"
    )
    assert re.search(r"^RESULT:PASS files=\d+$", r.stdout, re.MULTILINE), (
        f"integrity-check stdout missing RESULT:PASS terminator: {r.stdout!r}"
    )


_MANIFEST_REL = Path("audit") / "INTEGRITY-MANIFEST.md"
_BLANK_HASH_CELL = "_(blank — re-sign on install)_"
# Rows we synthetically un-sign in the sandbox to prove the WARN:UNSIGNED
# mechanism independently of the current repo's signed state. Choosing two
# files guards against regressions that might match on the first row only.
_SANDBOX_UNSIGN_FILES = ("SOUL.md", "USER.md")


def _unsign_manifest_rows(manifest_path: Path, rel_paths: Iterable[str]) -> int:
    """Replace the SHA256 cell of each named row with the blank placeholder.

    Returns the count of rows actually rewritten. Leaves formatting otherwise
    byte-identical so downstream parsers see the exact pre-install shape.
    """
    text = manifest_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    targets = {p for p in rel_paths}
    rewritten = 0
    for i, line in enumerate(lines):
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        filename = cells[0].strip("`")
        if filename in targets:
            # Preserve column widths by replacing only the second cell.
            parts = line.split("|")
            # parts[0] is leading empty, parts[1]=file, parts[2]=hash, ...
            if len(parts) >= 3:
                parts[2] = f" {_BLANK_HASH_CELL} "
                lines[i] = "|".join(parts)
                rewritten += 1
    manifest_path.write_text("".join(lines), encoding="utf-8")
    return rewritten


def test_integrity_check_emits_warn_unsigned_on_stderr(tmp_path):
    """The H-SEC-01 contract: every manifest row whose hash cell is the blank
    placeholder must appear on stderr as ``WARN:UNSIGNED:<filepath>`` while
    stdout stays on the Lock-1 ``RESULT:PASS`` contract.

    We exercise this against a *sandbox copy* of the repo with two named
    rows deliberately un-signed. This makes the test resilient to the
    production-shipping state of the live manifest (which may be fully
    signed post-install, fully blank pre-install, or anywhere in between)
    while still asserting the exact WARN emission mechanism.
    """
    sandbox = _sandbox(tmp_path)
    rewritten = _unsign_manifest_rows(sandbox / _MANIFEST_REL,
                                       _SANDBOX_UNSIGN_FILES)
    assert rewritten == len(_SANDBOX_UNSIGN_FILES), (
        f"sandbox setup failed: un-signed {rewritten} rows, "
        f"expected {len(_SANDBOX_UNSIGN_FILES)}"
    )

    r = _run("integrity-check", cwd=sandbox)
    assert r.returncode == 0, f"integrity-check failed: stderr={r.stderr!r}"
    warn_lines = [
        ln for ln in r.stderr.splitlines()
        if ln.startswith("WARN:UNSIGNED:")
    ]
    for filename in _SANDBOX_UNSIGN_FILES:
        expected = f"WARN:UNSIGNED:{filename}"
        assert expected in warn_lines, (
            f"expected {expected!r} on stderr, got: {warn_lines!r}"
        )
    # Lock-1: no WARN lines leak into stdout even when stderr has them.
    assert "WARN:" not in r.stdout, (
        "integrity-check leaked WARN to stdout under partial-unsigned state"
    )
    assert re.search(r"^RESULT:PASS files=\d+$", r.stdout, re.MULTILINE), (
        f"integrity-check stdout missing RESULT:PASS terminator: {r.stdout!r}"
    )


# ---------------------------------------------------------------------------
# H-SEC-02 — slug validation
# ---------------------------------------------------------------------------

# The canonical slug regex mirrored from scripts/nightclaw-admin.sh.
SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

BAD_SLUGS = [
    "../etc",           # traversal
    "foo/bar",          # path separator
    "Foo",              # uppercase
    "foo_bar",          # underscore
    "-foo",             # leading dash
    "foo-",             # trailing dash
    "",                 # empty
]


@pytest.mark.parametrize("bad", BAD_SLUGS)
def test_longrunner_render_rejects_invalid_slug(bad: str):
    r = _run("longrunner-render", bad)
    assert SLUG_RE.match(bad) is None, "test fixture sanity"
    assert r.returncode == 1, (
        f"longrunner-render accepted bad slug {bad!r}: stdout={r.stdout!r}"
    )
    assert "LONGRUNNER:ERROR:INVALID_SLUG" in r.stdout, (
        f"expected INVALID_SLUG on stdout for {bad!r}: {r.stdout!r}"
    )


def test_longrunner_render_accepts_valid_slug():
    """Regression guard: the valid-slug path still works — ``example-research``
    is the fixture project that ships with the repo."""
    r = _run("longrunner-render", "example-research")
    assert r.returncode == 0, (
        f"longrunner-render rejected valid slug: stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    assert "LONGRUNNER:OK:" in r.stdout


# ---------------------------------------------------------------------------
# H-SEC-03 — ops socket is chmod 0o600
# ---------------------------------------------------------------------------

def test_ops_sink_socket_is_owner_only(tmp_path: Path):
    """Bring up ``start_ops_sink`` against a tmp socket path and assert its
    mode is ``0o600``. This is the exact call bridge boot uses."""
    # Import lazily so the test module loads even if the bridge package
    # layout changes slightly in the future.
    from nightclaw_bridge.server import start_ops_sink  # type: ignore

    class _FakeRepo:
        def append_event(self, _):  # pragma: no cover - not exercised
            pass

        def load_events(self):  # pragma: no cover - not exercised
            return []

    async def _broadcast(_payload):  # pragma: no cover - not exercised
        return None

    sock_path = tmp_path / "ops.sock"

    async def _bring_up_and_check():
        server = await start_ops_sink(_FakeRepo(), _broadcast, path=str(sock_path))
        try:
            assert sock_path.exists(), "ops socket was not created"
            mode = stat.S_IMODE(sock_path.stat().st_mode)
            assert mode == 0o600, (
                f"ops socket mode is {oct(mode)} — H-SEC-03 requires 0o600 "
                "so only the owning user can write OpsStepEvent payloads"
            )
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(_bring_up_and_check())


# ---------------------------------------------------------------------------
# H-SEC-06 — idle-triage knowledge-repo confinement
# ---------------------------------------------------------------------------

def _write_user_md_knowledge_repo(sandbox: Path, value: str) -> None:
    """Rewrite USER.md in ``sandbox`` so its ``knowledge-repo:`` line points
    at ``value``. USER.md is a blank-hash row in INTEGRITY-MANIFEST.md, so
    mutating it does not break integrity-check (it just changes which
    WARN:UNSIGNED line integrity-check emits, which we are not asserting
    on here)."""
    user_md = sandbox / "USER.md"
    text = user_md.read_text(encoding="utf-8") if user_md.exists() else ""
    lines = text.splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if re.search(r"knowledge.repo", line, re.IGNORECASE):
            lines[i] = f"knowledge-repo: {value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"knowledge-repo: {value}")
    user_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_idle_triage_rejects_traversal_knowledge_repo(tmp_path: Path):
    """A knowledge-repo path with ``..`` segments that resolve outside the
    workspace must not be treated as a valid tier-1 target. The command
    must still succeed (idle-triage is advisory), but the output must NOT
    reference the escaped directory and must NOT claim tier-1 is available
    from it."""
    sandbox = _sandbox(tmp_path)
    # ``../../..`` from workspace root resolves to a directory above the
    # sandbox. It exists, it's a directory, and it has children — which
    # is exactly the pre-patch path that produced IDLE:TIER=1a output.
    _write_user_md_knowledge_repo(sandbox, "../../..")

    r = _run("idle-triage", cwd=sandbox)
    assert r.returncode == 0, f"idle-triage crashed: {r.stderr!r}"
    # Must fall through past tier-1 (which requires a confined knowledge-repo).
    assert "IDLE:TIER=1a" not in r.stdout, (
        f"idle-triage followed traversal knowledge-repo: {r.stdout!r}"
    )
    assert "IDLE:TIER=1b" not in r.stdout
    assert "IDLE:TIER=1c" not in r.stdout


def test_idle_triage_accepts_confined_knowledge_repo(tmp_path: Path):
    """Regression guard: a knowledge-repo path that sits under ROOT is
    still honored. We create a minimal ``kb/00-inbox/x.md`` so tier-1a
    fires and confirms the confinement check didn't over-reject."""
    sandbox = _sandbox(tmp_path)
    kb = sandbox / "kb"
    (kb / "00-inbox").mkdir(parents=True, exist_ok=True)
    (kb / "00-inbox" / "x.md").write_text("seed\n", encoding="utf-8")
    _write_user_md_knowledge_repo(sandbox, "kb")

    r = _run("idle-triage", cwd=sandbox)
    assert r.returncode == 0, f"idle-triage crashed: {r.stderr!r}"
    assert "IDLE:TIER=1a:ACTION=inbox_scan" in r.stdout, (
        f"idle-triage did not honor confined knowledge-repo: {r.stdout!r}"
    )
