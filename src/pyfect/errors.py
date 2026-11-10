"""Typed errors.

Subclass ``TaggedError`` for domain errors. One with fields must be a
``@dataclass(eq=False)`` (plain ``@dataclass`` works too, but pyright then
thinks it unhashable); constructing one whose fields nothing sets raises
``TypeError``. An
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
ends the program. ``error_reported`` and the ``report_*`` attributes tune
how ``run_main`` and the error reporters (``pyfect.error_reporter``) treat
it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import builtins
import re
import sys
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final, Never, Self, TypeIs, get_origin, overload

from pyfect._core import Effect, _FailCause
from pyfect.cause import Cause, Fail, Interrupt, Reason, fail, from_reasons
from pyfect.duration import Duration
from pyfect.result import Err, Ok, Result

if TYPE_CHECKING:
    from pyfect.logger import Severity


def with_cause(message: str, cause: object) -> str:
    """``message`` and why, for ``str()``: what a log line shows, while ``.message`` stays
    Effect's text (docs/PARITY.md). A cause whose own message this one repeats replaces it,
    so a wrapper around its reason says it once."""
    if cause is None:
        return message
    if not isinstance(cause, BaseException):
        return f"{message}: {cause!r}"
    detail = str(cause)
    if detail.startswith(message):
        return detail
    said = getattr(cause, "message", None)
    if isinstance(said, str) and said and said in message:
        return message.replace(said, detail, 1)
    if detail and detail in message:
        return message
    return f"{message}: {type(cause).__name__}{f': {detail}' if detail else ''}"


def _why(error: BaseException) -> object:
    """What caused ``error``: a ``reason`` that is an error (it tells its own cause), or else
    its ``__cause__`` or ``cause``."""
    reason = getattr(error, "reason", None)
    if isinstance(reason, BaseException):
        return reason
    return error.__cause__ if error.__cause__ is not None else getattr(error, "cause", None)


class TaggedError(Exception):
    exit_code: ClassVar[int] = 1
    error_reported: bool = True
    """``False``: ``run_main`` does not log this error when it ends the
    program (Effect's ``Runtime.errorReported``)."""
    report_ignored: bool = False
    """``True``: error reporters skip this error."""
    report_severity: Severity | None = None
    """The severity error reporters give it (``None``: ``INFO``)."""
    report_attributes: Mapping[str, object] = MappingProxyType({})
    """Extra metadata for error reporters."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Put the structural methods in the subclass's own namespace: then
        # ``@dataclass`` treats them as explicit and neither replaces
        # ``__eq__`` nor sets ``__hash__ = None``. A class that defines (or
        # inherits) its own ``__eq__`` or ``__hash__`` keeps it.
        if cls.__eq__ is TaggedError.__eq__ and cls.__hash__ is TaggedError.__hash__:
            type.__setattr__(cls, "__eq__", TaggedError.__eq__)
            type.__setattr__(cls, "__hash__", TaggedError.__hash__)
        # The bases are finished, so fields no constructor sets fail here; the
        # class itself may still get ``@dataclass``, so it is checked when
        # first constructed (``_check_fields_then_new``).
        _require_dataclass_fields(cls, below=cls)
        if "__init__" not in cls.__dict__ and _own_fields(cls):
            type.__setattr__(cls, "__new__", staticmethod(_check_fields_then_new))

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
            return with_cause(message, _why(self))
        if is_dataclass(self):
            return ", ".join(f"{f.name}={getattr(self, f.name)!r}" for f in fields(self))
        return super().__str__()

    def __reduce__(self) -> str | tuple[Any, ...]:
        # A dataclass error's ``args`` need not match its fields, so copy and
        # pickle rebuild it from the fields instead. The state is the rest
        # (notes, ...): the constructor sets the fields, which may be frozen.
        if is_dataclass(self):
            init = {f.name: getattr(self, f.name) for f in fields(self) if f.init}
            state = {k: v for k, v in self.__dict__.items() if k not in init}
            return (_rebuild, (type(self), init), state)
        return super().__reduce__()


def _own_fields(cls: type) -> list[str]:
    """The instance fields ``cls`` itself annotates: not ``ClassVar`` /
    ``Final``, dunders or ``TaggedError``'s own attributes."""
    if sys.version_info >= (3, 14):
        import annotationlib

        annotations = annotationlib.get_annotations(cls, format=annotationlib.Format.FORWARDREF)
    else:
        import inspect

        annotations = inspect.get_annotations(cls)
    return [
        name
        for name, annotation in annotations.items()
        if not name.startswith("__")
        and name not in TaggedError.__annotations__
        and not _CLASS_LEVEL.match(annotation if isinstance(annotation, str) else repr(annotation))
        and get_origin(annotation) not in (ClassVar, Final)
        and annotation not in (ClassVar, Final)
    ]


_CLASS_LEVEL = re.compile(r"^(?:typing\.|t\.)?(?:ClassVar|Final)\b")


def _require_dataclass_fields(cls: type, *, below: type | None = None) -> None:
    """Raise ``TypeError`` if a class between ``cls`` and ``TaggedError``
    (above ``below``, when given) annotates fields that no constructor sets:
    it is not a dataclass and neither it nor a subclass on the way to ``cls``
    writes ``__init__``."""
    handwritten_init = False
    for klass in cls.__mro__:
        if klass is TaggedError:
            return
        own_dataclass = "__dataclass_fields__" in klass.__dict__
        if "__init__" in klass.__dict__ and not own_dataclass:
            handwritten_init = True
        if own_dataclass or handwritten_init or klass is below:
            continue
        names = _own_fields(klass)
        if names:
            raise TypeError(
                f"{klass.__qualname__} declares fields ({', '.join(names)}) but is not a "
                "dataclass, so nothing sets them; decorate it with @dataclass (or "
                "@dataclass(eq=False)), or subclass S.TaggedError, which needs no decorator"
            )


def _check_fields_then_new(cls: type[TaggedError], *args: Any, **_kwargs: Any) -> Any:
    """The ``__new__`` of a class with fields and no ``__init__`` of its own:
    the first time a class is built, check that ``@dataclass`` set them up.
    The inherited ``__new__`` gets the positional arguments only, as
    ``BaseException.__new__`` keeps them (``OSError``'s refuses keywords
    once a class overrides ``__new__``); ``__init__`` takes them all."""
    new = cls.__dict__.get("_TaggedError__new")
    if new is None:
        _require_dataclass_fields(cls)
        new = next(
            own
            for klass in cls.__mro__
            if (own := klass.__dict__.get("__new__")) is not None and not _is_hook(own)
        )
        type.__setattr__(cls, "_TaggedError__new", new)
    return new(cls, *args)


def _is_hook(value: object) -> bool:
    return isinstance(value, staticmethod) and value.__func__ is _check_fields_then_new


def _rebuild[T](cls: Callable[..., T], init: dict[str, Any]) -> T:
    return cls(**init)


@dataclass
class TimeoutException(TaggedError, builtins.TimeoutError):
    """An effect ran longer than its ``timeout`` of ``duration``."""

    duration: Duration

    def __str__(self) -> str:
        return f"Operation timed out after '{self.duration.format()}'"


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


@dataclass(eq=False)
class AsyncFiberError(TaggedError):
    """``run_sync`` ran an effect that did not finish synchronously. The
    fiber is left where it stopped."""

    fiber: object
    message: str = "An asynchronous Effect was executed with Effect.runSync"


class ExceededCapacityError(TaggedError):
    """A bounded structure was asked to hold more than its capacity."""


@dataclass(eq=False)
class UnknownError(TaggedError):
    """An exception raised by code given to ``try_`` without a ``catch``.
    ``cause`` is that exception, and also the error's ``__cause__``."""

    cause: Exception
    message: str | None = None

    def __str__(self) -> str:
        return str(self.cause) if self.message is None else with_cause(self.message, self.cause)


__all__ = [
    "AsyncFiberError",
    "Done",
    "ExceededCapacityError",
    "IllegalArgumentError",
    "NoSuchElementException",
    "TaggedError",
    "TimeoutException",
    "UnknownError",
    "filter_done",
    "with_cause",
]
