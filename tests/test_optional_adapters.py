"""The pydantic and msgspec adapters stay optional: only their own modules
import the libraries, and importing pyfect loads neither."""

import ast
import subprocess
import sys
from pathlib import Path

_SOURCE = Path(__file__).parent.parent / "src" / "pyfect"
_OWNERS = {"pydantic": "pydantic.py", "pydantic_core": "pydantic.py", "msgspec": "msgspec.py"}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_only_the_adapter_modules_import_their_library():
    offenders = [
        (str(path.relative_to(_SOURCE)), library)
        for path in _SOURCE.rglob("*.py")
        for library in _imported_roots(path) & _OWNERS.keys()
        if path.relative_to(_SOURCE) != Path(_OWNERS[library])
    ]
    assert offenders == []


def test_importing_pyfect_loads_neither_library():
    loaded = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys, pyfect, pyfect.schema; "
            "print(sorted(m for m in ('pydantic', 'msgspec') if m in sys.modules))",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert loaded == "[]"
