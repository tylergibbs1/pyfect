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

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Never,
    Protocol,
    Self,
    TypeVar,
    cast,
    final,
    overload,
)

from pyfect._core import Effect, Step
from pyfect.cause import Cause, Die
from pyfect.exit import Failure, Success
from pyfect.option import Option, Some

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


def _is_runtime_setting(tag: type[Tag[Any]]) -> bool:
    """A reference (it has a default, so it is never missing) or a tag the
    runtime keeps for itself: noise in a missing-service message."""
    module = tag.__module__.split(".")
    return issubclass(tag, Reference) or (
        module[0] == "pyfect" and any(part.startswith("_") for part in module)
    )


def _missing(tag: type[Tag[Any]], ctx: Context) -> str:
    provided = [t.key for t in ctx.tags() if not _is_runtime_setting(t)]
    available = ", ".join(provided) or "none"
    return f"Service {tag.key} was not provided (available: {available})"


class Tag[S]:
    """A service identifier with shape ``S``. Subclass it; never
    instantiate it."""

    key: ClassVar[str]

    def __init_subclass__(cls, *, key: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.key = key or f"{cls.__module__}.{cls.__qualname__}"

    def __new__(cls) -> ServiceEffect[S, Self]:
        _require_subclass(cls)
        return ServiceEffect(cls)


class Reference[S](Tag[S]):
    """A tag with a default value. Override ``default``."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("default") is None:
            raise TypeError(f"Reference {cls.__qualname__} must define a 'default' classmethod")

    def __new__(cls) -> ServiceEffect[S, Never]:
        _require_subclass(cls)
        return ServiceEffect(cls)

    @classmethod
    def default(cls) -> S:
        raise NotImplementedError


def _require_subclass(cls: type[Tag[Any]]) -> None:
    if cls is Tag or cls is Reference:
        raise TypeError(
            f"{cls.__name__} is a base class: subclass it (class Db({cls.__name__}[str]): ...) "
            "and call the subclass"
        )


class TagLike[S, T](Protocol):
    """Any tag class: calling it gives the effect that reads the service.
    Used in signatures to recover both the shape ``S`` and the tag ``T``."""

    def __call__(self) -> ServiceEffect[S, T]: ...


@final
class Context(Generic[R_contra]):
    """An immutable map from tag to service. ``Context[R]`` holds the
    services of the tags ``R``, so a context with more services stands in
    for one with fewer (``Context[A | B]`` is a ``Context[A]``).

    ``Context(mapping)`` is Effect's ``makeUnsafe``: an untyped context.
    Build typed ones with ``make`` and ``add``."""

    __slots__ = ("_services",)

    def __init__(self, services: Mapping[type[Tag[Any]], Any] | None = None) -> None:
        self._services: dict[type[Tag[Any]], Any] = dict(services or {})

    if TYPE_CHECKING:
        # The tags seen covariantly, for ``omit`` (see ``_Holding``).
        @property
        def _held(self) -> type[R_contra]: ...  # pyright: ignore[reportGeneralTypeIssues]

    @staticmethod
    def empty() -> Context[Never]:
        return _EMPTY

    @staticmethod
    def make[S, T](tag: TagLike[S, T], service: S) -> Context[T]:
        """A context holding one service."""
        return Context({tag_class(tag): service})

    @overload
    @staticmethod
    def merge_all[X1, X2](c1: Context[X1], c2: Context[X2], /) -> Context[X1 | X2]: ...
    @overload
    @staticmethod
    def merge_all[X1, X2, X3](
        c1: Context[X1], c2: Context[X2], c3: Context[X3], /
    ) -> Context[X1 | X2 | X3]: ...
    @overload
    @staticmethod
    def merge_all[X1, X2, X3, X4](
        c1: Context[X1], c2: Context[X2], c3: Context[X3], c4: Context[X4], /
    ) -> Context[X1 | X2 | X3 | X4]: ...
    @overload
    @staticmethod
    def merge_all(*contexts: Context[Any]) -> Context[Any]: ...
    @staticmethod
    def merge_all(*contexts: Context[Any]) -> Context[Any]:
        """Every context's services; later contexts win where several have
        a tag."""
        merged: dict[type[Tag[Any]], Any] = {}
        for ctx in contexts:
            merged.update(ctx._services)
        return Context(merged)

    @staticmethod
    def pick[T = Never](*tags: TagLike[Any, T]) -> _Pick[T]:
        """Keep only ``tags``' services, in this context's order. Use with
        ``.pipe``; the context must hold every tag."""
        return _Pick(frozenset(map(tag_class, tags)))

    @staticmethod
    def omit[T = Never](*tags: TagLike[Any, T]) -> _Omit[T]:
        """Drop ``tags``' services and remove them from the type. Use with
        ``.pipe``."""
        return _Omit(frozenset(map(tag_class, tags)))

    @staticmethod
    def add_or_omit[S, T](tag: TagLike[S, T], service: Option[S]) -> _Omit[T]:
        """``add`` for ``Some(service)``, ``omit`` for ``None``. Either way the
        tag leaves the type. Use with ``.pipe``."""
        cls = tag_class(tag)
        if service is None:
            return _Omit(frozenset((cls,)))
        return _Omit(frozenset(), (cls, service.value))

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def lookup(self, tag: type[Tag[Any]]) -> tuple[bool, Any]:
        if tag in self._services:
            return True, self._services[tag]
        if issubclass(tag, Reference):
            return True, _default_of(tag)
        return False, None

    def get[S, T](self: Context[T], tag: TagLike[S, T]) -> S:
        """The service of ``tag``, which the context's type must hold (a
        reference falls back to its default)."""
        return self.get_unsafe(tag)

    def get_unsafe[S, T](self, tag: TagLike[S, T]) -> S:
        """``get`` without the type check: raises ``MissingServiceError`` if
        the service is absent."""
        found, value = self.lookup(tag_class(tag))
        if not found:
            raise MissingServiceError(_missing(tag_class(tag), self))
        return value

    def get_option[S, T](self, tag: TagLike[S, T]) -> Option[S]:
        """``Some(service)``, or ``None`` if absent. A reference is never
        absent: it falls back to its default."""
        found, value = self.lookup(tag_class(tag))
        return Some(value) if found else None

    def get_or_else[S, T, B](self, tag: TagLike[S, T], or_else: Callable[[], B]) -> S | B:
        """The service, or ``or_else()`` if absent."""
        found, value = self.lookup(tag_class(tag))
        return value if found else or_else()

    def add[S, T](self, tag: TagLike[S, T], service: S) -> Context[R_contra | T]:
        """A copy with ``service`` added. Replacing a tag keeps its place."""
        return Context({**self._services, tag_class(tag): service})

    def merge[R2](self, other: Context[R2]) -> Context[R_contra | R2]:
        """Both contexts' services; ``other`` wins where both have a tag.
        Merging with an empty context gives back the other one."""
        if not other._services:
            return cast("Context[Any]", self)
        if not self._services:
            return cast("Context[Any]", other)
        return Context({**self._services, **other._services})

    def tags(self) -> tuple[type[Tag[Any]], ...]:
        return tuple(self._services)

    @property
    def map_unsafe(self) -> Mapping[type[Tag[Any]], Any]:
        """The services by tag, in insertion order, untyped (Effect's
        ``mapUnsafe``)."""
        return MappingProxyType(self._services)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Context) and self._services == other._services

    __hash__ = None  # pyright: ignore[reportAssignmentType]

    def __repr__(self) -> str:
        entries = ", ".join(f"{tag.key}: {value!r}" for tag, value in self._services.items())
        return f"Context({{{entries}}})"


@final
class _Pick[T]:
    __slots__ = ("keep",)

    def __init__(self, keep: frozenset[type[Tag[Any]]]) -> None:
        self.keep = keep

    def __call__(self, ctx: Context[T]) -> Context[T]:
        return Context({t: s for t, s in ctx._services.items() if t in self.keep})


class _Holding(Protocol[T_co]):
    """A context holding the tags ``T``, matched covariantly. Pyright
    subtracts tags from a union only when solving a covariant position;
    matching ``Context[T | R]`` (contravariant) may keep removed tags in ``R``."""

    @property
    def _held(self) -> type[T_co]: ...


@final
class _Omit[T]:
    __slots__ = ("added", "drop")

    def __init__(
        self, drop: frozenset[type[Tag[Any]]], added: tuple[type[Tag[Any]], Any] | None = None
    ) -> None:
        self.drop = drop
        self.added = added

    @overload
    def __call__(self, ctx: _Holding[T]) -> Context[Never]: ...
    @overload
    def __call__[R](self, ctx: _Holding[T | R]) -> Context[R]: ...
    def __call__(self, ctx: Any) -> Context[Any]:
        kept = {t: s for t, s in ctx._services.items() if t not in self.drop}
        if self.added is not None:
            kept[self.added[0]] = self.added[1]
        return Context(kept)


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


__all__ = [
    "Context",
    "MissingServiceError",
    "Reference",
    "ServiceEffect",
    "Tag",
    "TagLike",
    "tag_class",
]
