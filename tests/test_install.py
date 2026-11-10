"""What a user gets from ``uv add pyfect-dev``: the base install
imports every module that does not belong to an extra, loads the pytest
plugin, and a module behind an extra fails with an ``ImportError`` naming
the extra and the command that installs it.

The source checks keep it that way: every import of an extra's library is
guarded by ``pyfect._extras.missing_extra`` (or sits in a module whose
package is), and no document names the bare distribution ``pyfect``,
which on PyPI is an unrelated project."""

from __future__ import annotations

import ast
import importlib.abc
import importlib.machinery
import json
import re
import shutil
import subprocess
import sys
import tomllib
import types
import typing
from pathlib import Path

import pytest

from pyfect._extras import DISTRIBUTION, LIBRARIES, Extra, install_command

_ROOT = Path(__file__).parent.parent
_SOURCE = _ROOT / "src" / "pyfect"

_LIBRARIES: dict[str, frozenset[Extra]] = {
    library: frozenset(extra for extra, names in LIBRARIES.items() if library in names)
    for library in set[str]().union(*LIBRARIES.values())
}
"""The extras that install each library; an import is guarded by any of them."""


def _pyproject() -> dict[str, typing.Any]:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text())


def _module_name(path: Path) -> str:
    parts = path.relative_to(_SOURCE.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _sources() -> list[Path]:
    return sorted(path for path in _SOURCE.rglob("*.py") if "__pycache__" not in path.parts)


def _gate_extra(handler: ast.ExceptHandler) -> Extra | None:
    """The extra a ``raise missing_extra(feature, extra, error) from error``
    in ``handler`` names, if it catches ``ImportError`` as ``error``: the
    gate needs the caught error to tell an absent library from a broken one."""
    if not (isinstance(handler.type, ast.Name) and handler.type.id == "ImportError"):
        return None
    for node in (node for statement in handler.body for node in ast.walk(statement)):
        match node:
            case ast.Raise(
                exc=ast.Call(
                    func=ast.Name(id="missing_extra"),
                    args=[_, ast.Constant(value=str() as extra), ast.Name(id=passed)],
                ),
                cause=ast.Name(id=cause),
            ) if passed == cause == handler.name:
                return typing.cast(Extra, extra)
            case _:
                pass
    return None


def _module_gates(tree: ast.Module) -> set[Extra]:
    return {
        extra
        for node in tree.body
        if isinstance(node, ast.Try)
        for handler in node.handlers
        if (extra := _gate_extra(handler)) is not None
    }


def _gated_modules() -> dict[str, Extra]:
    """Modules whose own top level checks for an extra (a package's checks
    cover its submodules)."""
    gated: dict[str, Extra] = {}
    for path in _sources():
        gates = _module_gates(ast.parse(path.read_text()))
        assert len(gates) <= 1, f"{path} checks for several extras: {gates}"
        if gates:
            gated[_module_name(path)] = gates.pop()
    return gated


def _extra_of(module: str, gated: dict[str, Extra]) -> Extra | None:
    parts = module.split(".")
    for end in range(len(parts), 0, -1):
        if (extra := gated.get(".".join(parts[:end]))) is not None:
            return extra
    return None


def _unguarded_imports(path: Path, gated: dict[str, Extra]) -> list[str]:
    tree = ast.parse(path.read_text())
    covered = _extra_of(_module_name(path), gated)
    offenders: list[str] = []

    def visit(node: ast.AST, guards: frozenset[str], type_checking: bool) -> None:
        match node:
            case ast.If(test=ast.Name(id="TYPE_CHECKING")):
                for child in node.body:
                    visit(child, guards, True)
                for child in node.orelse:
                    visit(child, guards, type_checking)
                return
            case ast.Try():
                inner = guards | {
                    extra for handler in node.handlers if (extra := _gate_extra(handler))
                }
                for child in node.body:
                    visit(child, inner, type_checking)
                for child in [*node.handlers, *node.orelse, *node.finalbody]:
                    visit(child, guards, type_checking)
                return
            case ast.Import(names=names):
                roots = [alias.name.split(".")[0] for alias in names]
            case ast.ImportFrom(module=str() as module, level=0):
                roots = [module.split(".")[0]]
            case _:
                roots = []
        for root in roots:
            extras = _LIBRARIES.get(root, frozenset[Extra]())
            if extras and not type_checking and not extras & (guards | {covered}):
                offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno} imports {root}")  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        for child in ast.iter_child_nodes(node):
            visit(child, guards, type_checking)

    visit(tree, frozenset(), False)
    return offenders


