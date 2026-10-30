"""GraphQL operations (Effect's ``GraphQL``): a document with a variables
schema and a result schema, as ``@effect/graphql-generator`` emits them.

``query`` / ``mutation`` give an ``Operation``, ``subscription`` a
``Subscription``. Put operations on a ``GraphQLGroup`` class; read on the
client ``client.make(Group)`` gives, an operation is its method::

    Viewer = query("Viewer", document="query Viewer{viewer{login}}", result=VIEWER)

    class Api(GraphQLGroup):
        viewer = Viewer

    api = yield* client.make(Api)
    result = yield* api.viewer()

``Operation[V, A, ME_co, MR_co]``: variables ``V``, result ``A``, middleware
errors ``ME_co``, and the services its schemas and middleware need ``MR_co``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    Never,
    Self,
    TypedDict,
    TypeIs,
    TypeVar,
    overload,
)

from pyfect import schema as S
from pyfect.context import Context, TagLike
from pyfect.effect import Effect
from pyfect.graphql._template import join_template
from pyfect.graphql._types import ExecutionResult, GraphQLRequest, Kind
from pyfect.graphql.client_error import GraphQLClientError, GraphQLError
from pyfect.graphql.middleware import AnyMiddleware, Implementation
from pyfect.graphql.template import DocumentTemplate
from pyfect.http.headers import Input as HeadersInput
from pyfect.http.url_params import Input as UrlParamsInput
from pyfect.schema import Codec
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect.graphql.group import GraphQLGroup
    from pyfect.graphql.middleware import GraphQLMiddleware

V = TypeVar("V")
V_contra = TypeVar("V_contra", contravariant=True)
A_co = TypeVar("A_co", covariant=True)
ME_co = TypeVar("ME_co", covariant=True, default=Never)
MR_co = TypeVar("MR_co", covariant=True, default=Never)


class NoVariables(TypedDict):
    """The variables of an operation that declares none."""


NO_VARIABLES = S.Struct(NoVariables)


@dataclass(frozen=True, slots=True)
class PartialResult(Generic[A_co]):
    """A result decoded alongside the response's errors (``partial=True``),
    and the response it came from (``None`` from a ``make_test`` client)."""

    data: A_co
    errors: tuple[GraphQLError, ...]
    response: ExecutionResult | None = field(default=None, compare=False, repr=False, kw_only=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class CallOptions:
    """The options of one call: extra headers and URL params, services for
    the call (``context``) and whether a partial result is wanted."""

    headers: HeadersInput | None = None
    url_params: UrlParamsInput | None = None
    context: Context[Any] | None = None
    partial: bool = False


type Call = Callable[[object, CallOptions], Any]


@dataclass(frozen=True, eq=False, kw_only=True)
class OperationInfo:
    """The runtime fields every operation has (a plain value: no
    descriptor), as middleware and transports see it."""

    kind: Kind
    name: str
    document: str
    template: DocumentTemplate | None
    variables: Codec[Any, Any, Any, Any]
    result: Codec[Any, Any, Any, Any]
    middlewares: tuple[AnyMiddleware, ...] = ()

    def _for_owner(self, owner: type) -> Self:
        from pyfect.graphql.group import group_middlewares

        added = group_middlewares(owner)
        return self if not added else replace(self, middlewares=(*added, *self.middlewares))

    def _method(self, instance: object) -> Any:
        from pyfect.graphql.group import method_of

        return method_of(instance, self)


@dataclass(frozen=True, slots=True)
class RawExecutor:
    """How a resolver sends a batch through a client method: its middleware
    and transport, always by POST, and the transport's ``url``."""

    execute: Callable[[GraphQLRequest], Effect[ExecutionResult, Any, Any]]
    url: Callable[[Kind, str], Effect[str]] | None


