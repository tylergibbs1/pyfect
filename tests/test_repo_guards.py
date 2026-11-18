"""Every test that scans the repository is in ``tests/_repo_guards.txt``, which the pre-push
hook runs (``lefthook.yml``, ``scripts/repo_scans.py``): all of it but the slow tests at its
end, each with the reason it runs only in CI.

A test that scans ``src/`` or ``tests/`` can fail on a change to any file, not only on one
near the code it tests, so running the suites a change touched misses it: a docstring the
whitespace guard flags, a renamed test still named in ``_longer_timeouts.txt``. The hook
runs these tests before every push, so the list must hold each of them.

A test scans the repository when it reaches, through the module's functions and constants
or a ``tests/_*.py`` helper's, a listing of a tree (``_source.files``, ``rglob``,
``os.walk``, ``git ls-files``) or of pyfect's modules (``pkgutil.walk_packages``,
``iter_modules``). Every test of a ``*guard*`` module counts too. The list may hold more:
tests whose checks span the repository without listing it (``tests/test_changelog.py``).
"""

from __future__ import annotations

import ast
import functools
import importlib.util
from collections.abc import Sequence
from pathlib import Path

import _source
from _source import TESTS

_spec = importlib.util.spec_from_file_location(
    "repo_scans", TESTS.parent / "scripts" / "repo_scans.py"
)
assert _spec is not None and _spec.loader is not None
repo_scans = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repo_scans)
LISTED: Path = repo_scans.LIST

_LISTINGS = frozenset({"rglob", "walk_packages", "iter_modules"})
_Function = ast.FunctionDef | ast.AsyncFunctionDef


def _lists_the_repository(call: ast.Call, source_files: frozenset[str]) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in source_files
    if not isinstance(func, ast.Attribute):
        return False
    owner = func.value.id if isinstance(func.value, ast.Name) else None
    return (
        func.attr in _LISTINGS
        or (func.attr, owner) in {("files", "_source"), ("walk", "os")}
        or any(
            isinstance(node, ast.Constant) and node.value == "ls-files"
            for arg in call.args
            for node in ast.walk(arg)
        )
    )


def _names(nodes: Sequence[ast.AST]) -> set[str]:
    return {n.id for node in nodes for n in ast.walk(node) if isinstance(n, ast.Name)}


def _imports(tree: ast.Module) -> tuple[frozenset[str], set[str]]:
    """The local names of ``_source.files``, and of ``tests/_*.py`` helpers' names that
    reach a listing of the repository."""
    source_files: set[str] = set()
    scanning: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level or node.module is None:
            continue
        helper = TESTS / f"{node.module}.py"
        for alias in node.names:
            local = alias.asname or alias.name
            if node.module == "_source" and alias.name == "files":
                source_files.add(local)
            elif (
                node.module.startswith("_") and helper.exists() and alias.name in _scanning(helper)
            ):
                scanning.add(local)
    return frozenset(source_files), scanning


def _definitions(tree: ast.Module) -> list[tuple[str, Sequence[ast.AST]]]:
    """Each module-level name (methods as ``Class::name``) with the code that defines it.
    A function's decorators are left out: a test parametrized over the files checks each
    file on its own, so it fails only for the file a change touched. Code run at import
    other than a definition is ``<module>``, which every test depends on."""
    found: list[tuple[str, Sequence[ast.AST]]] = []
    for node in tree.body:
        if isinstance(node, _Function):
            found.append((node.name, [*node.body, *node.args.defaults]))
        elif isinstance(node, ast.ClassDef):
            found += [
                (f"{node.name}::{item.name}", item.body)
                for item in node.body
                if isinstance(item, _Function)
            ]
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            found += [(name, [node]) for name in _names(targets)]
        elif not isinstance(node, ast.Import | ast.ImportFrom):
            found.append(("<module>", [node]))
    return found


def _fixtures(tree: ast.Module) -> dict[str, set[str]]:
    """The parameters of each function and method: the fixtures it asks for."""
    found: dict[str, set[str]] = {}
    for node in tree.body:
        methods = node.body if isinstance(node, ast.ClassDef) else [node]
        prefix = f"{node.name}::" if isinstance(node, ast.ClassDef) else ""
        for item in methods:
            if isinstance(item, _Function):
                found[prefix + item.name] = {a.arg for a in item.args.args}
    return found


