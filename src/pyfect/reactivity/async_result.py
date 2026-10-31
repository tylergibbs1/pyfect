"""``AsyncResult``: the state of a value computed asynchronously (Effect's
``effect/reactivity/AsyncResult``).

An ``AsyncResult[A, E]`` is ``Initial`` (no value yet), ``Success`` (a
value and when it arrived) or ``Failure`` (a ``Cause``, and the last
success if there was one). Each also says whether a newer computation is
``waiting``. Atoms backed by effects and streams hold one.

Two results are equal when their tags, ``waiting`` and value (or cause)
are: a success's timestamp and a failure's previous success do not count.

The functions are data-first (``map(result, f)``); take a result apart
with ``match``::

    match result:
        case Success(value=value):
            ...
        case Failure(cause=cause):
            ...
        case Initial():
            ...
"""

from __future__ import annotations

import builtins
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Generic, Never, TypeIs, TypeVar, cast, overload

from pyfect import _equal
from pyfect import cause as cause_
from pyfect._public import publish
from pyfect.cause import Cause
from pyfect.errors import NoSuchElementException
from pyfect.exit import Exit
from pyfect.exit import Failure as ExitFailure
from pyfect.exit import Success as ExitSuccess
from pyfect.exit import fail as exit_fail
from pyfect.exit import succeed as exit_succeed
from pyfect.option import Option, Some
from pyfect.reactivity._time import now_millis
from pyfect.result import Err, Ok

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)


class _Base(Generic[A_co, E_co]):
    __slots__ = ("waiting",)

    waiting: bool

    def _tag_hash(self) -> int:
        return hash((type(self).__name__, self.waiting))


class Initial(_Base[A_co, E_co]):
    """No value yet."""

    __slots__ = ()
    __match_args__ = ("waiting",)

    def __init__(self, waiting: bool = False) -> None:
        self.waiting = waiting

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Initial) and self.waiting == other.waiting

    def __hash__(self) -> int:
        return self._tag_hash()

    def __repr__(self) -> str:
        return f"Initial(waiting={self.waiting})"


class Success(_Base[A_co, E_co]):
    """A value, and when it arrived (epoch milliseconds)."""

    __slots__ = ("timestamp", "value")
    __match_args__ = ("value", "waiting", "timestamp")

    def __init__(self, value: A_co, waiting: bool = False, timestamp: int | None = None) -> None:
        self.value = value
        self.waiting = waiting
        self.timestamp = now_millis() if timestamp is None else timestamp

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Success):
            return False
        that = cast("Success[object, object]", other)
        return self.waiting == that.waiting and _equal.equals(self.value, that.value)

    def __hash__(self) -> int:
        return hash((self._tag_hash(), _value_hash(self.value)))

    def __repr__(self) -> str:
        return f"Success({self.value!r}, waiting={self.waiting}, timestamp={self.timestamp})"


class Failure(_Base[A_co, E_co]):
    """A cause, and the last success before it, if there was one."""

    __slots__ = ("cause", "previous_success")
    __match_args__ = ("cause", "previous_success", "waiting")

    def __init__(
        self,
        cause: Cause[E_co],
        previous_success: Option[Success[A_co, E_co]] = None,
        waiting: bool = False,
    ) -> None:
        self.cause = cause
        self.previous_success = previous_success
        self.waiting = waiting

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Failure):
            return False
        that = cast("Failure[object, object]", other)
        return self.waiting == that.waiting and self.cause == that.cause

    def __hash__(self) -> int:
        return hash((self._tag_hash(), hash(self.cause)))

    def __repr__(self) -> str:
        return (
            f"Failure({self.cause!r}, previous_success={self.previous_success!r}, "
            f"waiting={self.waiting})"
        )


def _value_hash(value: object) -> int:
    try:
        return hash(_equal.equal_key(value))
    except TypeError:
        return 0


type AsyncResult[A, E = Never] = Initial[A, E] | Success[A, E] | Failure[A, E]


# ------------------------------------------------------------------ guards


def is_async_result(u: object) -> TypeIs[AsyncResult[object, object]]:
    return isinstance(u, _Base)


