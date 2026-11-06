"""``Ok[A] | Err[E]``: success or a typed error, as a plain value.

Test which one you have with ``match`` (``case Ok(v)`` / ``case Err(e)``),
``isinstance``, or the ``is_ok`` / ``is_err`` guards. The methods exist on
both classes, so they work on a ``Result`` without narrowing first.
``Effect.result()`` produces one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeIs, TypeVar, cast, overload

from pyfect._some import Option, Some

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

    @overload
    def and_then[B, E2](  # pyright: ignore[reportOverlappingOverload]
        self, that: Callable[[A_co], Result[B, E2]]
    ) -> Result[B, E2]: ...
    @overload
    def and_then[B](self, that: Callable[[A_co], B]) -> Ok[B]: ...
    @overload
    def and_then[B, E2 = Never](self, that: Result[B, E2]) -> Result[B, E2]: ...
    @overload
    def and_then[B](self, that: B) -> Ok[B]: ...
    def and_then(self, that: Any) -> Any:
        """After this success: ``that(value)`` for a function, ``that``
        otherwise; what is not already a ``Result`` becomes ``Ok``."""
        result: object = that(self.value) if callable(that) else that
        return cast("Any", result) if isinstance(result, Ok | Err) else Ok(result)

    def or_else(self, f: Callable[[Never], object]) -> Ok[A_co]:
        return self

    def tap(self, f: Callable[[A_co], object]) -> Ok[A_co]:
        """Call ``f`` with the value for its side effect."""
        f(self.value)
        return self

    def flip(self) -> Err[A_co]:
        return Err(self.value)

    def merge(self) -> A_co:
        """The value, from either side."""
        return self.value

    @overload
    def filter_or_fail[B, E2](
        self, predicate: Callable[[A_co], TypeIs[B]], or_fail_with: Callable[[A_co], E2]
    ) -> Ok[B] | Err[E2]: ...
    @overload
    def filter_or_fail[E2](
        self, predicate: Callable[[A_co], bool], or_fail_with: Callable[[A_co], E2]
    ) -> Ok[A_co] | Err[E2]: ...
    def filter_or_fail(
        self, predicate: Callable[[Any], bool], or_fail_with: Callable[[Any], Any]
    ) -> Result[Any, Any]:
        """This success if ``predicate`` holds, else ``Err(or_fail_with(value))``."""
        return self if predicate(self.value) else Err(or_fail_with(self.value))

    def get_or_none(self) -> A_co:
        return self.value

    def get_or_raise_with(self, f: Callable[[Never], BaseException]) -> A_co:
        return self.value


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

    def and_then(self, that: object) -> Err[E_co]:
        return self

    def or_else[B = Never, E2 = Never](self, f: Callable[[E_co], Result[B, E2]]) -> Result[B, E2]:
        """Recover with ``f(error)``."""
        return f(self.error)

    def tap(self, f: Callable[[Never], object]) -> Err[E_co]:
        return self

    def flip(self) -> Ok[E_co]:
        return Ok(self.error)

    def merge(self) -> E_co:
        """The error, from either side."""
        return self.error

    def filter_or_fail(
        self, predicate: Callable[[Never], bool], or_fail_with: Callable[[Never], object]
    ) -> Err[E_co]:
        return self

    def get_or_none(self) -> None:
        return None

    def get_or_raise_with(self, f: Callable[[E_co], BaseException]) -> Never:
        """Raise ``f(error)``."""
        raise f(self.error)


type Result[A, E] = Ok[A] | Err[E]


void: Ok[None] = Ok(None)
"""``Ok(None)``: success with nothing to say."""

fail_void: Err[None] = Err(None)
"""``Err(None)``: failure with nothing to say."""

succeed_none: Ok[None] = Ok(None)
"""``Ok`` of an absent ``Option``."""


def succeed_some[A](value: A) -> Ok[Some[A]]:
    return Ok(Some(value))


def is_result(value: object) -> TypeIs[Ok[object] | Err[object]]:
    return isinstance(value, (Ok, Err))


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


def from_option[A = Never, E = Never](option: Option[A], on_none: Callable[[], E]) -> Result[A, E]:
    return Err(on_none()) if option is None else Ok(option.value)


@overload
def lift_predicate[A, B, E](
    value: A, predicate: Callable[[A], TypeIs[B]], or_fail_with: Callable[[A], E]
) -> Result[B, E]: ...
@overload
def lift_predicate[A, E](
    value: A, predicate: Callable[[A], bool], or_fail_with: Callable[[A], E]
) -> Result[A, E]: ...
def lift_predicate(
    value: Any, predicate: Callable[[Any], bool], or_fail_with: Callable[[Any], Any]
) -> Result[Any, Any]:
    """``Ok(value)`` if the predicate holds, else ``Err(or_fail_with(value))``."""
    return Ok(value) if predicate(value) else Err(or_fail_with(value))


def transpose_option[A = Never, E = Never](option: Option[Result[A, E]]) -> Result[Option[A], E]:
    """``Some(Ok(a))`` is ``Ok(Some(a))``, ``Some(Err(e))`` is ``Err(e)``, ``None`` is
    ``Ok(None)``."""
    return transpose_map_option(option, lambda r: r)


def transpose_map_option[A, B = Never, E = Never](
    option: Option[A], f: Callable[[A], Result[B, E]]
) -> Result[Option[B], E]:
    """``transpose_option`` of the option mapped through ``f``."""
    if option is None:
        return succeed_none
    return f(option.value).map(Some)


def all_dict[K, A = Never, EE = Never](
    results: Mapping[K, Result[A, EE]],
) -> Result[dict[K, A], EE]:
    """The values under their keys, or the first ``Err``."""
    values: dict[K, A] = {}
    for key, r in results.items():
        match r:
            case Ok(value):
                values[key] = value
            case Err():
                return r
    return Ok(values)


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


__all__ = [
    "Err",
    "Ok",
    "Result",
    "all",
    "all_dict",
    "fail_void",
    "from_option",
    "from_optional",
    "is_err",
    "is_ok",
    "is_result",
    "lift_predicate",
    "succeed_none",
    "succeed_some",
    "transpose_map_option",
    "transpose_option",
    "try_",
    "void",
]
