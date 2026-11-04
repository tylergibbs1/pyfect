"""Harvest #2: a curried ``fx.catch_all(lambda e: ...)`` inside ``.pipe`` leaves ``e``
``Unknown``; pyright strict reports "Argument type is partially unknown".

``fx.catch_all(...)`` is evaluated before ``.pipe`` binds it to the effect. It returns
a class with a generic ``__call__`` (so the effect's own ``A`` and ``R`` stay exact), and
pyright passes no expected type into such a call. Returning a plain
``Callable[[Effect[A, E, R]], ...]`` instead does not help: ``.pipe``'s parameter is
``Callable[[Self], B]`` with ``B`` unsolved, and ``e`` stays ``Unknown``. (On an
assignment-narrowed effect, ``x: Effect[str, ValueError, int] = fx.fail(...)``, it seems
to infer ``e``, but only because ``A`` and ``R`` are ``Never`` there.) Use the method form
or a typed ``def``.
"""

from collections.abc import Callable
from typing import Never, reveal_type

import pyfect as fx



def make_fallible() -> fx.Effect[str, ValueError, int]: ...


fallible = make_fallible()


def as_callable[A, E, R, B, E2 = Never, R2 = Never](
    f: Callable[[E], fx.Effect[B, E2, R2]],
) -> Callable[[fx.Effect[A, E, R]], fx.Effect[A | B, E2, R | R2]]: ...


def recover(e: ValueError) -> fx.Effect[str]:
    return fx.succeed(str(e))


reveal_type(fallible.pipe(fx.catch_all(lambda e: fx.succeed(""))))  # e: Unknown (strict error)
reveal_type(fallible.pipe(as_callable(lambda e: fx.succeed(e))))  # e: Unknown too
reveal_type(fallible.pipe(fx.catch_all(recover)))  # Effect[str, Never, int]
reveal_type(fallible.catch_all(lambda e: fx.succeed(str(e))))  # Effect[str, Never, int]