def is_waiting(result: AsyncResult[object, object]) -> bool:
    return result.waiting


def is_initial[A, E](result: AsyncResult[A, E]) -> TypeIs[Initial[A, E]]:
    return isinstance(result, Initial)


def is_not_initial[A, E](result: AsyncResult[A, E]) -> TypeIs[Success[A, E] | Failure[A, E]]:
    return not isinstance(result, Initial)


def is_success[A, E](result: AsyncResult[A, E]) -> TypeIs[Success[A, E]]:
    return isinstance(result, Success)


def is_failure[A, E](result: AsyncResult[A, E]) -> TypeIs[Failure[A, E]]:
    return isinstance(result, Failure)


def is_interrupted(result: AsyncResult[object, object]) -> bool:
    return isinstance(result, Failure) and result.cause.has_interrupts_only


# ------------------------------------------------------------ constructors


def initial[A = Never, E = Never](waiting: bool = False) -> Initial[A, E]:
    return Initial(waiting)


def success[A, E = Never](
    value: A, *, waiting: bool = False, timestamp: int | None = None
) -> Success[A, E]:
    """A success at ``timestamp`` (now by default)."""
    return Success(value, waiting, timestamp)


def failure[A = Never, E = Never](
    cause: Cause[E], *, previous_success: Option[Success[A, E]] = None, waiting: bool = False
) -> Failure[A, E]:
    return Failure(cause, previous_success, waiting)


def _previous_success[A, E](previous: Option[AsyncResult[A, E]]) -> Option[Success[A, E]]:
    match previous:
        case Some(Success() as found):
            return Some(found)
        case Some(Failure() as failed):
            return failed.previous_success
        case _:
            return None


def failure_with_previous[A, E](
    cause: Cause[E], *, previous: Option[AsyncResult[A, E]], waiting: bool = False
) -> Failure[A, E]:
    """A failure keeping the last success of ``previous``."""
    return Failure(cause, _previous_success(previous), waiting)


def fail[E, A = Never](
    error: E, *, previous_success: Option[Success[A, E]] = None, waiting: bool = False
) -> Failure[A, E]:
    return Failure(cause_.fail(error), previous_success, waiting)


def fail_with_previous[A, E](
    error: E, *, previous: Option[AsyncResult[A, E]], waiting: bool = False
) -> Failure[A, E]:
    return failure_with_previous(cause_.fail(error), previous=previous, waiting=waiting)


def from_exit[A, E](exit: Exit[A, E]) -> Success[A, E] | Failure[A, E]:
    if isinstance(exit, ExitSuccess):
        return Success(exit.value)
    return Failure(exit.cause)


def from_exit_with_previous[A, E](
    exit: Exit[A, E], previous: Option[AsyncResult[A, E]]
) -> Success[A, E] | Failure[A, E]:
    if isinstance(exit, ExitSuccess):
        return Success(exit.value)
    return failure_with_previous(exit.cause, previous=previous)


def waiting_from[A, E](previous: Option[AsyncResult[A, E]]) -> AsyncResult[A, E]:
    """``previous`` marked waiting, or a waiting ``Initial``."""
    if previous is None:
        return Initial(True)
    return waiting(previous.value)


# --------------------------------------------------------------- waiting


def _copy[R: AsyncResult[Any, Any]](result: R, waiting: bool) -> R:
    match result:
        case Initial():
            copied: AsyncResult[Any, Any] = Initial(waiting)
        case Success():
            copied = Success(result.value, waiting, result.timestamp)
        case Failure():
            copied = Failure(result.cause, result.previous_success, waiting)
    return copied  # pyright: ignore[reportReturnType]


@overload
def waiting[R: AsyncResult[Any, Any]](self: R, /, *, touch: bool = False) -> R: ...
@overload
def waiting[R: AsyncResult[Any, Any]](*, touch: bool = False) -> Callable[[R], R]: ...
def waiting(self: Any = None, /, *, touch: bool = False) -> Any:
    """``self`` marked waiting; with ``touch``, a success also gets a new
    timestamp. Without ``self``, the function that does it."""
    if self is None:

        def mark(result: AsyncResult[Any, Any]) -> AsyncResult[Any, Any]:
            return waiting(result, touch=touch)

        return mark
    current = cast("AsyncResult[Any, Any]", self)
    if current.waiting:
        return _touch(current) if touch else current
    result = _copy(current, True)
    if touch and isinstance(result, Success):
        result.timestamp = now_millis()
    return result


