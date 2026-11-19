"""A signal handler that dumps every thread's stack reads frames other threads are changing,
from whichever thread the signal landed on: ``faulthandler.register(sig, all_threads=True)``
under a recurring timer segfaulted CPython (the stall watchdog's SIGPROF samples, an xdist
worker lost on Python 3.13). So code here registers faulthandler on a signal only with
``all_threads=False``, and a sampler signals the one thread it reads
(``tests/_thread_cpu_timer.py``)."""

from __future__ import annotations

import ast

import _source


def _offenders() -> list[str]:
    found: list[str] = []
    for root in (_source.SRC, _source.TESTS):
        for path in _source.files(root):
            if not _source.mentions(path, "faulthandler"):
                continue
            for node in _source.walk(path):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "register"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "faulthandler"
                    and not any(
                        k.arg == "all_threads"
                        and isinstance(k.value, ast.Constant)
                        and k.value.value is False
                        for k in node.keywords
                    )
                ):
                    where = f"{path.relative_to(_source.ROOT)}:{node.lineno}"
                    found.append(f"{where} {ast.unparse(node)}")
    return found


def test_no_signal_handler_dumps_every_threads_stack():
    assert _offenders() == []
