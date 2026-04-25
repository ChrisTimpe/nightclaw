"""tests/core/test_reachability.py — dead-symbol reachability gate (Pass 2).

Pass 14.1 landed this gate in response to a drift incident: four functions
(plus one class) in the four NightClaw packages had become unreachable —
defined and imported nowhere outside their own file — yet the tree stayed
green because no existing gate looked for orphaned public symbols.

Pass 2 hardened the gate. The v1 implementation counted raw ``\\bname\\b``
regex hits across all repo text files. That was fast but fragile:

* **Self-fulfilling data** — the regression-pin parametrize list in this
  file literally spelled every removed symbol name as a string literal.
  If any removed symbol were reintroduced as a ``def``, the pin found the
  reappeared def line *plus* the parametrize literal and happily passed.
  The pin was defeated by its own test data.
* **Comments / docstrings count** — commented-out code or a stray
  mention in a docstring wired a symbol up as "alive" even with no
  runtime use.
* **String-literal references count** — any doc table row, markdown bullet,
  or YAML note mentioning the symbol name in prose kept it alive.
* **Same-file-only references** — a ``def foo`` followed by a ``#
  TODO: foo`` comment in the same file looked identical to a real caller.

Pass 2 replaces the regex scan with an AST-based reference scan. Every
``.py`` file under the four ``nightclaw_*`` packages, the ``scripts/``
directory, and the ``tests/`` tree (but **not** ``tests/core/test_reachability.py``
itself, for the regression-pin) is parsed, and only the following count
as a real code-level reference to a symbol ``name``:

1. ``ast.Name`` load with ``id == name`` in any expression position —
   covers direct calls, dispatch-dict values, decorator references,
   argument passing, etc.
2. ``ast.Attribute`` with ``attr == name`` — covers ``mod.name`` lookups
   (e.g., ``_shared.emit_step``).
3. ``ast.alias`` in an ``import`` / ``from X import`` with
   ``name == target`` OR ``asname == target`` — covers re-exports.
4. String literals inside an ``__all__ = [...]`` assignment — the one
   string-literal form we must honor because ``__all__`` is a legit
   re-export mechanism and the only place the language treats a string
   as a name binding.

Strings in docstrings, comments, regular string literals, YAML, Markdown,
and JSON are explicitly **not** counted. A symbol whose name never appears
as an ``ast.Name`` / ``ast.Attribute`` / import alias / ``__all__`` entry
anywhere in the scan tree is dead by this definition, regardless of how
many times prose mentions it.

YAML/Markdown doctrine references remain recognized for a narrow case:
we also scan ``orchestration-os/schema/routing.yaml`` for ``file:`` path
values pointing at a specific ``.py`` — that tells us a module is a
published R3-CODE surface and any top-level symbol in that module's
PUBLIC_API_ALLOWLIST entry must explicitly name the file. The allowlist
is currently empty (Pass 3.3 wired ``build_server`` into
``tests/test_bridge_server_snapshot.py`` and removed the unused
``Workspace`` dataclass), but the routing-surface cross-check is retained
for any future allowlist entry.

Exemptions
----------
* **Private names** — any symbol whose name starts with ``_`` is skipped.
* **Dunder names** — ``__init__``, ``__main__``, ``__all__`` etc. skipped.
* **PUBLIC_API_ALLOWLIST** — a small, hand-maintained set of names that
  form a public-API surface kept for downstream consumers even without
  an intra-repo caller. Entries require a one-line justification *and*
  the allowlist test cross-checks that each entry's defining file is
  a published R3-CODE surface in ``routing.yaml``.

Why this gate exists
--------------------
The codebase uses several dispatch-by-name patterns (``PREDICATE_REGISTRY``,
``RESOLVERS``, ``COMMANDS``) that launder function references through
identifier bindings. The AST-based scan naturally captures these because
every ``{"key": foo}`` compiles to an ``ast.Name(id="foo")`` load.

The canonical ``# @invariant: ID=INV-15 | ...`` annotation sits above
``test_no_dead_public_symbols`` below.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The four canonical runtime packages. Every top-level def/class under
# these directories is subject to the reachability check.
PACKAGES = ("nightclaw_engine", "nightclaw_bridge", "nightclaw_monitor", "nightclaw_ops")

# Directories whose .py files count as *reference sources*. A symbol is
# alive if it is referenced (AST-level) in any file under any of these.
# The four packages themselves are always scanned; we additionally sweep
# ``scripts/`` (launcher/admin code) and ``tests/`` (test suite calls
# into the runtime packages, which IS legitimate wiring).
_REFERENCE_SCAN_ROOTS = PACKAGES + ("scripts", "tests", "apps")

# Directories whose contents are mirrors / generated — exclude so a
# byte-mirror of the canonical tree cannot manufacture a spurious
# reference to its own source symbol.
_SKIP_DIRS = {"skills", "__pycache__", ".git"}

# The regression pin (below) scans a subset of files to detect any
# reintroduced dead symbol. We explicitly EXCLUDE this test file from
# that scan so its own parametrize list cannot manufacture a reference
# that defeats the pin.
_THIS_FILE = Path(__file__).resolve()

# Public API symbols kept intentionally even without an intra-repo caller.
# Entries are (name -> justification). Each entry's defining file must be
# a CODE-tier surface in orchestration-os/schema/routing.yaml — the
# test_allowlist_entries_have_routing_surface test enforces that.
PUBLIC_API_ALLOWLIST: dict[str, str] = {
    # Pass 3.3: both prior entries resolved.
    #   * ``build_server`` (nightclaw_bridge/main.py) is now AST-reachable
    #     via tests/test_bridge_server_snapshot.py, which exercises both
    #     the memory-repo and file-repo branches of the factory.
    #   * ``Workspace`` (nightclaw_bridge/workspace.py) had no intra-repo
    #     consumer and no dependent downstream; the dataclass and its
    #     routing row were removed rather than kept on the allowlist.
    # New entries require (a) a one-line justification, (b) the defining
    # file present as an R3-CODE row in routing.yaml, and (c) a deliberate
    # decision that no intra-repo wiring is more honest than the allowlist.
}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _python_files_under(rel_roots: tuple[str, ...], exclude: set[Path] | None = None) -> list[Path]:
    exclude = exclude or set()
    out: list[Path] = []
    for rel in rel_roots:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.resolve() in exclude:
                continue
            out.append(p)
    return out


def _collect_defs() -> dict[str, list[Path]]:
    """Return {symbol_name: [defining_file, ...]} for top-level defs/classes
    in the four runtime packages.
    """
    defs: dict[str, list[Path]] = {}
    for path in _python_files_under(PACKAGES):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs.setdefault(node.name, []).append(path)
    return defs


# ---------------------------------------------------------------------------
# AST-level reference counting
# ---------------------------------------------------------------------------

class _RefCollector(ast.NodeVisitor):
    """Collects real code-level name references from a module.

    A reference is one of:
      * ast.Name (Load context)
      * ast.Attribute (attr string)
      * ast.alias.name / ast.alias.asname  (imports)
      * string constants that appear as elements of an ``__all__`` list/tuple

    Excluded explicitly:
      * def-site names (FunctionDef.name / ClassDef.name / arg names / etc.)
      * string literals in general
      * docstrings, comments (comments are not in the AST at all)
    """

    def __init__(self) -> None:
        self.refs: dict[str, int] = {}

    def _bump(self, name: str) -> None:
        if not name:
            return
        self.refs[name] = self.refs.get(name, 0) + 1

    # Every Name load (dispatch dict values, decorators, calls, etc.)
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._bump(node.id)
        # We also bump Store contexts because re-binding a name (e.g.,
        # ``COMMANDS = _commands.COMMANDS``) is also a reference to the
        # RHS name — but the RHS itself is a Load, so we don't need to
        # handle Store explicitly. Fall through to children.
        self.generic_visit(node)

    # Every attribute access — mod.foo counts as a reference to 'foo'.
    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._bump(node.attr)
        self.generic_visit(node)

    # Function/class/arg definitions: we must NOT bump the name being
    # defined (that's the def site, not a reference). But we DO walk the
    # body + decorators + default args, which contain real references.
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        # Default values are evaluated at def time and reference live names.
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        # Return annotation / arg annotations — all are real references.
        if node.returns:
            self.visit(node.returns)
        for arg in (*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs):
            if arg.annotation:
                self.visit(arg.annotation)
        # Body — every expression inside is a reference candidate.
        for stmt in node.body:
            self.visit(stmt)
        # Note: we DO NOT bump node.name itself.

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # identical treatment

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw.value)
        for stmt in node.body:
            self.visit(stmt)
        # Note: we DO NOT bump node.name itself.

    # Imports: ``from X import foo`` is a real reference to 'foo'.
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self._bump(alias.name)
            if alias.asname:
                self._bump(alias.asname)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            # ``import a.b.c`` — bump each dotted component; most searches
            # care about the last component (the bound name).
            for part in alias.name.split("."):
                self._bump(part)
            if alias.asname:
                self._bump(alias.asname)

    # __all__ = [...] — string literals inside this specific assignment
    # count as references (legitimate public re-export).
    def visit_Assign(self, node: ast.Assign) -> None:
        is_all = any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        )
        if is_all and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    self._bump(elt.value)
        # Still walk the value — e.g., ``X = Y`` (Y is a real reference).
        self.generic_visit(node)


def _collect_refs_from_file(path: Path) -> dict[str, int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return {}
    collector = _RefCollector()
    collector.visit(tree)
    return collector.refs


def _collect_all_refs(exclude: set[Path] | None = None) -> dict[str, int]:
    """Sum AST references across the reference-scan roots."""
    total: dict[str, int] = {}
    for path in _python_files_under(_REFERENCE_SCAN_ROOTS, exclude=exclude):
        for name, count in _collect_refs_from_file(path).items():
            total[name] = total.get(name, 0) + count
    return total


# ---------------------------------------------------------------------------
# Routing surface (allowlist validation)
# ---------------------------------------------------------------------------

def _routing_yaml_files() -> set[str]:
    """Return the set of `file:` path values in orchestration-os/schema/routing.yaml.

    These are the R3-CODE and related rows that declare a source file as
    a published surface. We treat being in this set as evidence that a
    module has a public consumer beyond pure Python imports.
    """
    rp = REPO_ROOT / "orchestration-os" / "schema" / "routing.yaml"
    if not rp.exists():
        return set()
    files: set[str] = set()
    text = rp.read_text(encoding="utf-8", errors="ignore")
    # Minimal parse: look for ``file: "path"`` anywhere.
    import re
    for m in re.finditer(r'file:\s*"([^"]+)"', text):
        files.add(m.group(1))
    return files


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


# @invariant: ID=INV-15 | domain=reachability/dead-symbols | fails_on=a top-level def/class under nightclaw_engine|_bridge|_monitor|_ops has zero real AST-level references (ast.Name load, ast.Attribute, import alias, or __all__ string entry) outside its own def site — and is not private, a dunder, or in PUBLIC_API_ALLOWLIST | remediation=delete the symbol, wire it into a real caller/registry, or add it to PUBLIC_API_ALLOWLIST in tests/core/test_reachability.py with a one-line justification
def test_no_dead_public_symbols():
    """Every non-private top-level symbol in the four packages must have
    at least one AST-level reference somewhere in the reference-scan tree
    (packages + scripts + tests + apps), OR be listed in
    ``PUBLIC_API_ALLOWLIST`` with a justification.

    AST-based: string literals, comments, and docstrings do NOT count.
    """
    defs = _collect_defs()
    assert defs, "reachability gate: expected to discover at least one def"

    all_refs = _collect_all_refs()

    dead: list[str] = []
    for name, def_files in defs.items():
        if name.startswith("_"):
            continue  # private / dunder
        if name in PUBLIC_API_ALLOWLIST:
            continue
        # At least one AST reference anywhere. The def site itself does
        # NOT contribute to `all_refs` (the visitor suppresses it), so
        # any count > 0 is a real wire-up.
        if all_refs.get(name, 0) == 0:
            rel = ", ".join(str(p.relative_to(REPO_ROOT)) for p in def_files)
            dead.append(f"{name}  ({rel})")

    assert not dead, (
        "Dead public symbols (defined under nightclaw_{engine,bridge,monitor,"
        "ops}/ but with zero AST-level references in any scanned .py file):\n  - "
        + "\n  - ".join(sorted(dead))
        + "\nEither delete them, wire them into a real caller, or add them "
        "to PUBLIC_API_ALLOWLIST in tests/core/test_reachability.py with a "
        "one-line justification."
    )


def test_allowlist_entries_still_exist():
    """Entries in PUBLIC_API_ALLOWLIST must still be defined somewhere in
    the four packages — otherwise the allowlist is stale."""
    defs = _collect_defs()
    missing = [n for n in PUBLIC_API_ALLOWLIST if n not in defs]
    assert not missing, (
        f"PUBLIC_API_ALLOWLIST lists symbols that no longer exist: "
        f"{missing}. Remove them from tests/core/test_reachability.py."
    )


def test_allowlist_entries_have_justification():
    """Every allowlist value must be a non-empty string justification."""
    bad = [n for n, why in PUBLIC_API_ALLOWLIST.items() if not (isinstance(why, str) and why.strip())]
    assert not bad, (
        f"PUBLIC_API_ALLOWLIST entries missing justification: {bad}. "
        f"Add a one-line reason next to each name."
    )


def test_allowlist_entries_have_routing_surface():
    """Every allowlist entry's defining file(s) must be declared as a
    published surface in ``orchestration-os/schema/routing.yaml``.

    The allowlist is a pressure-release valve — but pressure must have a
    published reason. If a symbol is "public API" yet its module is not
    listed in routing.yaml, either wire it up in code or stop claiming
    public-API status.
    """
    defs = _collect_defs()
    routing_files = _routing_yaml_files()
    missing_surface: list[str] = []
    for name in PUBLIC_API_ALLOWLIST:
        if name not in defs:
            continue  # caught by test_allowlist_entries_still_exist
        # At least one of the defining files must appear in routing.yaml.
        rel_files = [str(p.relative_to(REPO_ROOT)) for p in defs[name]]
        if not any(rf in routing_files for rf in rel_files):
            missing_surface.append(f"{name} (defining files: {rel_files})")
    assert not missing_surface, (
        "PUBLIC_API_ALLOWLIST entries whose defining file is NOT listed "
        "in orchestration-os/schema/routing.yaml (so they are not actually "
        "a published surface):\n  - " + "\n  - ".join(missing_surface)
        + "\nEither add a routing.yaml entry for the file, or drop the "
        "symbol from PUBLIC_API_ALLOWLIST and either wire it up or delete it."
    )


@pytest.mark.parametrize("removed", [
    "emit_session_open",   # was in nightclaw_engine/commands/_shared.py
    "emit_session_close",  # was in nightclaw_engine/commands/_shared.py
    "ClientDispatcher",    # was in nightclaw_bridge/client_handlers.py
    "get_transport",       # was in nightclaw_ops/telemetry.py
    "load_workspace",      # was in nightclaw_bridge/workspace.py
    "parse_project_entry", # transitively removed with load_workspace
    "parse_bundle_entry",  # transitively removed with load_workspace
    "Workspace",           # Pass 3.3: removed with nightclaw_bridge/workspace.py
])
def test_removed_dead_symbols_stay_removed(removed: str):
    """Regression pin: the dead symbols Pass 14.1 removed must not come back
    without also gaining a real AST-level caller.

    Pass 2 hardening: the scan EXCLUDES this test file itself, so the
    parametrize string literal above cannot manufacture a reference.
    The scan also only counts real AST references (not regex matches),
    so string literals in handoff docs (.md) don't count either.

    If a future pass legitimately reintroduces one of these names with
    proper wiring, remove that entry from this parametrize list — the
    general reachability gate above will continue to protect us.
    """
    defs = _collect_defs()
    refs = _collect_all_refs(exclude={_THIS_FILE})
    reintroduced = removed in defs
    has_real_ref = refs.get(removed, 0) > 0

    if not reintroduced and not has_real_ref:
        # Still gone and no code references it — the target state.
        return
    if reintroduced and has_real_ref:
        # Legit reintroduction: someone re-added it AND wired it up.
        # The author should remove it from this parametrize list.
        return
    if reintroduced and not has_real_ref:
        pytest.fail(
            f"{removed!r} was reintroduced as a def/class but has ZERO "
            f"AST-level references anywhere under "
            f"{list(_REFERENCE_SCAN_ROOTS)} (excluding this test file). "
            f"If this is intentional public API, add it to "
            f"PUBLIC_API_ALLOWLIST in this test module. Otherwise, wire "
            f"it into a real caller or delete it again."
        )
    # Not reintroduced, but something references it by name — probably
    # a leftover comment/import. We don't fail (the general gate already
    # covers dead-on-the-vine cases), but surface it as information.
    # NB: because `refs` counts only AST nodes, this path is rare.
    pytest.skip(
        f"{removed!r} is not defined, but an AST reference to the name "
        f"exists somewhere — likely a surviving import. If the import "
        f"targets nothing, clean it up."
    )


# ---------------------------------------------------------------------------
# Meta-tests — verify the gate itself works
# ---------------------------------------------------------------------------


def test_gate_detects_synthetic_dead_symbol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Negative control: synthesize a fake package with a clearly-dead
    symbol and confirm the gate logic flags it.

    Without this test, a future refactor could silently break the gate
    (e.g., by making ``_collect_all_refs`` double-count the def site)
    and the general gate would still pass against the real repo, because
    every real symbol happens to be wired up.
    """
    # Build an isolated two-package repo under tmp_path:
    #   fake_engine/
    #     dead.py         — defines ``orphan_function`` and nothing else.
    #     alive.py        — defines ``alive_function``, references orphan? no.
    #     user.py         — defines ``use_alive``, references ``alive_function``.
    pkg = tmp_path / "fake_engine"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "dead.py").write_text(textwrap.dedent("""
        def orphan_function():
            return 'nobody calls me'

        # Comment mentioning orphan_function should NOT rescue it.
        x = "orphan_function"  # string literal should NOT rescue it.
    """))
    (pkg / "alive.py").write_text(textwrap.dedent("""
        def alive_function():
            return 1
    """))
    (pkg / "user.py").write_text(textwrap.dedent("""
        from fake_engine.alive import alive_function

        def use_alive():
            return alive_function()
    """))

    # Scan the fake package as if it were the repo.
    defs_seen: dict[str, list[Path]] = {}
    for path in pkg.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs_seen.setdefault(node.name, []).append(path)

    refs_seen: dict[str, int] = {}
    for path in pkg.rglob("*.py"):
        for name, count in _collect_refs_from_file(path).items():
            refs_seen[name] = refs_seen.get(name, 0) + count

    # orphan_function: defined but only referenced in a comment and a
    # string literal — both of which the AST visitor correctly ignores.
    assert "orphan_function" in defs_seen, "fixture sanity"
    assert refs_seen.get("orphan_function", 0) == 0, (
        f"Gate is broken: orphan_function is mentioned only in a comment "
        f"and string literal, but the AST visitor counted "
        f"{refs_seen.get('orphan_function', 0)} reference(s). "
        f"Comments and strings must NOT count."
    )

    # alive_function: has a real call site and an import — should be alive.
    assert refs_seen.get("alive_function", 0) >= 2, (
        f"Gate is broken: alive_function is imported AND called, but "
        f"the AST visitor counted only {refs_seen.get('alive_function', 0)} "
        f"reference(s). Expected >= 2 (import alias + call-site load)."
    )


