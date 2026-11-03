"""Recovery that removes the caught errors from ``E``: use with ``.pipe``.

``catch_tag`` catches by class (one, or a tuple of any number), ``catch_if``
by a ``TypeIs`` refinement. Both remove exactly what they catch::

    eff.pipe(catch_tag((NotFound, Invalid), lambda e: succeed(None)))

``catch_all`` is the method of that name for ``.pipe`` (Effect's
``catch``): it removes every typed error.

``or_else`` handles every other error. Annotate its parameter with those
errors (it must be a ``def``; a lambda's parameter can't be inferred here)
and pyright checks that it covers all of them.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, TypeIs, overload

from pyfect._core import Effect, _catching_if, _MatchCause
from pyfect._tags import Tags


class _CatchSome[EC, B, E2, R2]:
    """Removes ``EC`` from an effect's errors."""

    __slots__ = ("handle",)

    def __init__(self, handle: Callable[[Any], Effect[Any, Any, Any]]) -> None:
        self.handle = handle

    @overload
    def __call__[A, R = Never](self, eff: Effect[A, EC, R]) -> Effect[A | B, E2, R | R2]: ...
    @overload
    def __call__[A, R = Never, ER = Never](
        self, eff: Effect[A, EC | ER, R]
    ) -> Effect[A | B, ER | E2, R | R2]: ...
    def __call__(self, eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        return _MatchCause(eff, self.handle, None)


class _CatchAll[EC, EO, B, C, EE, RR]:
    """Handles ``EC`` with one handler and ``EO``, which must be every other
    error of the effect, with another."""

    __slots__ = ("handle",)

    def __init__(self, handle: Callable[[Any], Effect[Any, Any, Any]]) -> None:
        self.handle = handle

    def __call__[A, R = Never](self, eff: Effect[A, EC | EO, R]) -> Effect[A | B | C, EE, R | RR]:
        return _MatchCause(eff, self.handle, None)


class _CatchEvery[E, B, E2, R2]:
    """Handles every typed error ``E`` of an effect."""

    __slots__ = ("f",)

    def __init__(self, f: Callable[[E], Effect[B, E2, R2]]) -> None:
        self.f = f

    def __call__[A, R = Never](self, eff: Effect[A, E, R]) -> Effect[A | B, E2, R | R2]:
        return eff.catch_all(self.f)


def catch_all[E, B, E2 = Never, R2 = Never](
    f: Callable[[E], Effect[B, E2, R2]],
) -> _CatchEvery[E, B, E2, R2]:
    """``eff.catch_all(f)`` for ``.pipe``: recover from every typed error.
    Defects and interruptions pass through. Annotate ``f``'s parameter (a
    ``def``): pyright checks it covers every error of the effect."""
    return _CatchEvery(f)


@overload
def catch_if[EB, B, E2 = Never, R2 = Never](
    refinement: Callable[[Any], TypeIs[EB]], f: Callable[[EB], Effect[B, E2, R2]]
) -> _CatchSome[EB, B, E2, R2]: ...
@overload
def catch_if[EB, EO, B, C, EE = Never, RR = Never](
    refinement: Callable[[Any], TypeIs[EB]],
    f: Callable[[EB], Effect[B, EE, RR]],
    *,
    or_else: Callable[[EO], Effect[C, EE, RR]],
) -> _CatchAll[EB, EO, B, C, EE, RR]: ...
def catch_if(
    refinement: Callable[[Any], bool],
    f: Callable[[Any], Effect[Any, Any, Any]],
    *,
    or_else: Callable[[Any], Effect[Any, Any, Any]] | None = None,
) -> Any:
    """Recover from the typed errors ``refinement`` accepts and remove them
    from ``E``. For a plain ``bool`` predicate, use the ``catch_if`` method."""
    handle = _catching_if(refinement, f, or_else)
    if or_else is None:
        return _CatchSome[Any, Any, Any, Any](handle)
    return _CatchAll[Any, Any, Any, Any, Any, Any](handle)


@overload
def catch_tag[T, B, E2 = Never, R2 = Never](
    tag: Tags[T], f: Callable[[T], Effect[B, E2, R2]]
) -> _CatchSome[T, B, E2, R2]: ...
@overload
def catch_tag[T, EO, B, C, EE = Never, RR = Never](
    tag: Tags[T],
    f: Callable[[T], Effect[B, EE, RR]],
    *,
    or_else: Callable[[EO], Effect[C, EE, RR]],
) -> _CatchAll[T, EO, B, C, EE, RR]: ...
def catch_tag(
    tag: Tags[Any],
    f: Callable[[Any], Effect[Any, Any, Any]],
    *,
    or_else: Callable[[Any], Effect[Any, Any, Any]] | None = None,
) -> Any:
    """Recover from the errors that are instances of ``tag`` (a class or a
    tuple of classes) and remove them from ``E``::

    eff.pipe(catch_tag(NotFound, lambda e: succeed(None)))
    """
    handle = _catching_if(lambda e: isinstance(e, tag), f, or_else)
    if or_else is None:
        return _CatchSome[Any, Any, Any, Any](handle)
    return _CatchAll[Any, Any, Any, Any, Any, Any](handle)
