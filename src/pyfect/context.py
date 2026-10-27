"""Services: tags, references, and the context that holds them.

A tag names a service. Its identity is the class, and its type parameter
is the service's shape, so two tags can share a shape and stay distinct::

    class Database(Protocol):
        def find(self, key: str) -> str | None: ...

    class Primary(Tag[Database]): ...
    class Replica(Tag[Database]): ...

    def program():
        db = yield from Primary()   # Database; adds Primary to R

Calling a tag class does not construct anything: it gives the effect that
reads the service from the running fiber's context.

A ``Reference`` is a tag with a default value. Effects that read a
reference do not need it provided, so it never appears in ``R``::

    class LogLevel(Reference[int]):
        @classmethod
        def default(cls) -> int:
            return 20
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Never, Protocol, Self, TypeVar, final

from pyfect._core import Effect, Step
from pyfect.cause import Cause, Die
from pyfect.exit import Failure, Success

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

S_inv = TypeVar("S_inv")
T_co = TypeVar("T_co", covariant=True)
# A bare ``Context`` is ``Context[Any]``: the runtime's own contexts are
# untyped; contexts handed to users and taken from them carry their tags.
R_contra = TypeVar("R_contra", contravariant=True, default=Any)


class MissingServiceError(Exception):
    """A defect: an effect read a service nobody provided. The types rule
    this out unless an ``Any`` or a cast got in the way."""


@final
class ServiceEffect(Effect[S_inv, Never, T_co]):
    """Reads a service. Invariant in the shape so ``Layer.succeed(Tag,
    value)`` checks ``value`` against the shape exactly."""

    __slots__ = ("tag",)

    def __init__(self, tag: type[Tag[Any]]) -> None:
        self.tag = tag

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        found, value = fiber._context.lookup(self.tag)
        if found:
            return Success(value)
        return Failure(Cause((Die(MissingServiceError(_missing(self.tag, fiber._context))),)))


def _missing(tag: type[Tag[Any]], ctx: Context) -> str:
    available = ", ".join(t.key for t in ctx.tags()) or "none"
    return f"Service {tag.key} was not provided (available: {available})"


class Tag[S]:
    """A service identifier with shape ``S``. Subclass it; never
    instantiate it."""

    key: ClassVar[str]

    def __init_subclass__(cls, *, key: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.key = key or f"{cls.__module__}.{cls.__qualname__}"

    def __new__(cls) -> ServiceEffect[S, Self]:
        return ServiceEffect(cls)


class Reference[S](Tag[S]):
    """A tag with a default value. Override ``default``."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("default") is None:
            raise TypeError(f"Reference {cls.__qualname__} must define a 'default' classmethod")

    def __new__(cls) -> ServiceEffect[S, Never]:
        return ServiceEffect(cls)

    @classmethod
    def default(cls) -> S:
        raise NotImplementedError


class TagLike[S, T](Protocol):
    """Any tag class: calling it gives the effect that reads the service.
    Used in signatures to recover both the shape ``S`` and the tag ``T``."""

    def __call__(self) -> ServiceEffect[S, T]: ...


@final
class Context(Generic[R_contra]):
    """An immutable map from tag to service. ``Context[R]`` holds the
    services of the tags ``R``, so a context with more services stands in
    for one with fewer (``Context[A | B]`` is a ``Context[A]``)."""

    __slots__ = ("_services",)

    def __init__(self, services: Mapping[type[Tag[Any]], Any] | None = None) -> None:
        self._services: dict[type[Tag[Any]], Any] = dict(services or {})

    @staticmethod
    def empty() -> Context[Never]:
        return _EMPTY

    @staticmethod
    def make[S, T](tag: TagLike[S, T], service: S) -> Context[T]:
        """A context holding one service."""
        return Context({tag_class(tag): service})

    def lookup(self, tag: type[Tag[Any]]) -> tuple[bool, Any]:
        if tag in self._services:
            return True, self._services[tag]
        if issubclass(tag, Reference):
            return True, _default_of(tag)
        return False, None

    def add[S, T](self, tag: TagLike[S, T], service: S) -> Context[R_contra | T]:
        return Context({**self._services, tag_class(tag): service})

    def merge[R2](self, other: Context[R2]) -> Context[R_contra | R2]:
        """Both contexts' services; ``other`` wins where both have a tag."""
        return Context({**self._services, **other._services})

    def tags(self) -> tuple[type[Tag[Any]], ...]:
        return tuple(self._services)


_EMPTY: Context[Never] = Context()
_defaults: dict[type[Reference[Any]], Any] = {}


def _default_of(tag: type[Reference[Any]]) -> Any:
    """Each reference's default is built once, on first use."""
    if tag not in _defaults:
        _defaults[tag] = tag.default()
    return _defaults[tag]


def tag_class[S, T](tag: TagLike[S, T]) -> type[Tag[S]]:
    """The class behind a ``TagLike``. Every ``TagLike`` is a tag class;
    the protocol only exists so signatures can name its shape and tag."""
    if isinstance(tag, type) and issubclass(tag, Tag):
        return tag  # pyright: ignore[reportUnknownVariableType]
    raise TypeError(f"{tag!r} is not a Tag class")
