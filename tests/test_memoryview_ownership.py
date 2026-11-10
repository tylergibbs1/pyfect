"""A ``memoryview`` belongs to the thread that made it.

Free-threaded CPython 3.14 counts a buffer's views without a lock, so a
view made on one thread and freed on another while a third view of the same
buffer is made can release the buffer under its remaining views ("operation
forbidden on released memoryview object"). A child process's stdin writer
kept a view made on the fiber's thread in the write request and sliced it on
its own thread; about one 24 MB write in twenty hung on 3.14t (dogfood
m020). So every view in ``src`` is made in a ``with`` statement: the block's
thread owns it and releases it, and it never lives on an object another
thread can reach."""

import ast
from pathlib import Path

_SOURCE = Path(__file__).parent.parent / "src" / "pyfect"


def _offenders(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), str(path))
        owned = {
            id(item.context_expr)
            for node in ast.walk(tree)
            if isinstance(node, ast.With | ast.AsyncWith)
            for item in node.items
        }
        found.extend(
            f"{path.relative_to(root)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "memoryview"
            and id(node) not in owned
        )
    return found


def test_every_memoryview_is_made_in_a_with_statement():
    assert _offenders(_SOURCE) == []


def test_the_check_sees_a_view_kept_on_an_object(tmp_path: Path):
    (tmp_path / "kept.py").write_text(
        "class Write:\n"
        "    def __init__(self, data):\n"
        "        self.view = memoryview(data)\n"
        "def owned(data):\n"
        "    with memoryview(data) as view:\n"
        "        return bytes(view[1:])\n"
    )
    assert _offenders(tmp_path) == ["kept.py:3"]
