"""HTTP APIs (Effect's ``HttpApi``): groups of endpoints under one
identifier, served by ``HttpApiBuilder``, called with ``HttpApiClient`` and
documented by ``OpenApi``::

    api = HttpApi.make("app").add(Users).add(Posts)  # HttpApi[Users | Posts]
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Generic, Never, Protocol, Self, TypeVar, overload

from pyfect.context import Context, Tag, TagLike
from pyfect.http_api import schema as api_schema
from pyfect.http_api.endpoint import AnyEndpoint, error_schemas, success_schemas
from pyfect.http_api.group import AnyGroup, HttpApiGroup
from pyfect.http_api.middleware import AnyMiddleware
from pyfect.schema import ParseOptions as SchemaParseOptions
from pyfect.schema import Top

G_co = TypeVar("G_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class HttpApi(Generic[G_co]):
    """An API of the groups ``G`` (group classes), by identifier."""

    identifier: str
    groups: Mapping[str, AnyGroup] = field(default_factory=dict[str, AnyGroup])
    annotations: Context[Any] = field(default_factory=Context.empty)

    if TYPE_CHECKING:
        # The groups seen contravariantly, for ``ApiWith``.
        def _has_group(self, group: type[G_co], /) -> None: ...  # pyright: ignore[reportGeneralTypeIssues]

    @staticmethod
    def make(identifier: str) -> HttpApi[Never]:
        return HttpApi(identifier)

    @overload
    def add[G1: HttpApiGroup[Any]](self, g1: type[G1], /) -> HttpApi[G_co | G1]: ...
    @overload
    def add[G1: HttpApiGroup[Any], G2: HttpApiGroup[Any]](
        self, g1: type[G1], g2: type[G2], /
    ) -> HttpApi[G_co | G1 | G2]: ...
    @overload
    def add[G1: HttpApiGroup[Any], G2: HttpApiGroup[Any], G3: HttpApiGroup[Any]](
        self, g1: type[G1], g2: type[G2], g3: type[G3], /
    ) -> HttpApi[G_co | G1 | G2 | G3]: ...
    def add(self, *groups: AnyGroup) -> HttpApi[Any]:
        """This API with more groups (a group replaces one with its
        identifier)."""
        added = dict(self.groups)
        for group in groups:
            added[group.identifier] = group
        return replace(self, groups=added)

    def add_http_api[G2](self, api: HttpApi[G2], /) -> HttpApi[G_co | G2]:
        """This API with the groups of ``api``, which keep its annotations
        under their own."""
        added: dict[str, AnyGroup] = dict(self.groups)
        for key, group in api.groups.items():
            added[key] = group.annotate_merge(api.annotations.merge(group.annotations))
        return HttpApi(self.identifier, added, self.annotations)

    def prefix(self, prefix: str) -> Self:
        """This API with every endpoint under ``prefix``."""
        return replace(self, groups={k: g.prefix(prefix) for k, g in self.groups.items()})

    def middleware(self, middleware: AnyMiddleware) -> Self:
        """This API with every endpoint wrapped by ``middleware``. Only the
        run time changes: the handlers and clients are typed by their
        groups' middleware."""
        return replace(self, groups={k: g.middleware(middleware) for k, g in self.groups.items()})

    def annotate[S, T](self, tag: TagLike[S, T], value: S) -> Self:
        return replace(self, annotations=self.annotations.add(tag, value))

    def annotate_merge(self, annotations: Context[Any]) -> Self:
        return replace(self, annotations=self.annotations.merge(annotations))

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)


type AnyApi = HttpApi[Any]


class ApiWith[G](Protocol):
    """An ``HttpApi`` that has the group ``G``. A parameter ``api:
    HttpApi[G]`` beside ``group: type[G]`` would widen ``G`` to take any
    group (``HttpApi`` is covariant); matched through ``_has_group``, the
    api's groups bound ``G`` from above, so a group it lacks is an error."""

    def _has_group(self, group: type[G], /) -> None: ...


def api_of(api: ApiWith[Any]) -> AnyApi:
    """The ``HttpApi`` behind an ``ApiWith`` (every one is an ``HttpApi``)."""
    if not isinstance(api, HttpApi):
        raise TypeError(f"api must be an HttpApi, got {type(api).__name__}")
    return api


