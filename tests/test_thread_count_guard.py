"""Tests look only at the threads their code names (``_threads.live_threads``).

Counting every thread in the process (``threading.active_count()``,
``threading.enumerate()``) picks up threads other tests left behind, which
exit whenever they idle out: a fresh-stack test failed with ``assert 6 == 7``
when a blocking-pool worker ended during it."""

import ast

import _source
from _source import TESTS

_BANNED = frozenset({"active_count", "activeCount", "enumerate"})
_MAY_LIST_EVERY_THREAD = frozenset({"_threads.py", "_thread_cpu_timer.py"})
"""``_threads.live_threads`` itself, and the stack dumps, which signal every thread to write
its own stack (a report of each, never a count) and load where ``_threads`` cannot be
imported (a fork's ``sys.path`` stays what ``python -P`` gives)."""


def _counts_all_threads(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return (
            node.attr in _BANNED
            and isinstance(node.value, ast.Name)
            and node.value.id == "threading"
        )
    if isinstance(node, ast.ImportFrom):
        return node.module == "threading" and any(alias.name in _BANNED for alias in node.names)
    return False


def test_tests_find_threads_only_through_live_threads():
    offenders = [
        f"{path.relative_to(TESTS)}:{getattr(node, 'lineno', 0)}"
        for path in _source.files(TESTS)
        if path.name not in _MAY_LIST_EVERY_THREAD and _source.mentions(path, *_BANNED)
        for node in _source.walk(path)
        if _counts_all_threads(node)
    ]
    assert offenders == [], "use _threads.live_threads(name_prefix)"
