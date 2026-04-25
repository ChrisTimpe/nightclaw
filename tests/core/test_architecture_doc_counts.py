"""
internal_enhancement/ARCHITECTURE.md doc-drift gate.

Pass 14 landed this as a direct response to a Pass 13 oversight: the internal architecture document
carried four stale ``**Tests:** N files`` claims (engine: 24 vs actual 16;
bridge: 9 vs 8; monitor: 3 vs 4; ops: 3 vs 2) plus a stale SCR enumeration that
omitted SCR-11. The miss was caught only by human review, not by any gate.

This test closes that gap. It parses internal_enhancement/ARCHITECTURE.md for two kinds of count
claims and cross-checks them against the filesystem. Any drift is a hard test
failure with a precise error message naming the file, the claim, and the
actual value.

Parse contract
--------------
Two claim shapes are recognized, both on stable Markdown patterns:

1. **Package ``.py`` count** — lines of the form::

       ### `nightclaw_<name>/` — <any text> (N `.py` files)

   Checked against the number of ``.py`` files under ``nightclaw_<name>/``
   (excluding ``__pycache__``).

2. **Test file count** — the first line matching ``**Tests:** N file[s] …`` that
   appears *after* a ``### `nightclaw_<name>/…`` heading and before the next
   ``### `` heading. Checked against the canonical test-dir mapping declared
   in ``PACKAGE_TEST_PATHS`` below.

The mapping from package to test paths is declared here (not read from doctrine)
because it *is* the drift surface. Adding a new test file means the author
must decide which package it covers; that decision belongs in this file.

This test does NOT enforce that every test under ``tests/`` appears in the
mapping — only that the internal architecture claims match what the mapping says.
A separate assertion ensures the mapping itself covers every ``test_*.py``
under ``tests/``, so an orphan test file fails the gate.

The canonical ``# @invariant: ID=INV-14 | ...`` comment annotation sits
directly above ``test_package_test_paths_covers_every_test_file`` below,
which is the core drift-detecting assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_MD = REPO_ROOT / "internal_enhancement" / "ARCHITECTURE.md"


# Canonical mapping from package name to the test files that cover it.
# Paths are relative to REPO_ROOT. Globs are resolved with Path.glob.
# Keep this mapping in sync with the "**Tests:**" lines in internal_enhancement/ARCHITECTURE.md.
PACKAGE_TEST_PATHS: dict[str, list[str]] = {
    "nightclaw_engine": [
        "tests/core/test_*.py",
        "tests/engine_e2e/test_*.py",
    ],
    "nightclaw_bridge": [
        "tests/test_bridge_config.py",
        "tests/test_bridge_runtime.py",
        "tests/test_bridge_runtime_e2e.py",
        "tests/test_bridge_server_snapshot.py",
        "tests/test_bridge_sources.py",
        "tests/test_client_handlers.py",
        "tests/test_protocol_payloads.py",
        "tests/test_repository.py",
        "tests/test_server_sink_integration.py",
        "tests/test_snapshot_adapter.py",
        "tests/test_snapshot_contract.py",
    ],
    "nightclaw_monitor": [
        "tests/test_monitor_handler_router.py",
        "tests/test_monitor_selectors.py",
        "tests/test_monitor_store.py",
        "tests/test_state_replay.py",
    ],
    "nightclaw_ops": [
        "tests/test_ops_lifecycle.py",
        "tests/test_telemetry_emit_step.py",
    ],
}


# Regex: ### `nightclaw_xxx/` — some prose (N `.py` files)
_HEADING_PY_COUNT_RE = re.compile(
    r"^###\s+`(nightclaw_[a-z]+)/`.*?\((\d+)\s+`\.py`\s+files\)",
)

# Regex: ### `nightclaw_xxx/` — some prose (may or may not have a count)
_HEADING_RE = re.compile(r"^###\s+`(nightclaw_[a-z]+)/`")

# Regex: **Tests:** N file(s) ...
_TESTS_LINE_RE = re.compile(r"^\*\*Tests:\*\*\s+(\d+)\s+files?\b")


def _read_architecture_md() -> list[str]:
    assert ARCHITECTURE_MD.exists(), f"Missing: {ARCHITECTURE_MD}"
    return ARCHITECTURE_MD.read_text(encoding="utf-8").splitlines()


def _count_py_files(package: str) -> int:
    pkg_dir = REPO_ROOT / package
    assert pkg_dir.is_dir(), f"Missing package dir: {pkg_dir}"
    return sum(
        1
        for p in pkg_dir.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _resolve_test_paths(globs: list[str]) -> set[Path]:
    """Resolve each glob against REPO_ROOT and return the union of matches."""
    resolved: set[Path] = set()
    for pattern in globs:
        # Path.glob does not accept absolute patterns; split off the dir.
        abs_pattern = REPO_ROOT / pattern
        if "*" in pattern:
            parent = abs_pattern.parent
            name_pat = abs_pattern.name
            resolved.update(p for p in parent.glob(name_pat) if p.is_file())
        else:
            if abs_pattern.is_file():
                resolved.add(abs_pattern)
    return resolved


def _parse_architecture_claims() -> tuple[dict[str, int], dict[str, int]]:
    """
    Returns (py_counts, test_counts) where each dict maps package name to
    the N asserted in internal_enhancement/ARCHITECTURE.md. Missing claims are simply absent.
    """
    lines = _read_architecture_md()
    py_counts: dict[str, int] = {}
    test_counts: dict[str, int] = {}

    current_pkg: str | None = None
    for line in lines:
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            current_pkg = heading_match.group(1)
            py_match = _HEADING_PY_COUNT_RE.match(line)
            if py_match:
                py_counts[py_match.group(1)] = int(py_match.group(2))
            continue

        if current_pkg is None:
            continue

        tests_match = _TESTS_LINE_RE.match(line)
        if tests_match and current_pkg not in test_counts:
            # Only first **Tests:** line after heading counts.
            test_counts[current_pkg] = int(tests_match.group(1))

    return py_counts, test_counts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_architecture_md_exists_and_parses():
    """Sanity: internal_enhancement/ARCHITECTURE.md parses and at least one claim is recovered."""
    py_counts, test_counts = _parse_architecture_claims()
    assert py_counts or test_counts, (
        "internal_enhancement/ARCHITECTURE.md parsed, but no claims were recovered. "
        "Either the file has been restructured or the regexes drifted."
    )


@pytest.mark.parametrize("package", sorted(PACKAGE_TEST_PATHS.keys()))
def test_architecture_package_py_count(package: str):
    """
    For every `nightclaw_*/` section that asserts `(N .py files)`, verify N
    matches the actual count on disk.
    """
    py_counts, _ = _parse_architecture_claims()
    if package not in py_counts:
        pytest.skip(
            f"internal_enhancement/ARCHITECTURE.md does not assert a .py count for {package}; "
            f"nothing to drift-check."
        )
    asserted = py_counts[package]
    actual = _count_py_files(package)
    assert asserted == actual, (
        f"internal_enhancement/ARCHITECTURE.md ### `{package}/` heading asserts "
        f"({asserted} `.py` files), but filesystem has {actual}. "
        f"Update the heading."
    )


@pytest.mark.parametrize("package", sorted(PACKAGE_TEST_PATHS.keys()))
def test_architecture_test_count(package: str):
    """
    For every `nightclaw_*/` section, verify the `**Tests:** N files` line
    matches the count of test files covered by PACKAGE_TEST_PATHS[package].
    """
    _, test_counts = _parse_architecture_claims()
    assert package in test_counts, (
        f"internal_enhancement/ARCHITECTURE.md has no `**Tests:** N files` line under "
        f"### `{package}/`. Add one so this gate can check it."
    )
    asserted = test_counts[package]
    resolved = _resolve_test_paths(PACKAGE_TEST_PATHS[package])
    actual = len(resolved)
    assert asserted == actual, (
        f"internal_enhancement/ARCHITECTURE.md ### `{package}/` claims `**Tests:** {asserted} files`, "
        f"but PACKAGE_TEST_PATHS resolves {actual} files. "
        f"Either the mapping is stale or internal_enhancement/ARCHITECTURE.md is stale. "
        f"Resolved files: "
        f"{sorted(str(p.relative_to(REPO_ROOT)) for p in resolved)}"
    )


# @invariant: ID=INV-14 | domain=doctrine/drift | fails_on=internal_enhancement/ARCHITECTURE.md `**Tests:** N files` or `(N `.py` files)` claim diverges from filesystem, or a test file under tests/ is not claimed by any package in PACKAGE_TEST_PATHS | remediation=update the internal architecture count or add the new test file to PACKAGE_TEST_PATHS[<pkg>] in tests/core/test_architecture_doc_counts.py
def test_package_test_paths_covers_every_test_file():
    """
    Every `test_*.py` under `tests/` must be claimed by exactly one package
    in PACKAGE_TEST_PATHS. An orphan test file is a mapping drift.
    """
    tests_root = REPO_ROOT / "tests"
    assert tests_root.is_dir()
    all_test_files = {
        p for p in tests_root.rglob("test_*.py") if "__pycache__" not in p.parts
    }

    claimed: set[Path] = set()
    for pkg, globs in PACKAGE_TEST_PATHS.items():
        claimed.update(_resolve_test_paths(globs))

    orphans = all_test_files - claimed
    unknown = claimed - all_test_files

    assert not orphans, (
        f"Orphan test files not claimed by PACKAGE_TEST_PATHS: "
        f"{sorted(str(p.relative_to(REPO_ROOT)) for p in orphans)}. "
        f"Add them to the appropriate package's mapping."
    )
    assert not unknown, (
        f"PACKAGE_TEST_PATHS claims files that do not exist: "
        f"{sorted(str(p.relative_to(REPO_ROOT)) for p in unknown)}. "
        f"Remove or fix the mapping entry."
    )


def test_no_test_file_is_claimed_twice():
    """
    No test file may be claimed by more than one package in PACKAGE_TEST_PATHS.
    Double-counting would make the `**Tests:** N files` assertions ambiguous.
    """
    seen_by: dict[Path, str] = {}
    for pkg, globs in PACKAGE_TEST_PATHS.items():
        for path in _resolve_test_paths(globs):
            if path in seen_by:
                pytest.fail(
                    f"Test file {path.relative_to(REPO_ROOT)} is claimed by "
                    f"both {seen_by[path]!r} and {pkg!r}."
                )
            seen_by[path] = pkg