def touch[R: AsyncResult[Any, Any]](result: R) -> R:
    """A success with a new timestamp; anything else as it is."""
    if isinstance(result, Success):
        touched: AsyncResult[Any, Any] = Success(result.value, result.waiting)
        return touched  # pyright: ignore[reportReturnType]
    return result


_touch = touch


def replace_previous[A, E](
    self: AsyncResult[Any, E], previous: Option[AsyncResult[A, Any]]
) -> AsyncResult[A, E]:
    """A failure's previous success taken from ``previous``; anything else
    as it is."""
    if isinstance(self, Failure):
        return Failure(self.cause, _previous_success(previous), self.waiting)
    return self


# ---------------------------------------------------------------- getters


def value[A, E](self: AsyncResult[A, E]) -> Option[A]:
    """A success's value, or a failure's previous one."""
    match self:
        case Success():
            return Some(self.value)
        case Failure(previous_success=Some(previous)):
            return Some(previous.value)
        case _:
            return None


def get_or_else[A, E, B](self: AsyncResult[A, E], or_else: Callable[[], B]) -> A | B:
    found = value(self)
    return or_else() if found is None else found.value


def get_or_raise[A, E](self: AsyncResult[A, E]) -> A:
    """The value (Effect's ``getOrThrow``), or raise
    ``NoSuchElementException``."""
    found = value(self)
    if found is None:
        raise NoSuchElementException("AsyncResult.getOrThrow: no value found")
    return found.value


def cause[A, E](self: AsyncResult[A, E]) -> Option[Cause[E]]:
    return Some(self.cause) if isinstance(self, Failure) else None


def error[A, E](self: AsyncResult[A, E]) -> Option[E]:
    """A failure's first typed error."""
    if isinstance(self, Failure):
        found = self.cause.find_error()
        return Some(found.value) if isinstance(found, Ok) else None
    return None


def to_exit[A, E](self: AsyncResult[A, E]) -> Exit[A, E | NoSuchElementException]:
    match self:
        case Success():
            return exit_succeed(self.value)
        case Failure():
            return ExitFailure(self.cause)
        case Initial():
            return exit_fail(NoSuchElementException())


# ----------------------------------------------------------- combinators


def map[A, E, B](self: AsyncResult[A, E], f: Callable[[A], B]) -> AsyncResult[B, E]:
    """``f`` of the value, and of a failure's previous success."""
    match self:
        case Initial():
            return Initial(self.waiting)
        case Failure():
            previous = self.previous_success
            return Failure(
                self.cause,
                None
                if previous is None
                else Some(
                    Success(
                        f(previous.value.value), previous.value.waiting, previous.value.timestamp
                    )
                ),
                self.waiting,
            )
        case Success():
            return Success(f(self.value), self.waiting, self.timestamp)


def flat_map[A, B, EE](
    self: AsyncResult[A, EE], f: Callable[[A, Success[A, EE]], AsyncResult[B, EE]]
) -> AsyncResult[B, EE]:
    match self:
        case Initial():
            return Initial(self.waiting)
        case Failure():
            previous = self.previous_success
            kept: Option[Success[B, EE]] = None
            if previous is not None:
                nxt = f(previous.value.value, previous.value)
                kept = Some(nxt) if isinstance(nxt, Success) else None
            return Failure(self.cause, kept, self.waiting)
        case Success():
            return f(self.value, self)


def match[A, E, X, Y, Z](
    self: AsyncResult[A, E],
    *,
    on_initial: Callable[[Initial[A, E]], X],
    on_failure: Callable[[Failure[A, E]], Y],
    on_success: Callable[[Success[A, E]], Z],
) -> X | Y | Z:
    match self:
        case Initial():
            return on_initial(self)
        case Failure():
            return on_failure(self)
        case Success():
            return on_success(self)


