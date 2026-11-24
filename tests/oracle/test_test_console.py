"""Ports of Effect's ``test/TestConsole.test.ts``, every title. Each test's
docstring is the Effect test title; ``${method}`` is the parameter."""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import console, testing

_READERS: list[tuple[str, Callable[..., fx.Effect[None]], fx.Effect[list[object]]]] = [
    ("warn", console.warn, testing.warn_lines),
    ("info", console.info, testing.info_lines),
    ("debug", console.debug, testing.debug_lines),
    ("trace", console.trace, testing.trace_lines),
]


@pytest.mark.parametrize(("method", "write", "read"), _READERS)
@testing.effect
def test_lines_captures_parameters_from_only_that_methods_calls(
    method: str, write: Callable[..., fx.Effect[None]], read: fx.Effect[list[object]]
):
    """${method}Lines captures parameters from only ${method} calls"""
    details: dict[str, Any] = {"value": 1}
    yield from console.log("log", details)
    yield from console.error("error", details)
    yield from console.warn("warn", details)
    yield from console.info("info", details)
    yield from console.debug("debug", details)
    yield from console.trace("trace", details)
    yield from write("second", 42)

    lines = yield from read
    assert lines == [method, details, "second", 42]
