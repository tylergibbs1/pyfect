"""``Request[A, E, R]`` and the ``Entry`` a resolver completes."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Never, Protocol, Self, TypeVar

from pyfect._core import Effect, _Succeed, _Sync
from pyfect._effect_args import require_effect
from pyfect.cause import Cause
from pyfect.context import Context
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as exit_fail

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)
Q_co = TypeVar("Q_co", covariant=True)
_A_co = TypeVar("_A_co", covariant=True)
_E_co = TypeVar("_E_co", covariant=True)
_R_co = TypeVar("_R_co", covariant=True)


class Request(Generic[A_co, E_co, R_co]):
    """A request that succeeds with ``A``, fails with ``E`` and needs the
    services ``R``. Subclass it as a frozen dataclass, so equal requests
    compare equal (``with_cache`` and grouping rely on it)::

        @dataclass(frozen=True)
        class GetUser(fx.Request[User, NotFound]):
            id: int
    """

    __slots__ = ()

    def _request_types(self) -> tuple[A_co, E_co, R_co, Self]:
        """Never called: lets ``request`` read ``A``, ``E``, ``R`` and the
        request's own class from one argument."""
        raise NotImplementedError


class TypedRequest(Protocol[_A_co, _E_co, _R_co, Q_co]):
    """A ``Request[A, E, R]`` whose class is ``Q``."""

    def _request_types(self) -> tuple[_A_co, _E_co, _R_co, Q_co]: ...


class Entry(Generic[Q_co]):
    """One pending request inside a batch: the request, the services of
    the fiber that made it, and the way to complete it.

    Resolvers complete each entry once; later completions are ignored.
    ``uninterruptible`` keeps the entry in its batch when its caller is
    interrupted (``with_cache`` sets it on a request others wait for)."""

    __slots__ = ("_complete", "_context", "_request", "uninterruptible")

    def __init__(
        self,
        request: Q_co,
        *,
        context: Context,
        complete_unsafe: Callable[[Exit[Any, Any]], None],
        uninterruptible: bool = False,
    ) -> None:
        self._request = request
        self._context = context
        self._complete = complete_unsafe
        self.uninterruptible = uninterruptible

    @property
    def request(self) -> Q_co:
        return self._request

    @property
    def context(self) -> Context:
        """The services of the fiber that made the request."""
        return self._context

    def complete_unsafe[A, E](self: Entry[Request[A, E, Any]], ex: Exit[A, E], /) -> None:
        """Complete the request now with ``ex``."""
        self._complete(ex)

    def complete[A, E](self: Entry[Request[A, E, Any]], ex: Exit[A, E], /) -> Effect[None]:
        """The effect that completes the request with ``ex``."""
        return _Sync(lambda: self._complete(ex))

    def complete_effect[A, E, R](
        self: Entry[Request[A, E, Any]], eff: Effect[A, E, R], /
    ) -> Effect[None, Never, R]:
        """Run ``eff`` and complete the request with its value or typed
        error. Defects and interruptions are not caught."""
        require_effect(eff, "eff")
        complete = self._complete

        def done(ex: Exit[Any, Any]) -> Effect[None]:
            complete(ex)
            return _VOID

        return eff.match_effect(
            on_failure=lambda e: done(exit_fail(e)), on_success=lambda a: done(Success(a))
        )

    def succeed[A](self: Entry[Request[A, Any, Any]], value: A, /) -> Effect[None]:
        return _Sync(lambda: self._complete(Success(value)))

    def fail[E](self: Entry[Request[Any, E, Any]], error: E, /) -> Effect[None]:
        return _Sync(lambda: self._complete(exit_fail(error)))

    def fail_cause[E](self: Entry[Request[Any, E, Any]], cause: Cause[E], /) -> Effect[None]:
        return _Sync(lambda: self._complete(Failure(cause)))

    def __repr__(self) -> str:
        return f"Entry({self._request!r})"


_VOID: Effect[None] = _Succeed(None)