def _error_or_defect[A, E, X, Y](
    self: Failure[A, E],
    on_error: Callable[[E, Failure[A, E]], X],
    on_defect: Callable[[object, Failure[A, E]], Y],
) -> X | Y:
    match self.cause.find_error():
        case Ok(found):
            return on_error(found, self)
        case Err(rest):
            return on_defect(rest.squash(), self)


def match_with_error[A, E, W, X, Y, Z](
    self: AsyncResult[A, E],
    *,
    on_initial: Callable[[Initial[A, E]], W],
    on_error: Callable[[E, Failure[A, E]], X],
    on_defect: Callable[[object, Failure[A, E]], Y],
    on_success: Callable[[Success[A, E]], Z],
) -> W | X | Y | Z:
    match self:
        case Initial():
            return on_initial(self)
        case Failure():
            return _error_or_defect(self, on_error, on_defect)
        case Success():
            return on_success(self)


def match_with_waiting[A, E, W, X, Y, Z](
    self: AsyncResult[A, E],
    *,
    on_waiting: Callable[[AsyncResult[A, E]], W],
    on_error: Callable[[E, Failure[A, E]], X],
    on_defect: Callable[[object, Failure[A, E]], Y],
    on_success: Callable[[Success[A, E]], Z],
) -> W | X | Y | Z:
    if self.waiting:
        return on_waiting(self)
    match self:
        case Initial():
            return on_waiting(self)
        case Failure():
            return _error_or_defect(self, on_error, on_defect)
        case Success():
            return on_success(self)


@overload
def all[A, E](  # pyright: ignore[reportOverlappingOverload]
    results: Mapping[str, AsyncResult[A, E]], /
) -> AsyncResult[dict[str, A], E]: ...
@overload
def all[A, E](results: Iterable[AsyncResult[A, E]], /) -> AsyncResult[list[A], E]: ...
@overload
def all(results: Mapping[str, object], /) -> AsyncResult[dict[str, Any], Any]: ...
@overload
def all(results: Iterable[object], /) -> AsyncResult[list[Any], Any]: ...
def all(results: Iterable[object] | Mapping[str, object], /) -> AsyncResult[Any, Any]:
    """One result of many (a list, or a mapping by key); values that are
    not results are kept as they are. The first failure or initial result
    wins; a failure keeps the combined previous successes when every input
    has a value."""
    as_dict = isinstance(results, Mapping)
    entries: builtins.list[tuple[object, object]] = (
        builtins.list(cast("Mapping[str, object]", results).items())
        if as_dict
        else builtins.list(enumerate(results))
    )
    successes: dict[object, object] = {}
    any_waiting = False
    for key, result in entries:
        if not is_async_result(result):
            successes[key] = result
            continue
        if isinstance(result, Failure):
            return Failure(result.cause, _combined_previous(entries, as_dict), result.waiting)
        if isinstance(result, Initial):
            return result
        successes[key] = result.value
        any_waiting = any_waiting or result.waiting
    return Success(_shape(successes, as_dict), any_waiting)


def _shape(values: dict[object, object], as_dict: bool) -> object:
    return values if as_dict else builtins.list(values.values())


def _combined_previous(
    entries: builtins.list[tuple[object, object]], as_dict: bool
) -> Option[Success[object]]:
    values: dict[object, object] = {}
    for key, entry in entries:
        if not is_async_result(entry):
            values[key] = entry
            continue
        found = value(entry)
        if found is None:
            return None
        values[key] = found.value
    return Some(Success(_shape(values, as_dict)))


# ---------------------------------------------------------------- builder


Out_co = TypeVar("Out_co", covariant=True)


