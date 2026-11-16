"""``ManagedRuntime``'s shared state is read and written only under its lock.

Runs and disposals come from many threads at once. Without the lock two
``dispose()`` calls both saw no disposal and both began one (the second
returned before the release), and a run read the services, then a disposal
closed the fiber scope before the run joined it, so nothing awaited the run
(and a second read of ``_cached`` could see ``None``). Every access to the
state below must sit inside ``with self._lock:``, or in a method whose
docstring says it is "Called under ``_lock``", itself only called there.
"""

from __future__ import annotations

import ast

import _source

SOURCE = _source.SRC / "managed_runtime.py"
_GUARDED = {"_disposed", "_cached", "_context_effect", "_build_fiber"}
_MARK = "Called under ``_lock``"


def _self_attr(node: ast.AST) -> str | None:
    """``name`` for ``self.name``, else ``None``."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.attr if node.value.id == "self" else None
    return None


def _marked(func: ast.FunctionDef) -> bool:
    return _MARK in " ".join((ast.get_docstring(func) or "").split())


def _unlocked_uses(tree: ast.AST) -> list[str]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    under_lock = {f.name for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and _marked(f)}

    def locked(node: ast.AST) -> bool:
        current = parents.get(node)
        while current is not None:
            if isinstance(current, ast.With) and any(
                _self_attr(item.context_expr) == "_lock" for item in current.items
            ):
                return True
            if isinstance(current, ast.FunctionDef):
                return current.name == "__init__" or current.name in under_lock
            current = parents.get(current)
        return False

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        name = _self_attr(node)
        if name in _GUARDED:
            what = name
        elif isinstance(node, ast.Attribute) and node.attr == "_watch":
            what = "_watch"  # joining the fiber scope is decided with the state
        elif isinstance(node, ast.Call) and _self_attr(node.func) in under_lock:
            what = _self_attr(node.func)
        else:
            continue
        if not locked(node):
            found.append((getattr(node, "lineno", 0), str(what)))
    return [f"line {line}: {what}" for line, what in sorted(found)]


def test_the_runtime_state_is_only_used_under_the_lock() -> None:
    assert _unlocked_uses(_source.tree(SOURCE)) == []


def test_the_check_finds_an_unlocked_use() -> None:
    code = '''
class R:
    def __init__(self):
        self._cached = None

    def ok(self):
        with self._lock:
            return self._provided()

    def _provided(self):
        """Called under ``_lock``."""
        return self._cached

    def racy(self):
        if self._disposed is None:
            self._fiber_scope._watch(f)
        return self._provided()
'''
    assert _unlocked_uses(_source.parse(code)) == [
        "line 15: _disposed",
        "line 16: _watch",
        "line 17: _provided",
    ]