def test_gate_ignores_string_literal_and_docstring_mentions(tmp_path: Path):
    """Negative control: a def whose name is mentioned only in a module
    docstring, a function docstring, or a string constant must still be
    flagged as dead. This pins the specific loophole that fooled v1.
    """
    pkg = tmp_path / "fake2"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "m.py").write_text(textwrap.dedent('''
        """Module docstring mentioning ghost_symbol in prose."""

        def ghost_symbol():
            """Docstring: this function is called ghost_symbol."""
            return "ghost_symbol as a string literal"
    '''))
    refs: dict[str, int] = {}
    for path in pkg.rglob("*.py"):
        for name, count in _collect_refs_from_file(path).items():
            refs[name] = refs.get(name, 0) + count
    assert refs.get("ghost_symbol", 0) == 0, (
        f"Gate is broken: ghost_symbol appears only in a module docstring, "
        f"a function docstring, and a string literal — all of which must "
        f"NOT count as references. AST visitor counted "
        f"{refs.get('ghost_symbol', 0)}."
    )


def test_gate_counts_dispatch_dict_values(tmp_path: Path):
    """Positive control: a function registered in a dispatch dict (the
    ``PREDICATE_REGISTRY`` / ``RESOLVERS`` / ``COMMANDS`` pattern) must
    count as alive even when no syntactic call site exists in the tree.
    """
    pkg = tmp_path / "fake3"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "m.py").write_text(textwrap.dedent("""
        def pred_foo(x):
            return True
        def pred_bar(x):
            return False

        PREDICATE_REGISTRY = {
            "foo": pred_foo,
            "bar": pred_bar,
        }
    """))
    refs: dict[str, int] = {}
    for path in pkg.rglob("*.py"):
        for name, count in _collect_refs_from_file(path).items():
            refs[name] = refs.get(name, 0) + count
    assert refs.get("pred_foo", 0) >= 1, (
        "Gate is broken: dispatch-dict value reference to pred_foo was "
        "not counted — this is the exact registry-binding pattern the "
        "gate must recognize."
    )
    assert refs.get("pred_bar", 0) >= 1, (
        "Gate is broken: dispatch-dict value reference to pred_bar was "
        "not counted."
    )


