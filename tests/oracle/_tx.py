"""``@in_tx``: a test body run as one transaction, as Effect's tests wrap
their program in ``Effect.tx(Effect.gen(...))``. Stack it under
``@testing.effect``."""

import functools
from collections.abc import Callable, Generator
from typing import Any

import pyfect as fx

type Body = Callable[[], Generator[fx.Effect[Any, Any, Any], Any]]


def in_tx(body: Body) -> Callable[[], fx.Effect[None, Any]]:
    @functools.wraps(body)
    def run() -> fx.Effect[None, Any]:
        return fx.tx(fx.fn(body)())

    return run