class Method(Generic[V_contra, A_co, ME_co, MR_co]):
    """A query or mutation on a client: call it with the variables (none
    for an operation without), and ``partial=True`` for the decoded data
    alongside the response's errors. ``context`` provides services to the
    call."""

    __slots__ = ("_call", "operation", "raw")

    def __init__(self, operation: AnyOperation, call: Call, raw: RawExecutor | None = None) -> None:
        self.operation = operation
        self._call = call
        self.raw = raw

    @overload
    def __call__(
        self: Method[NoVariables, A_co, ME_co, MR_co],
        variables: None = None,
        /,
        *,
        partial: Literal[False] = False,
        headers: HeadersInput | None = None,
        url_params: UrlParamsInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[A_co, GraphQLClientError | ME_co, MR_co]: ...
    @overload
    def __call__(
        self: Method[NoVariables, A_co, ME_co, MR_co],
        variables: None = None,
        /,
        *,
        partial: Literal[True],
        headers: HeadersInput | None = None,
        url_params: UrlParamsInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[PartialResult[A_co], GraphQLClientError | ME_co, MR_co]: ...
    @overload
    def __call__(
        self,
        variables: V_contra,
        /,
        *,
        partial: Literal[False] = False,
        headers: HeadersInput | None = None,
        url_params: UrlParamsInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[A_co, GraphQLClientError | ME_co, MR_co]: ...
    @overload
    def __call__(
        self,
        variables: V_contra,
        /,
        *,
        partial: Literal[True],
        headers: HeadersInput | None = None,
        url_params: UrlParamsInput | None = None,
        context: Context[Any] | None = None,
    ) -> Effect[PartialResult[A_co], GraphQLClientError | ME_co, MR_co]: ...
    def __call__(
        self,
        variables: object = None,
        /,
        *,
        partial: bool = False,
        headers: HeadersInput | None = None,
        url_params: UrlParamsInput | None = None,
        context: Context[Any] | None = None,
    ) -> Any:
        options = CallOptions(
            headers=headers, url_params=url_params, context=context, partial=partial
        )
        return self._call(variables, options)


class SubscriptionMethod(Generic[V_contra, A_co, ME_co, MR_co]):
    """A subscription on a client: a stream of results, retried by the
    client's ``subscription_retry`` while its failures are retryable."""

    __slots__ = ("_call", "operation")

    def __init__(self, operation: AnyOperation, call: Call) -> None:
        self.operation = operation
        self._call = call

    @overload
    def __call__(
        self: SubscriptionMethod[NoVariables, A_co, ME_co, MR_co],
        variables: None = None,
        /,
        *,
        headers: HeadersInput | None = None,
        url_params: UrlParamsInput | None = None,
        context: Context[Any] | None = None,
    ) -> Stream[A_co, GraphQLClientError | ME_co, MR_co]: ...
    @overload
    def __call__(
        self,
        variables: V_contra,
        /,
        *,
        headers: HeadersInput | None = None,
        url_params: UrlParamsInput | None = None,
        context: Context[Any] | None = None,
    ) -> Stream[A_co, GraphQLClientError | ME_co, MR_co]: ...
    def __call__(
        self,
        variables: object = None,
        /,
        *,
        headers: HeadersInput | None = None,
        url_params: UrlParamsInput | None = None,
        context: Context[Any] | None = None,
    ) -> Any:
        return self._call(
            variables, CallOptions(headers=headers, url_params=url_params, context=context)
        )


@dataclass(frozen=True, eq=False, kw_only=True)
class Operation(OperationInfo, Generic[V, A_co, ME_co, MR_co]):
    """A query or mutation. On a group instance (a client) it is its
    ``Method``; on a group class, it carries the group's middleware."""

    @overload
    def __get__(self, instance: None, owner: type[GraphQLGroup[Never]], /) -> Self: ...
    @overload
    def __get__[GE, GR](
        self, instance: None, owner: type[GraphQLGroup[GraphQLMiddleware[GE, GR]]], /
    ) -> Operation[V, A_co, ME_co | GE, MR_co | GR]: ...
    @overload
    def __get__(
        self, instance: GraphQLGroup[Never], owner: type[object], /
    ) -> Method[V, A_co, ME_co, MR_co]: ...
    @overload
    def __get__[GE, GR](
        self, instance: GraphQLGroup[GraphQLMiddleware[GE, GR]], owner: type[object], /
    ) -> Method[V, A_co, ME_co | GE, MR_co | GR]: ...
    def __get__(self, instance: object, owner: type[object], /) -> Any:
        return self._for_owner(owner) if instance is None else self._method(instance)

    def middleware[E2, R2, T](
        self, middleware: TagLike[Implementation[E2, R2], T], /
    ) -> Operation[V, A_co, ME_co | E2, MR_co | R2]:
        """A copy with ``middleware`` added last; this one is unchanged."""
        added: Any = middleware
        return replace(self, middlewares=(*self.middlewares, added))


@dataclass(frozen=True, eq=False, kw_only=True)
class Subscription(OperationInfo, Generic[V, A_co, ME_co, MR_co]):
    """A subscription. On a group instance (a client) it is its
    ``SubscriptionMethod``."""

    @overload
    def __get__(self, instance: None, owner: type[GraphQLGroup[Never]], /) -> Self: ...
    @overload
    def __get__[GE, GR](
        self, instance: None, owner: type[GraphQLGroup[GraphQLMiddleware[GE, GR]]], /
    ) -> Subscription[V, A_co, ME_co | GE, MR_co | GR]: ...
    @overload
    def __get__(
        self, instance: GraphQLGroup[Never], owner: type[object], /
    ) -> SubscriptionMethod[V, A_co, ME_co, MR_co]: ...
    @overload
    def __get__[GE, GR](
        self, instance: GraphQLGroup[GraphQLMiddleware[GE, GR]], owner: type[object], /
    ) -> SubscriptionMethod[V, A_co, ME_co | GE, MR_co | GR]: ...
    def __get__(self, instance: object, owner: type[object], /) -> Any:
        return self._for_owner(owner) if instance is None else self._method(instance)

    def middleware[E2, R2, T](
        self, middleware: TagLike[Implementation[E2, R2], T], /
    ) -> Subscription[V, A_co, ME_co | E2, MR_co | R2]:
        """A copy with ``middleware`` added last; this one is unchanged."""
        added: Any = middleware
        return replace(self, middlewares=(*self.middlewares, added))


type AnyOperation = OperationInfo


def _fields(
    kind: Kind,
    name: str,
    document: str | DocumentTemplate,
    variables: Codec[Any, Any, Any, Any] | None,
    result: Codec[Any, Any, Any, Any],
) -> dict[str, Any]:
    template = document if isinstance(document, DocumentTemplate) else None
    return {
        "kind": kind,
        "name": name,
        "document": document if template is None else join_template(kind, name, template),
        "template": template,
        "variables": NO_VARIABLES if variables is None else variables,
        "result": result,
    }


def query[A, V = NoVariables, RR = Never](
    name: str,
    *,
    document: str | DocumentTemplate,
    result: Codec[A, Any, RR, Any],
    variables: Codec[V, Any, Any, RR] | None = None,
) -> Operation[V, A, Never, RR]:
    """A query: its ``document`` (or the template it is joined from), the
    ``result`` schema of its ``data`` and, when it declares variables, their
    schema."""
    return Operation(**_fields("query", name, document, variables, result))


def mutation[A, V = NoVariables, RR = Never](
    name: str,
    *,
    document: str | DocumentTemplate,
    result: Codec[A, Any, RR, Any],
    variables: Codec[V, Any, Any, RR] | None = None,
) -> Operation[V, A, Never, RR]:
    """A mutation; see ``query``."""
    return Operation(**_fields("mutation", name, document, variables, result))


def subscription[A, V = NoVariables, RR = Never](
    name: str,
    *,
    document: str | DocumentTemplate,
    result: Codec[A, Any, RR, Any],
    variables: Codec[V, Any, Any, RR] | None = None,
) -> Subscription[V, A, Never, RR]:
    """A subscription; see ``query``."""
    return Subscription(**_fields("subscription", name, document, variables, result))


def other_typename(selected: Sequence[str], /) -> S.Bottom[str]:
    """The ``__typename`` of a union member the document did not select:
    any string but the ``selected`` names, including names the server adds
    later."""
    rejected = frozenset(selected)
    names = ", ".join(f'"{name}"' for name in selected)

    def other(name: str) -> TypeIs[str]:
        return name not in rejected

    return S.String.pipe(
        S.refine(other, title="otherTypename", expected=f"a __typename other than {names}")
    )


def enum_literals[L: str](literals: Sequence[L], /) -> S.Bottom[L, str]:
    """A GraphQL enum: typed as ``literals`` but accepting any string, so
    a value the server adds later still decodes."""

    def any_string(_: str) -> TypeIs[L]:
        return True

    return S.String.pipe(
        S.refine(
            any_string,
            title=f"enum({' | '.join(literals)})",
            description=", ".join(f'"{literal}"' for literal in literals)
            + ", or any string the server adds later",
        )
    )


__all__ = [
    "NO_VARIABLES",
    "AnyOperation",
    "CallOptions",
    "Method",
    "NoVariables",
    "Operation",
    "OperationInfo",
    "PartialResult",
    "Subscription",
    "SubscriptionMethod",
    "enum_literals",
    "mutation",
    "other_typename",
    "query",
    "subscription",
]