# --- reflection ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReflectedEndpoint:
    """An endpoint as ``reflect`` sees it: its annotations merged over its
    group's and API's, and its buffered responses by status."""

    group: AnyGroup
    endpoint: AnyEndpoint
    merged_annotations: Context[Any]
    middleware: tuple[AnyMiddleware, ...]
    successes: Mapping[int, tuple[Top, ...]]
    errors: Mapping[int, tuple[Top, ...]]


def reflect(
    api: AnyApi,
    *,
    on_group: Callable[[AnyGroup, Context[Any]], None],
    on_endpoint: Callable[[ReflectedEndpoint], None],
    predicate: Callable[[AnyGroup, AnyEndpoint], bool] | None = None,
) -> None:
    """Visit every group (with its merged annotations) and endpoint."""
    for group in api.groups.values():
        group_annotations = api.annotations.merge(group.annotations)
        on_group(group, group_annotations)
        for endpoint in group.endpoints.values():
            if predicate is not None and not predicate(group, endpoint):
                continue
            on_endpoint(
                ReflectedEndpoint(
                    group,
                    endpoint,
                    group_annotations.merge(endpoint.annotations),
                    endpoint.middlewares,
                    _response_content(
                        success_schemas(endpoint), api_schema.get_status_success_schema
                    ),
                    _response_content(error_schemas(endpoint), api_schema.get_status_error_schema),
                )
            )


def _response_content(
    schemas: tuple[Top, ...], get_status: Callable[[Top], int]
) -> Mapping[int, tuple[Top, ...]]:
    result: dict[int, tuple[Top, ...]] = {}
    for schema in schemas:
        body = schema.schema if api_schema.is_with_headers(schema) else schema
        if api_schema.is_stream_schema(body) or api_schema.is_upgrade(body):
            continue
        status = get_status(schema)
        result[status] = (*result.get(status, ()), schema)
    return result


# --- annotations ---------------------------------------------------------------------


class AdditionalSchemas(Tag[tuple[Top, ...]], key="effect/http-api/HttpApi/AdditionalSchemas"):
    """Schemas OpenAPI documents in its components though no endpoint uses
    them."""


class ParseOptions(Tag[SchemaParseOptions], key="effect/http-api/HttpApi/ParseOptions"):
    """The parse options of every slot that has none of its own."""


class ParamsParseOptions(Tag[SchemaParseOptions], key="effect/http-api/HttpApi/ParamsParseOptions"):
    pass


class QueryParseOptions(Tag[SchemaParseOptions], key="effect/http-api/HttpApi/QueryParseOptions"):
    pass


class HeadersParseOptions(
    Tag[SchemaParseOptions], key="effect/http-api/HttpApi/HeadersParseOptions"
):
    pass


class PayloadParseOptions(
    Tag[SchemaParseOptions], key="effect/http-api/HttpApi/PayloadParseOptions"
):
    pass


class SuccessParseOptions(
    Tag[SchemaParseOptions], key="effect/http-api/HttpApi/SuccessParseOptions"
):
    pass


class ErrorParseOptions(Tag[SchemaParseOptions], key="effect/http-api/HttpApi/ErrorParseOptions"):
    pass


@dataclass(frozen=True, slots=True)
class SlotParseOptions:
    """The parse options of each part of a request and response."""

    params: SchemaParseOptions
    query: SchemaParseOptions
    headers: SchemaParseOptions
    payload: SchemaParseOptions
    success: SchemaParseOptions
    error: SchemaParseOptions


def get_slot_parse_options(annotations: Context[Any]) -> SlotParseOptions:
    """Each slot's options: its own annotation, else ``ParseOptions``."""
    fallback = annotations.get_option(ParseOptions)
    default: SchemaParseOptions = {} if fallback is None else fallback.value

    def slot(tag: type[Tag[SchemaParseOptions]]) -> SchemaParseOptions:
        found = annotations.get_option(tag)
        return default if found is None else found.value

    return SlotParseOptions(
        params=slot(ParamsParseOptions),
        query=slot(QueryParseOptions),
        headers=slot(HeadersParseOptions),
        payload=slot(PayloadParseOptions),
        success=slot(SuccessParseOptions),
        error=slot(ErrorParseOptions),
    )


__all__ = [
    "AdditionalSchemas",
    "AnyApi",
    "ApiWith",
    "ErrorParseOptions",
    "HeadersParseOptions",
    "HttpApi",
    "ParamsParseOptions",
    "ParseOptions",
    "PayloadParseOptions",
    "QueryParseOptions",
    "ReflectedEndpoint",
    "SlotParseOptions",
    "SuccessParseOptions",
    "api_of",
    "get_slot_parse_options",
    "reflect",
]
