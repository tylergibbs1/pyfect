"""No ``asyncio.shield`` in src. Some releases (3.14.7 among them) report the
shielded future's later failure to the loop's exception handler after the
waiter is cancelled, even when the failure is retrieved. Code that waits for
a future that must outlive a cancelled waiter uses
``pyfect._futures.await_uncancelled``, which waits through ``asyncio.wait``."""

import ast
from pathlib import Path

import _source


def _shields(path: Path) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(_source.tree(path)):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "shield"
            and isinstance(node.value, ast.Name)
            and node.value.id == "asyncio"
        ):
            hits.append(f"{path.relative_to(_source.SRC)}:{node.lineno}")
        if isinstance(node, ast.ImportFrom) and node.module == "asyncio":
            hits += [
                f"{path.relative_to(_source.SRC)}:{node.lineno}"
                for alias in node.names
                if alias.name == "shield"
            ]
    return hits


def test_src_never_uses_asyncio_shield():
    assert [hit for path in _source.files(_source.SRC) for hit in _shields(path)] == []
