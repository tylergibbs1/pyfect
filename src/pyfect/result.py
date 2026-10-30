"""``Ok[A] | Err[E]``: success or a typed error, as a plain value.

Test which one you have with ``match`` (``case Ok(v)`` / ``case Err(e)``),
``isinstance``, or the ``is_ok`` / ``is_err`` guards. The methods exist on
both classes, so they work on a ``Result`` without narrowing first.
``Effect.result()`` produces one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeIs, TypeVar, overload

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Ok(Generic[A_co]):
    value: A_co

    def map[B](self, f: Callable[[A_co], B]) -> Ok[B]:
        return Ok(f(self.value))

    def map_error(self, f: Callable[[Never], object]) -> Ok[A_co]:
        return self

    def map_both[B](
        self, *, on_failure: Callable[[Never], object], on_success: Callable[[A_co], B]
    ) -> Ok[B]:
        return Ok(on_success(self.value))

    def flat_map[B = Never, E2 = Never](self, f: Callable[[A_co], Result[B, E2]]) -> Result[B, E2]:
        return f(self.value)

    def get_or_else(self, f: Callable[[Never], object]) -> A_co:
        return self.value

    def get_or_raise(self) -> A_co:
        return self.value

    def match[C](
        self, *, on_failure: Callable[[Never], object], on_success: Callable[[A_co], C]
    ) -> C:
        return on_success(self.value)


@dataclass(frozen=True, slots=True)
class Err(Generic[E_co]):
    error: E_co

    def map(self, f: Callable[[Never], object]) -> Err[E_co]:
        return self

    def map_error[E2](self, f: Callable[[E_co], E2]) -> Err[E2]:
        return Err(f(self.error))

    def map_both[E2](
        self, *, on_failure: Callable[[E_co], E2], on_success: Callable[[Never], object]
    ) -> Err[E2]:
        return Err(on_failure(self.error))

    def flat_map(self, f: Callable[[Never], object]) -> Err[E_co]:
        return self

    def get_or_else[B](self, f: Callable[[E_co], B]) -> B:
        return f(self.error)

    def get_or_raise[X: BaseException](self: Err[X]) -> Never:
        """Raise the error. Only an ``Err`` holding an exception has this;
        for other errors, ``match`` or ``get_or_else``."""
        raise self.error

    def match[B](
        self, *, on_failure: Callable[[E_co], B], on_success: Callable[[Never], object]
    ) -> B:
        return on_failure(self.error)


type Result[A, E] = Ok[A] | Err[E]


def is_ok[A, E](result: Result[A, E]) -> TypeIs[Ok[A]]:
    return isinstance(result, Ok)


def is_err[A, E](result: Result[A, E]) -> TypeIs[Err[E]]:
    return isinstance(result, Err)


@overload
def try_[A](thunk: Callable[[], A]) -> Result[A, Exception]: ...
@overload
def try_[A, E](thunk: Callable[[], A], catch: Callable[[Exception], E]) -> Result[A, E]: ...
def try_(
    thunk: Callable[[], Any], catch: Callable[[Exception], Any] | None = None
) -> Result[Any, Any]:
    """``Ok`` of what ``thunk`` returns, or ``Err`` of the exception it
    raised (mapped through ``catch`` when given)."""
    try:
        return Ok(thunk())
    except Exception as exc:
        return Err(exc if catch is None else catch(exc))


def from_optional[A = Never, E = Never](value: A | None, on_none: Callable[[], E]) -> Result[A, E]:
    return Err(on_none()) if value is None else Ok(value)


@overload
def all[A1 = Never, EE = Never](r1: Result[A1, EE], /) -> Result[tuple[A1], EE]: ...
@overload
def all[A1 = Never, A2 = Never, EE = Never](
    r1: Result[A1, EE], r2: Result[A2, EE], /
) -> Result[tuple[A1, A2], EE]: ...
@overload
def all[A1 = Never, A2 = Never, A3 = Never, EE = Never](
    r1: Result[A1, EE], r2: Result[A2, EE], r3: Result[A3, EE], /
) -> Result[tuple[A1, A2, A3], EE]: ...
@overload
def all[A1 = Never, A2 = Never, A3 = Never, A4 = Never, EE = Never](
    r1: Result[A1, EE], r2: Result[A2, EE], r3: Result[A3, EE], r4: Result[A4, EE], /
) -> Result[tuple[A1, A2, A3, A4], EE]: ...
@overload
def all[A = Never, EE = Never](*results: Result[A, EE]) -> Result[tuple[A, ...], EE]: ...
def all(*results: Result[Any, Any]) -> Result[tuple[Any, ...], Any]:
    """The values in order, or the first ``Err``."""
    values: list[Any] = []
    for r in results:
        match r:
            case Ok(value):
                values.append(value)
            case Err():
                return r
    return Ok(tuple(values))


__all__ = ["Err", "Ok", "Result", "all", "from_optional", "is_err", "is_ok", "try_"]
