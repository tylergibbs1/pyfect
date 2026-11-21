"""A dump of every thread's stack reads frames other threads may be changing, with no lock:
faulthandler's all-threads dump segfaulted CPython whenever another thread ran Python
meanwhile. ``faulthandler.register(sig, all_threads=True)`` under a recurring timer did (the
stall watchdog's SIGPROF samples, an xdist worker lost on Python 3.13), and so did
``faulthandler.dump_traceback_later``, whose C thread dumps every thread at its deadline: at
the end of a SIGSTOP, every thread starts again just then (#279's CI, an inner run dead with
SIGSEGV and nothing on stderr, as that thread blocks every signal).

So no thread reads another's frames: a thread's stack is written by the thread itself, from
a signal only it is sent (``tests/_thread_cpu_timer.py``), or read under the GIL through
``sys._current_frames()``. This guard fails any call that dumps every thread, and any config
that turns on pytest's ``faulthandler_timeout`` (``dump_traceback_later`` again)."""

from __future__ import annotations

import ast
import re
from typing import TypeGuard

import _source

_ROOTS = ("src", "tests", "benchmarks", "examples", "scripts", "website")


def _all_threads_false(call: ast.Call) -> bool:
    return any(
        k.arg == "all_threads" and isinstance(k.value, ast.Constant) and k.value.value is False
        for k in call.keywords
    )


def _dumps_every_thread(node: ast.AST) -> TypeGuard[ast.Call | ast.ImportFrom]:
    """``faulthandler.dump_traceback_later(...)``, or ``faulthandler.dump_traceback`` or
    ``faulthandler.register`` without ``all_threads=False``; or importing one by name."""
    if isinstance(node, ast.ImportFrom) and node.module == "faulthandler":
        return any(
            alias.name in ("dump_traceback_later", "dump_traceback", "register")
            for alias in node.names
        )
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "faulthandler"
    ):
        return False
    if node.func.attr == "dump_traceback_later":
        return True
    return node.func.attr in ("dump_traceback", "register") and not _all_threads_false(node)


def _offenders() -> list[str]:
    found: list[str] = []
    for root in _ROOTS:
        for path in _source.files(_source.ROOT / root):
            if not _source.mentions(path, "faulthandler"):
                continue
            for node in _source.walk(path):
                if _dumps_every_thread(node):
                    where = f"{path.relative_to(_source.ROOT)}:{node.lineno}"
                    found.append(f"{where} {ast.unparse(node)}")
    return found


def test_no_code_dumps_every_threads_stack():
    assert _offenders() == []


def test_the_guard_sees_each_way_to_dump_every_thread():
    def offends(source: str) -> bool:
        return any(_dumps_every_thread(node) for node in ast.walk(_source.parse(source)))

    assert offends("faulthandler.dump_traceback_later(5, exit=True)")
    assert offends("faulthandler.dump_traceback(file=f)")
    assert offends("faulthandler.dump_traceback(f, all_threads=True)")
    assert offends("faulthandler.register(sig, file=f)")
    assert offends("from faulthandler import dump_traceback_later")
    assert not offends("faulthandler.dump_traceback(f, all_threads=False)")
    assert not offends("faulthandler.register(sig, file=f, all_threads=False)")
    assert not offends("faulthandler.cancel_dump_traceback_later()")


_TIMEOUT = re.compile(r"^\s*faulthandler_timeout\s*=", re.MULTILINE)


def test_no_pytest_config_turns_on_faulthandler_timeout():
    configs = [
        path
        for pattern in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg")
        for path in _source.files(_source.ROOT, pattern, recursive=False)
    ]
    assert [str(p) for p in configs if _TIMEOUT.search(_source.text(p))] == []