class Builder(Generic[Out_co, A_co, E_co]):
    """Renders a result case by case: each ``on_*`` handles the cases it
    matches unless an earlier one already did (Effect's ``builder``). The
    output type grows with each handler; Python cannot remove handled
    cases from the type, so ``exhaustive`` is ``render`` (an unhandled
    failure raises its squashed cause, as Effect's does)."""

    __slots__ = ("_output", "result")

    def __init__(self, result: AsyncResult[A_co, E_co]) -> None:
        self.result = result
        self._output: Option[Any] = None

    def _when(
        self,
        matches: Callable[[AsyncResult[Any, Any]], bool],
        f: Callable[[Any], Option[object]],
    ) -> Any:
        if self._output is None and matches(self.result):
            self._output = f(self.result)
        return self

    def on_waiting[B](
        self, f: Callable[[AsyncResult[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        return self._when(lambda r: r.waiting, lambda r: Some(f(r)))

    def on_initial_or_waiting[B](
        self, f: Callable[[AsyncResult[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        return self._when(lambda r: isinstance(r, Initial) or r.waiting, lambda r: Some(f(r)))

    def on_initial[B](
        self, f: Callable[[Initial[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        return self._when(is_initial, lambda r: Some(f(r)))

    def on_success[B](
        self, f: Callable[[A_co, Success[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        return self._when(is_success, lambda r: Some(f(r.value, r)))

    def on_failure[B](
        self, f: Callable[[Cause[E_co], Failure[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        return self._when(is_failure, lambda r: Some(f(r.cause, r)))

    def on_error[B](
        self, f: Callable[[E_co, Failure[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        return self.on_error_if(lambda _: True, f)

    def on_error_if[B](
        self, predicate: Callable[[E_co], bool], f: Callable[[E_co, Failure[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        def handle(result: Failure[A_co, E_co]) -> Option[object]:
            found = error(result)
            if found is None or not predicate(found.value):
                return None
            return Some(f(found.value, result))

        return self._when(is_failure, handle)

    def on_error_tag[T, B](
        self, tag: type[T] | tuple[type[T], ...], f: Callable[[T, Failure[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        """Handle a typed error that is an instance of ``tag`` (pyfect's
        tags are classes)."""

        def handle(result: Failure[A_co, E_co]) -> Option[object]:
            found = error(result)
            if found is None or not isinstance(found.value, tag):
                return None
            return Some(f(found.value, result))

        return self._when(is_failure, handle)

    def on_defect[B](
        self, f: Callable[[BaseException, Failure[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        def handle(result: Failure[A_co, E_co]) -> Option[object]:
            defect = result.cause.find_defect()
            return None if defect is None else Some(f(defect, result))

        return self._when(is_failure, handle)

    def on_interrupt[B](
        self, f: Callable[[frozenset[int], Failure[A_co, E_co]], B]
    ) -> Builder[Out_co | B, A_co, E_co]:
        def handle(result: Failure[A_co, E_co]) -> Option[object]:
            interruptors = result.cause.filter_interruptors()
            return None if interruptors is None else Some(f(interruptors, result))

        return self._when(is_failure, handle)

    def or_else[B](self, or_else: Callable[[], B]) -> Out_co | B:
        return or_else() if self._output is None else self._output.value

    def or_none(self) -> Out_co | None:
        return None if self._output is None else self._output.value

    def render(self) -> Out_co | None:
        if self._output is not None:
            return self._output.value
        if isinstance(self.result, Failure):
            raise self.result.cause.squash()
        return None

    def exhaustive(self) -> Out_co:
        """``render``, for a builder that handles every case."""
        return self.render()  # pyright: ignore[reportReturnType]


def builder[A, E](self: AsyncResult[A, E]) -> Builder[Never, A, E]:
    """A ``Builder`` rendering ``self``."""
    return Builder(self)


__all__ = [
    "AsyncResult",
    "Builder",
    "Failure",
    "Initial",
    "Success",
    "all",
    "builder",
    "cause",
    "error",
    "fail",
    "fail_with_previous",
    "failure",
    "failure_with_previous",
    "flat_map",
    "from_exit",
    "from_exit_with_previous",
    "get_or_else",
    "get_or_raise",
    "initial",
    "is_async_result",
    "is_failure",
    "is_initial",
    "is_interrupted",
    "is_not_initial",
    "is_success",
    "is_waiting",
    "map",
    "match",
    "match_with_error",
    "match_with_waiting",
    "replace_previous",
    "success",
    "to_exit",
    "touch",
    "value",
    "waiting",
    "waiting_from",
]
publish(globals())