def test_the_extras_are_the_ones_pyproject_declares():
    declared = set(_pyproject()["project"]["optional-dependencies"])
    assert set(typing.get_args(Extra.__value__)) == declared
    assert set[Extra]().union(*_LIBRARIES.values()) <= declared


def test_the_distribution_is_pyfect_dev_and_imports_as_pyfect():
    project = _pyproject()
    assert project["project"]["name"] == DISTRIBUTION == "pyfect-dev"
    assert project["tool"]["uv"]["build-backend"]["module-name"] == "pyfect"
    assert project["project"]["entry-points"]["pytest11"] == {"pyfect": "pyfect.testing.plugin"}


def test_every_import_of_an_extra_library_is_guarded_by_missing_extra():
    gated = _gated_modules()
    offenders = [line for path in _sources() for line in _unguarded_imports(path, gated)]
    assert offenders == []


_DOCUMENTS = [
    _ROOT / "README.md",
    _ROOT / "CONTRIBUTING.md",
    *(_ROOT / "docs").glob("*.md"),
    *(_ROOT / "website" / "content").rglob("*.mdx"),
    *(
        path
        for folder in ("app", "components", "lib")
        for pattern in ("*.ts", "*.tsx")
        for path in (_ROOT / "website" / folder).rglob(pattern)
    ),
    *(_ROOT / "website" / "snippets").rglob("*.py"),
    *(_ROOT / "examples").rglob("*.py"),
    *(_ROOT / "tests").rglob("*.py"),
    *_sources(),
]
# PARITY.md is the milestone log; it records what was done under the old name.
# This file spells the banned patterns out.
_HISTORY = {_ROOT / "docs" / "PARITY.md", Path(__file__)}
_BARE_NAME = re.compile(
    r"(?:pip install|uv add|uv pip install|poetry add)\s+['\"]?pyfect(?![\w-])"
    r"|(?<![\w./-])pyfect\["
    r"|(?:version|distribution|metadata)\(\s*['\"]pyfect['\"]"
)


def test_no_document_or_lookup_names_the_bare_pyfect_distribution():
    offenders = [
        f"{path.relative_to(_ROOT)}:{number}: {line.strip()}"
        for path in _DOCUMENTS
        if path not in _HISTORY
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _BARE_NAME.search(line)
    ]
    assert offenders == []


def test_the_install_command_names_the_pypi_distribution():
    assert install_command() == "uv add pyfect-dev"
    assert install_command("otel") == 'uv add "pyfect-dev[otel]"'


def test_no_document_installs_from_git():
    # pyfect-dev is on PyPI: a git install line in the docs would install an
    # unreleased main instead of the release.
    offenders = [
        f"{path.relative_to(_ROOT)}:{number}: {line.strip()}"
        for path in _DOCUMENTS
        if path not in _HISTORY
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "git+https://github.com/tylergibbs1/pyfect" in line
    ]
    assert offenders == []


# pytest is not a dependency: only the plugin (loaded by pytest itself) may
# import it at import time, so the run below hides it.
_NEEDS_PYTEST = {"pyfect.testing.plugin"}

_IMPORT_EVERY_MODULE = """
import importlib, importlib.abc, json, sys

class HidePytest(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("pytest", "_pytest"):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None

sys.meta_path.insert(0, HidePytest())
expected = json.loads(sys.argv[1])
problems = []
for module, extra in expected.items():
    try:
        importlib.import_module(module)
    except ImportError as error:
        hint = f'uv add "pyfect-dev[{extra}]"'
        if extra is None or hint not in str(error):
            problems.append(f"{module}: {type(error).__name__}: {error}")
    else:
        if extra is not None:
            problems.append(f"{module} imported without the {extra} extra")
print(json.dumps(problems))
"""

_PLUGIN_TEST = """
import pyfect as fx

@fx.testing.effect
def test_runs():
    value = yield from fx.succeed(1)
    assert value == 1
"""


