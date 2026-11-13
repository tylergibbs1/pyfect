"""Checks that a run lets go of the values it handled at once, without the
cycle collector: a reference cycle (a loop closure that reaches itself)
would keep them, and the sockets or files they own, until it runs."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable
from typing import Any

import pyfect as fx


class Handled:
    """A value a program handles; the test checks it is freed after the run."""

    __slots__ = ("__weakref__", "label")

    def __init__(self, label: str = "") -> None:
        self.label = label


def assert_freed_after_run(build: Callable[[Handled], fx.Effect[Any, Any, Any]]) -> None:
    """Run ``build(value)`` with the cycle collector off, then check ``value``
    is gone: only the program held it, and the run is over. The run may fail;
    its exit is dropped."""
    gc.collect()
    gc.disable()
    try:
        value = Handled()
        freed = weakref.ref(value)
        program = build(value).exit().map(lambda _: None)
        del value
        fx.run_blocking(program)
        del program
        assert freed() is None, "the run still holds a value it handled"
    finally:
        gc.enable()
