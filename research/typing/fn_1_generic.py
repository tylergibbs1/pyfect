"""Forge #2: a generic ``@fx.fn`` body loses its type parameter.

Pyright solves the type parameters of a generic function passed as an argument
together with the decorator's. Matching the body's yield type, a union of effects,
against ``Effect[Any, E, R]`` then binds the body's own ``R``: it becomes ``Unknown``
when one effect needs ``R | Scope`` and the other nothing, and collapses into the
other requirement (``R := Scope``) when they are separate. The same happens to a
generic ``E``. ``uv run pyright -p research/typing research/typing/fn_1_generic.py``.

Tried:
- ``Callable[P, Generator[Y, Any, A]]`` keeps ``R`` in ``Y``, but nothing turns ``Y``
  (a union of effects) back into ``E`` and ``R``; a self-typed ``__call__`` on the
  result re-matches ``Y`` and collapses ``R`` the same way.
- Several requirement slots (``Effect[Any, E, R1] | Effect[Any, E, R2] | ...``) keep
  ``R`` only while the body yields no more distinct effects than there are slots, in
  an order pyright picks; separate error slots give ``Never | Never`` = ``Unknown``,
  and a body yielding only ``succeed`` infers ``Unknown`` for both.
- A return annotation, ``-> fx.Gen[A, E, R]`` (``Generator[Effect[Any, E, R], Any, A]``),
  gives one yield type to match, and the decorator keeps ``R``.

Adopted: ``fx.Gen``, and ``fn`` raises ``TypeError`` for a generic body (PEP 695
type parameters) with no return annotation, so the silent case can't be written.
"""

from collections.abc import Callable, Generator
from typing import Any, Never, reveal_type

import pyfect as fx
from pyfect.scope import Scope


class Db: ...


def scoped[R](eff: fx.Effect[int, Never, R]):
    fiber = yield from eff.fork_scoped()
    return (yield from fiber.join())


def with_other[R](eff: fx.Effect[int, Never, R], other: fx.Effect[int, Never, Scope]):
    yield from other
    return (yield from eff)


def annotated[R](eff: fx.Effect[int, Never, R]) -> fx.Gen[int, Never, R | Scope]:
    fiber = yield from eff.fork_scoped()
    return (yield from fiber.join())


def fn_like[**P, A, E = Never, R = Never](
    f: Callable[P, Generator[fx.Effect[Any, E, R], Any, A]],
) -> Callable[P, fx.Effect[A, E, R]]: ...


def whole_yield[**P, Y, A](f: Callable[P, Generator[Y, Any, A]]) -> Callable[P, Y]: ...


def slots[**P, A, E = Never, R1 = Never, R2 = Never](
    f: Callable[P, Generator[fx.Effect[Any, E, R1] | fx.Effect[Any, E, R2], Any, A]],
) -> Callable[P, fx.Effect[A, E, R1 | R2]]: ...


def three[R](
    eff: fx.Effect[int, Never, R], a: fx.Effect[int, Never, Scope], b: fx.Effect[int, Never, Db]
):
    yield from a
    yield from b
    return (yield from eff)


reveal_type(fn_like(scoped))  # (eff: Effect[int, Never, Unknown]) -> Effect[int, Never, Unknown | Scope]
reveal_type(fn_like(with_other))  # (eff: Effect[int, Never, Scope], ...) -> Effect[int, Never, Scope]
reveal_type(whole_yield(scoped))  # keeps R, but as a union of effects
reveal_type(slots(with_other))  # keeps R: two slots, two effects
reveal_type(slots(three))  # three effects, two slots: R := Scope again
reveal_type(fx.fn(annotated))  # (eff: Effect[int, Never, R]) -> Effect[int, Never, R | Scope]
