"""Groups of HTTP API endpoints (Effect's ``HttpApiGroup``).

A group is a class whose attributes are its endpoints::

    class Users(HttpApiGroup, identifier="users"):
        get_user = endpoint.get("getUser", "/users/:id", params=..., success=User)

    class Admin(HttpApiGroup[Authorization], identifier="admin"):
        ...  # every endpoint is wrapped by the Authorization middleware

A group is also the tag of its handlers: ``HttpApiBuilder.group(api, Users,
...)`` is a ``Layer[Users]``. Read on a client's group (``client[Users]``)
an endpoint attribute is its client method. ``top_level=True`` puts a
group's methods on the client itself in OpenAPI-style tools; a Python
client always reads them through the group.

``prefix``, ``add``, ``annotate`` and the other class methods give a new
group class (a subclass, the tag of the same handlers).
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from typing import Any, ClassVar, Generic, Never, Self, TypeVar, Union, cast, get_args, get_origin

from pyfect.context import Context, Tag, TagLike
from pyfect.http_api.endpoint import AnyEndpoint, HttpApiEndpoint
from pyfect.http_api.middleware import AnyMiddleware, HttpApiMiddleware

M_co = TypeVar("M_co", covariant=True, default=Never)
MT_co = TypeVar("MT_co", covariant=True, default=M_co)

_KEY_PREFIX = "effect/http-api/HttpApiGroup/"


class GroupService:
    """What a group's layer provides: its routes, made from its handlers."""

    __slots__ = ("handlers", "routes")

    def __init__(self, routes: tuple[Any, ...], handlers: Mapping[str, Any]) -> None:
        self.routes = routes
        self.handlers = handlers