def _uv(*args: str) -> None:
    offline = subprocess.run(
        ["uv", *args, "--offline", "-q"], capture_output=True, text=True, check=False
    )
    if offline.returncode != 0:
        subprocess.run(["uv", *args, "-q"], check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def base_install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The interpreter of a new venv with pyfect-dev (no extras) and pytest."""
    if shutil.which("uv") is None:
        pytest.fail("the install tests need uv on PATH")
    venv = tmp_path_factory.mktemp("base") / "venv"
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    subprocess.run(["uv", "venv", "-q", "--python", version, str(venv)], check=True)
    python = venv / "bin" / "python"
    _uv("pip", "install", "--python", str(python), str(_ROOT), "pytest")
    return python


def test_a_base_install_imports_every_module_outside_an_extra(base_install: Path):
    gated = _gated_modules()
    expected = {
        _module_name(path): _extra_of(_module_name(path), gated)
        for path in _sources()
        if not path.name.startswith("__main__") and _module_name(path) not in _NEEDS_PYTEST
    }
    assert {"pyfect.otel", "pyfect.sql.pg", "pyfect.socket.ws"} <= set(gated)
    run = subprocess.run(
        [str(base_install), "-I", "-c", _IMPORT_EVERY_MODULE, json.dumps(expected)],
        capture_output=True,
        text=True,
        cwd=base_install.parent,
        check=True,
    )
    assert json.loads(run.stdout.splitlines()[-1]) == []


def test_a_base_install_loads_the_pytest_plugin(base_install: Path, tmp_path: Path):
    (tmp_path / "test_plugin.py").write_text(_PLUGIN_TEST)
    run = subprocess.run(
        [str(base_install), "-m", "pytest", "-q", "--strict-markers", "-m", "pyfect_effect"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "1 passed" in run.stdout


def test_a_base_install_builds_the_httpx_layer_only_to_fail_naming_the_extra(
    base_install: Path,
):
    program = (
        "import pyfect as fx\n"
        "from pyfect.http import httpx_client\n"
        "exit = fx.run_blocking_exit(fx.scoped(fx.void.pipe(fx.provide(httpx_client.layer))))\n"
        "print(exit)\n"
    )
    run = subprocess.run(
        [str(base_install), "-I", "-c", program], capture_output=True, text=True, check=True
    )
    assert install_command("httpx") in run.stdout


_BREAK_LIBRARIES = """
import importlib, importlib.abc, importlib.machinery, json, sys

module, libraries, absent = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3] == "absent"

class Broken(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise ImportError(f"{module.__name__} is broken: libpq library not found")

class Installed(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name in libraries:
            return importlib.machinery.ModuleSpec(name, Broken())
        return None

for name in list(sys.modules):
    if name.split(".")[0] in libraries:
        del sys.modules[name]
class Uninstalled(importlib.abc.MetaPathFinder):
    def __init__(self, finder):
        self.finder = finder

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in libraries:
            return None
        return self.finder.find_spec(name, path, target)

if absent:
    sys.meta_path[:] = [Uninstalled(finder) for finder in sys.meta_path]
else:
    sys.meta_path.insert(0, Installed())
try:
    importlib.import_module(module)
except ImportError as error:
    print(json.dumps(str(error)))
else:
    print(json.dumps(None))
"""


@pytest.mark.parametrize("absent", [True, False], ids=["absent", "broken"])
@pytest.mark.parametrize("module", sorted(_gated_modules()))
def test_a_gate_names_the_extra_only_when_its_library_is_absent(module: str, absent: bool):
    # On a slim image psycopg is installed but libpq is not: the gate must
    # show that error, not tell the user to install the extra they have.
    extra = _gated_modules()[module]
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _BREAK_LIBRARIES,
            module,
            json.dumps(sorted(LIBRARIES[extra])),
            "absent" if absent else "broken",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    message = json.loads(run.stdout.splitlines()[-1])
    assert message is not None, f"{module} imported without its libraries"
    if absent:
        assert install_command(extra) in message
    else:
        assert install_command(extra) not in message
        assert "libpq library not found" in message


class _BrokenLoader(importlib.abc.Loader):
    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        raise ImportError(f"{module.__name__} is broken: a shared library is missing")


class _BrokenFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> importlib.machinery.ModuleSpec | None:
        return (
            importlib.machinery.ModuleSpec(fullname, _BrokenLoader())
            if fullname == "regex"
            else None
        )


def test_a_property_escape_shows_why_an_installed_regex_failed(monkeypatch: pytest.MonkeyPatch):
    # The ``regex`` extra is optional: absent, the pattern is refused; installed
    # but broken, the import error is shown instead of the refusal.
    from pyfect.schema._ecma_pattern import EcmaPatternError, compile_ecma

    compile_ecma.cache_clear()
    monkeypatch.setitem(sys.modules, "regex", None)
    with pytest.raises(EcmaPatternError):
        compile_ecma(r"\p{Lu}")
    compile_ecma.cache_clear()
    monkeypatch.delitem(sys.modules, "regex")
    monkeypatch.setattr(sys, "meta_path", [_BrokenFinder(), *sys.meta_path])
    with pytest.raises(ImportError, match="a shared library is missing"):
        compile_ecma(r"\p{Lu}")
    compile_ecma.cache_clear()