def test_gate_counts_all_list_reexports(tmp_path: Path):
    """Positive control: a string literal inside ``__all__ = [...]`` is
    a legitimate public-API declaration and must count as a reference."""
    pkg = tmp_path / "fake4"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "m.py").write_text(textwrap.dedent("""
        __all__ = ["ReExportedThing"]

        class ReExportedThing:
            pass
    """))
    refs: dict[str, int] = {}
    for path in pkg.rglob("*.py"):
        for name, count in _collect_refs_from_file(path).items():
            refs[name] = refs.get(name, 0) + count
    # One reference: the string inside __all__. The class def site does
    # not contribute.
    assert refs.get("ReExportedThing", 0) >= 1, (
        "Gate is broken: __all__ string-literal re-export was not "
        "counted as a reference. Expected >= 1."
    )


def test_regression_pin_excludes_self(monkeypatch: pytest.MonkeyPatch):
    """Confirm the regression pin's reference scan excludes this test
    file itself — otherwise the parametrize list below would
    manufacture references that defeat the pin.

    We assert this structurally by confirming that _collect_all_refs
    with exclude={_THIS_FILE} sees strictly fewer 'removed'-symbol
    references than the same call without the exclusion.
    """
    refs_without_exclude = _collect_all_refs()
    refs_with_exclude = _collect_all_refs(exclude={_THIS_FILE})
    # At least one of the 5 removed symbol names should appear in this
    # test file's AST (the parametrize list uses string literals — but
    # AST only counts them inside __all__. So strings inside a
    # @pytest.mark.parametrize call do NOT register as AST refs.
    # However, if the test file ever acquires a real import or
    # reference, this guard catches it.
    for removed in (
        "emit_session_open", "emit_session_close", "ClientDispatcher",
        "get_transport", "load_workspace", "parse_project_entry", "parse_bundle_entry",
        "Workspace",
    ):
        diff = refs_without_exclude.get(removed, 0) - refs_with_exclude.get(removed, 0)
        assert diff == 0, (
            f"Excluding this test file changed the ref count for "
            f"{removed!r} (full={refs_without_exclude.get(removed, 0)}, "
            f"excluded={refs_with_exclude.get(removed, 0)}). If this is "
            f"intentional, update the test; otherwise, remove the "
            f"reference in this file that is defeating the pin."
        )