class HttpApiGroup(Tag[GroupService], Generic[M_co, MT_co]):
    """A group of endpoints wrapped by the middleware ``M`` (a middleware
    class, or a union of them). Leave out ``MT``: it repeats ``M`` so that
    the builder can read both the middleware and what it provides."""

    identifier: ClassVar[str]
    top_level: ClassVar[bool]
    endpoints: ClassVar[Mapping[str, AnyEndpoint]]
    annotations: ClassVar[Context[Any]]
    origin: ClassVar[type[HttpApiGroup[Any]]]
    """The class whose handlers this group's are: itself, or the group it
    was derived from with ``prefix``, ``add``, ..."""

    def __init_subclass__(
        cls,
        *,
        identifier: str | None = None,
        top_level: bool = False,
        annotations: Context[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if identifier is None:
            # A derived group: the methods below set its endpoints.
            super().__init_subclass__(key=cls.key, **kwargs)
            return
        super().__init_subclass__(key=_KEY_PREFIX + identifier, **kwargs)
        cls.identifier = identifier
        cls.top_level = top_level
        cls.annotations = annotations if annotations is not None else Context.empty()
        cls.origin = cls
        endpoints: dict[str, AnyEndpoint] = {}
        for base in reversed(cls.__mro__[1:]):
            endpoints |= getattr(base, "endpoints", {})
        for value in vars(cls).values():
            if isinstance(value, HttpApiEndpoint):
                endpoint = cast("AnyEndpoint", value)
                endpoints[endpoint.identifier] = endpoint
        cls.endpoints = _wrapped(cls, endpoints)

    def method(self, identifier: str, /) -> Any:
        """On a client's group, the client method of the endpoint
        ``identifier``: for endpoints added with ``add`` rather than
        declared as attributes (which type their methods)."""
        methods: Mapping[str, Any] | None = getattr(self, "_http_api_client", None)
        if methods is None:
            raise TypeError("method() reads a client's group (client[Group])")
        return methods[identifier]

    @classmethod
    def _derive(
        cls,
        *,
        endpoints: Mapping[str, AnyEndpoint] | None = None,
        annotations: Context[Any] | None = None,
    ) -> type[Self]:
        derived = types.new_class(cls.__name__, (cls,))
        derived.__qualname__ = cls.__qualname__
        derived.__module__ = cls.__module__
        derived.endpoints = cls.endpoints if endpoints is None else _wrapped(derived, endpoints)
        derived.annotations = cls.annotations if annotations is None else annotations
        return derived

    @classmethod
    def add(cls, *endpoints: AnyEndpoint) -> type[Self]:
        """This group with more endpoints (read them from ``endpoints``;
        declare them as attributes to type a client's methods)."""
        added = dict(cls.endpoints)
        for endpoint in endpoints:
            added[endpoint.identifier] = endpoint
        return cls._derive(endpoints=added)

    @classmethod
    def prefix(cls, prefix: str) -> type[Self]:
        """This group with every endpoint under ``prefix``."""
        return cls._derive(endpoints={k: e.prefix(prefix) for k, e in cls.endpoints.items()})

    @classmethod
    def middleware(cls, middleware: AnyMiddleware) -> type[Self]:
        """This group with every endpoint wrapped by ``middleware``. Only the
        endpoints' run time changes; to type the handlers and clients,
        declare it as the group's type argument."""
        return cls._derive(
            endpoints={k: e.middleware(middleware) for k, e in cls.endpoints.items()}
        )

    @classmethod
    def annotate[S, T](cls, tag: TagLike[S, T], value: S) -> type[Self]:
        return cls._derive(annotations=cls.annotations.add(tag, value))

    @classmethod
    def annotate_merge(cls, annotations: Context[Any]) -> type[Self]:
        return cls._derive(annotations=cls.annotations.merge(annotations))

    @classmethod
    def annotate_endpoints[S, T](cls, tag: TagLike[S, T], value: S) -> type[Self]:
        """This group with an annotation on every endpoint."""
        return cls._derive(endpoints={k: e.annotate(tag, value) for k, e in cls.endpoints.items()})

    @classmethod
    def annotate_endpoints_merge(cls, annotations: Context[Any]) -> type[Self]:
        return cls._derive(
            endpoints={k: e.annotate_merge(annotations) for k, e in cls.endpoints.items()}
        )

    @staticmethod
    def make(identifier: str, *, top_level: bool = False) -> type[HttpApiGroup[Never]]:
        """An empty group class (Effect's ``HttpApiGroup.make``); add its
        endpoints with ``add``."""
        return types.new_class(
            identifier,
            (HttpApiGroup,),
            {"identifier": identifier, "top_level": top_level},
        )


type AnyGroup = type[HttpApiGroup[Any]]


def _wrapped(cls: type, endpoints: Mapping[str, AnyEndpoint]) -> Mapping[str, AnyEndpoint]:
    """``endpoints`` each wrapped by the middleware ``cls`` declares. Every
    assignment of a group's ``endpoints`` goes through here, so no class
    method can bring in an endpoint that skips it."""
    middlewares = _declared_middlewares(cls)
    out: dict[str, AnyEndpoint] = {}
    for identifier, endpoint in endpoints.items():
        wrapped = endpoint
        for middleware in middlewares:
            wrapped = wrapped.middleware(middleware)
        out[identifier] = wrapped
    return out


def _declared_middlewares(cls: type) -> tuple[AnyMiddleware, ...]:
    """The middleware classes of ``class G(HttpApiGroup[M])``."""
    for base in getattr(cls, "__orig_bases__", ()):
        if get_origin(base) is HttpApiGroup:
            return _middleware_classes(get_args(base)[0])
    return ()


def _middleware_classes(argument: object) -> tuple[AnyMiddleware, ...]:
    if get_origin(argument) in (Union, types.UnionType):
        return tuple(m for arg in get_args(argument) for m in _middleware_classes(arg))
    if isinstance(argument, type) and issubclass(argument, HttpApiMiddleware):
        return (cast("AnyMiddleware", argument),)
    raise TypeError(f"HttpApiGroup[...] takes middleware classes, got {argument!r}")


__all__ = ["AnyGroup", "GroupService", "HttpApiGroup"]
