"""Typed errors.

Subclass ``TaggedError`` (usually as a ``@dataclass(eq=False)``; plain
``@dataclass`` works too, but pyright then thinks it unhashable) for
domain errors. An
instance is yieldable: ``yield from NotFound(key)`` fails the surrounding
generator and adds ``NotFound`` to its error channel. Write
``return (yield from NotFound(key))`` so the type checker knows the code
after it is unreachable.

The class is the tag: ``catch_tag(NotFound, ...)`` matches by
``isinstance``, so catching a base class catches its subclasses, and the
types agree.

Like Effect's ``Data.TaggedError``, errors compare and hash structurally
(same class, equal fields or ``args``), a ``message`` field is the string
form, a ``cause`` field holding an exception becomes ``__cause__``, and
``exit_code`` is the process status ``run_main`` exits with when the error
ends the program.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import builtins
from collections.abc import Callable, Generator
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, ClassVar, Never, Self, TypeIs, overload

from pyfect._core import Effect, _FailCause
from pyfect.cause import Cause, Fail, Interrupt, Reason, fail, from_reasons
from pyfect.duration import Seconds, format_duration
from pyfect.result import Err, Ok, Result


class TaggedError(Exception):
    exit_code: ClassVar[int] = 1

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Put the structural methods in the subclass's own namespace: then
        # ``@dataclass`` treats them as explicit and neither replaces
        # ``__eq__`` nor sets ``__hash__ = None``. A class that defines (or
        # inherits) its own ``__eq__`` or ``__hash__`` keeps it.
        if cls.__eq__ is TaggedError.__eq__ and cls.__hash__ is TaggedError.__hash__:
            type.__setattr__(cls, "__eq__", TaggedError.__eq__)
            type.__setattr__(cls, "__hash__", TaggedError.__hash__)

    def _structure(self) -> tuple[object, ...]:
        if is_dataclass(self):
            return tuple(getattr(self, f.name) for f in fields(self) if f.compare)
        return self.args

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TaggedError) or type(other) is not type(self):
            return NotImplemented
        return self._structure() == other._structure()

    def __hash__(self) -> int:
        return hash((type(self), self._structure()))

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name != "cause":
            return
        if isinstance(value, BaseException):
            self.__cause__ = value
        elif value is None and self.__cause__ is not None:
            # Assigning ``__cause__`` also sets ``__suppress_context__``; an
            # absent cause must not hide the implicit ``__context__``.
            self.__cause__ = None
            self.__suppress_context__ = False

    def __iter__(self) -> Generator[Effect[Never, Self, Never], Any, Never]:
        yield _FailCause(fail(self))
        raise AssertionError("unreachable: a failed effect never resumes")

    def __str__(self) -> str:
        message = getattr(self, "message", None)
        if isinstance(message, str):
            return message
        if is_dataclass(self):
            return ", ".join(f"{f.name}={getattr(self, f.name)!r}" for f in fields(self))
        return super().__str__()

    def __reduce__(self) -> str | tuple[Any, ...]:
        # A dataclass error's ``args`` need not match its fields, so copy and
        # pickle rebuild it from the fields instead.
        if is_dataclass(self):
            init = {f.name: getattr(self, f.name) for f in fields(self) if f.init}
            return (_rebuild, (type(self), init), self.__dict__)
        return super().__reduce__()


def _rebuild[T](cls: Callable[..., T], init: dict[str, Any]) -> T:
    return cls(**init)


@dataclass
class TimeoutException(TaggedError, builtins.TimeoutError):
    """An effect ran longer than its ``timeout`` of ``duration``."""

    duration: Seconds

    def __str__(self) -> str:
        return f"Operation timed out after '{format_duration(self.duration)}'"


class NoSuchElementException(TaggedError, LookupError):
    """An expected value was missing."""


class IllegalArgumentError(TaggedError, ValueError):
    """An argument outside what an operation accepts, such as an unknown
    time zone name."""


class Done[L = None](TaggedError):
    """A producer finished normally: no more items will come. ``value`` is
    what it leaves over (Effect's ``Cause.Done(value)``); a bare ``Done``
    means ``Done[None]``.

    A queue that can be ended says so in its error type,
    ``Queue[int, Done]``; its takers fail with ``Done()`` once it drains."""

    __match_args__ = ("value",)

    @overload
    def __init__(self: Done[None]) -> None: ...
    @overload
    def __init__(self, value: L) -> None: ...
    def __init__(self, value: object = None) -> None:
        super().__init__(value)

    @property
    def value(self) -> L:
        return self.args[0]

    def __repr__(self) -> str:
        return "Done()" if self.value is None else f"Done({self.value!r})"

    __str__ = __repr__


def filter_done[E](cause: Cause[E]) -> Result[Done[Any], Cause[E]]:
    """``Ok(done)`` if ``cause`` holds a ``Done`` failure and nothing else but
    interruptions; otherwise ``Err`` of the cause without its ``Done``
    failures (Effect's ``Pull.filterDone``)."""
    dones = [r.error for r in cause.reasons if _is_done(r)]
    if not dones:
        return Err(cause)
    if all(_is_done(r) or isinstance(r, Interrupt) for r in cause.reasons):
        return Ok(dones[0])
    return Err(from_reasons(r for r in cause.reasons if not _is_done(r)))


def _is_done(reason: Reason[object]) -> TypeIs[Fail[Done[Any]]]:
    return isinstance(reason, Fail) and isinstance(reason.error, Done)


class ExceededCapacityError(TaggedError):
    """A bounded structure was asked to hold more than its capacity."""


@dataclass(eq=False)
class UnknownError(TaggedError):
    """An exception raised by code given to ``try_`` without a ``catch``.
    ``cause`` is that exception, and also the error's ``__cause__``."""

    cause: Exception
    message: str | None = None

    def __str__(self) -> str:
        return self.message if self.message is not None else str(self.cause)
