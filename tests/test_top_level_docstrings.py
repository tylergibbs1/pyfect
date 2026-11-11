"""Every function ``import pyfect as fx`` exports has a docstring, so
``help(fx.run_blocking)`` says what it does (FINDINGS-vault 10: it said
nothing)."""

from __future__ import annotations

import inspect

import pyfect as fx


def test_every_exported_function_has_a_docstring() -> None:
    functions = [name for name in fx.__all__ if inspect.isfunction(getattr(fx, name))]
    assert functions
    assert [name for name in functions if not inspect.getdoc(getattr(fx, name))] == []