@functools.cache
def _scanning(path: Path) -> frozenset[str]:
    """The module-level names of ``path`` (methods as ``Class::name``) that reach a listing
    of the repository."""
    tree = _source.tree(path)
    source_files, reach = _imports(tree)
    fixtures = _fixtures(tree)
    uses: dict[str, set[str]] = {}
    for name, code in _definitions(tree):
        uses.setdefault(name, set()).update(_names(code), fixtures.get(name, ()))
        if any(
            isinstance(n, ast.Call) and _lists_the_repository(n, source_files)
            for node in code
            for n in ast.walk(node)
        ):
            reach.add(name)
    while more := {
        name
        for name, used in uses.items()
        if name not in reach and ("<module>" in reach or used & reach)
    }:
        reach |= more
    return frozenset(reach)


def _tests(path: Path) -> list[str]:
    """The ids of the test functions in ``path``, as pytest names them without parameters."""
    found: list[str] = []
    for node in _source.tree(path).body:
        if isinstance(node, _Function) and node.name.startswith("test"):
            found.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            found += [
                f"{node.name}::{item.name}"
                for item in node.body
                if isinstance(item, _Function) and item.name.startswith("test")
            ]
    return found


def _test_files() -> tuple[Path, ...]:
    return _source.files(TESTS, "test_*.py")


def _id(path: Path, test: str) -> str:
    return f"{path.relative_to(TESTS.parent).as_posix()}::{test}"


def scanning_tests() -> set[str]:
    found: set[str] = set()
    for path in _test_files():
        guard = "guard" in path.name
        reach = frozenset[str]() if guard else _scanning(path)
        found |= {_id(path, t) for t in _tests(path) if guard or t in reach}
    return found


def _entries() -> list[tuple[str, str | None]]:
    return repo_scans.entries(LISTED.read_text())


def test_every_test_that_scans_the_repository_is_listed() -> None:
    missing = sorted(scanning_tests() - {test for test, _ in _entries()})
    assert not missing, f"add to {LISTED.name} (the pre-push hook runs them):\n" + "\n".join(
        missing
    )


def test_every_listed_test_exists_once() -> None:
    tests = [test for test, _ in _entries()]
    known = {_id(path, t) for path in _test_files() for t in _tests(path)}
    assert not sorted(set(tests) - known), f"stale in {LISTED.name}"
    assert len(tests) == len(set(tests)), f"listed twice in {LISTED.name}"


def test_the_ci_only_tests_come_last_and_each_part_is_sorted() -> None:
    pushed = [test for test, reason in _entries() if reason is None]
    ci_only = [test for test, reason in _entries() if reason is not None]
    assert [test for test, _ in _entries()] == pushed + ci_only
    assert pushed == sorted(pushed)
    assert ci_only == sorted(ci_only)


def test_the_list_reads_tests_reasons_and_comments() -> None:
    assert repo_scans.entries(
        "# a comment\n\ntests/a.py::test_a\ntests/b.py::test_b  # 9 s: imports every module\n"
    ) == [("tests/a.py::test_a", None), ("tests/b.py::test_b", "9 s: imports every module")]


def test_a_scan_is_found_through_constants_helpers_and_fixtures(tmp_path: Path) -> None:
    def scans(source: str) -> list[str]:
        path = tmp_path / f"test_example_{len(list(tmp_path.iterdir()))}.py"
        path.write_text(source)
        _scanning.cache_clear()
        return [t for t in _tests(path) if t in _scanning(path)]

    assert scans(
        "import _source\n"
        "FILES = _source.files(_source.SRC)\n"
        "def _texts():\n    return [p.read_text() for p in FILES]\n"
        "def test_direct():\n    _source.files(_source.TESTS)\n"
        "def test_constant():\n    _texts()\n"
        "def test_other():\n    pass\n"
    ) == ["test_direct", "test_constant"]
    assert scans(
        "import pytest, subprocess\n"
        "@pytest.fixture\ndef tracked():\n    return subprocess.run(['git', 'ls-files'])\n"
        "def test_fixture(tracked):\n    pass\n"
        "class TestOne:\n    def test_method(self, tracked):\n        pass\n"
    ) == ["test_fixture", "TestOne::test_method"]
    assert scans(
        "from _pyfect_modules import module_names\n"
        "def test_helper():\n    module_names()\n"
        "def test_unrelated():\n    pass\n"
    ) == ["test_helper"]
    assert (
        scans(
            "import _source, pytest\n"
            "@pytest.mark.parametrize('path', _source.files(_source.SRC))\n"
            "def test_each_file(path):\n    pass\n"
        )
        == []
    )
