"""Can ``endpoint.middleware(Inner).middleware(Outer)`` take what Outer provides off what
Inner needs, as Effect's ``ApplyServices`` does (``Exclude<Requires<Inner>,
Provides<Outer>> | Requires<Outer>``)?

Run with ``uv run pyright -p research/typing research/typing/httpapi_3_middleware_chain.py``.

Findings (pyright 1.1.414):

C1. Union matching subtracts only a type that is already fixed: a class parameter of
    the object a method is bound to (``Bound``'s ``MP``), or a TypeVar solved from
    ``self`` before the arguments. Solved from the same argument (``needs_one_argument``)
    or an earlier one, the TypeVar is not subtracted.
C2. So a method can't subtract what its argument provides from ``self``'s services:
    ``self`` binds first (``exp3_methods.py``). It can subtract one class parameter from
    another, by a ``self`` annotation over the class's own TypeVars (``X.rest``).
C3. ``endpoint.middleware`` is a descriptor: reading it solves the outermost middleware's
    provides and needs into ``AddMiddleware``'s class parameters, and calling it takes
    them off what the inner middleware need. The endpoint keeps the outermost middleware
    and what those inside it need; ``handle`` / ``entry`` take the last one's provides off
    in the handler call, as ``Bound`` takes ``MP`` off the handler's services.
C4. Subtracting from ``Never`` solves the rest as ``Unknown`` (``X.rest`` on ``empty``),
    so ``Bound`` and ``EntrySlot`` join a marker to what they subtract from and take it
    off with the rest. A rest fully subtracted is the method TypeVar's default, ``Never``.
C5. A union of class TypeVars that are both ``Never`` is ``Unknown``, so the case where
    nothing is subtracted (``Seal`` alone) has its own first overloads.
C6. A ``Never`` group middleware matches any ``HttpApiGroup[HttpApiMiddleware[GP1, ...]]``
    ``self`` pattern with ``GP1`` ``Unknown``; a parameter type built from ``GP1`` makes the
    whole bound method partially unknown, so ``GP`` comes off in ``Bound``, not ``handle``.
C7. ``Bound`` takes ``GP`` off the outermost middleware's needs and ``LP | GP`` off the inner
    ones' with one shared TypeVar for both rests (two ``Never``-defaulted ones in a union
    widen to ``Unknown``, ``tests/test_typing_rules.py``); pyright joins the two solutions.
"""

from __future__ import annotations

from typing import Any, Generic, Never, TypeVar, assert_type, overload

from pyfect import Tag

A_co = TypeVar("A_co", covariant=True, default=Never)
B_co = TypeVar("B_co", covariant=True, default=Never)


class Session(Tag[str]): ...


class Other(Tag[str]): ...


class X(Generic[A_co, B_co]):
    def rest[R1 = Never](self: X[A_co, R1 | A_co]) -> list[R1]: ...


class Provides(Generic[A_co]): ...


@overload
def needs_one_argument[P](e: tuple[Provides[P], X[Never, Never]]) -> list[Never]: ...
@overload
def needs_one_argument[P, R1](e: tuple[Provides[P], X[Never, R1 | P]]) -> list[R1]: ...
def needs_one_argument(e: Any) -> Any: ...


def check(
    both: X[Session, Session | Other],
    covered: X[Session, Session],
    empty: X[Session, Never],
    pair: tuple[Provides[Session], X[Never, Session | Other]],
) -> None:
    assert_type(both.rest(), list[Other])  # C2
    assert_type(covered.rest(), list[Never])  # C4: the default
    assert_type(empty.rest(), list[Never])  # pyright: ignore[reportAssertTypeFailure]  # C4: Unknown
    assert_type(needs_one_argument(pair), list[Other])  # pyright: ignore[reportAssertTypeFailure]  # C1
