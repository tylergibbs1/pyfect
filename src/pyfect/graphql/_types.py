"""What a GraphQL transport takes and gives: a ``GraphQLRequest`` in, an
``Answer`` (the raw body with its HTTP status and headers) out, read by the
client into an ``ExecutionResult``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from pyfect import schema as S
from pyfect.context import Reference, Tag
from pyfect.effect import Effect
from pyfect.graphql.client_error import GraphQLError, TransportError
from pyfect.http.headers import EMPTY as EMPTY_HEADERS
from pyfect.http.headers import Headers
from pyfect.http.url_params import EMPTY as EMPTY_URL_PARAMS
from pyfect.http.url_params import UrlParams
from pyfect.stream import Stream

type Kind = Literal["query", "mutation", "subscription"]


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphQLRequest:
    """One operation to send: the document (``query``), the operation's
    name and its encoded variables, plus per-call headers and URL params.
    Middleware may return a changed copy (``dataclasses.replace``)."""

    kind: Kind
    query: str
    operation_name: str
    variables: object
    extensions: Mapping[str, object] | None = None
    headers: Headers = field(default=EMPTY_HEADERS)
    url_params: UrlParams = field(default=EMPTY_URL_PARAMS)


def request_body(request: GraphQLRequest) -> dict[str, object]:
    """The JSON body of a POST and the payload of a graphql-ws
    ``subscribe``; ``extensions`` is left out when unset."""
    body: dict[str, object] = {
        "query": request.query,
        "operationName": request.operation_name,
        "variables": request.variables,
    }
    if request.extensions is not None:
        body["extensions"] = request.extensions
    return body


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionResult:
    """A GraphQL response: ``data`` (``None`` when null or missing), its
    ``errors`` and ``extensions``, and the transport's ``status`` and
    ``headers`` (metadata, never read from the body)."""

    data: object = None
    errors: tuple[GraphQLError, ...] = ()
    extensions: Mapping[str, S.JsonValue] | None = None
    status: int | None = None
    headers: Headers | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Answer:
    """What a transport received: the parsed body, and the HTTP status and
    headers when there were any."""

    body: object
    status: int | None = None
    headers: Headers | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphQLProtocolService:
    """A transport: ``execute`` sends a query or mutation, ``subscribe``
    a subscription. ``url`` resolves the endpoint of an operation, when the
    transport has one."""

    execute: Callable[[GraphQLRequest], Effect[Answer, TransportError]]
    subscribe: Callable[[GraphQLRequest], Stream[Answer, TransportError]]
    url: Callable[[Kind, str], Effect[str]] | None = None


class GraphQLProtocol(Tag[GraphQLProtocolService], key="effect/graphql/GraphQLProtocol"):
    """The transport the GraphQL client sends through."""


class ForcePost(Reference[bool], key="effect/graphql/ForcePost"):
    """Set while a resolver batch is sent, so a transport that would send
    queries by GET posts it (a batch may outgrow a URL)."""

    @classmethod
    def default(cls) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class BatchUrl:
    """The URL a resolver batch was grouped by, and the ``url`` function
    of the transport that resolved it."""

    resolve: Callable[[Kind, str], Effect[str]]
    url: str


class ResolvedUrl(Reference[BatchUrl | None], key="effect/graphql/ResolvedUrl"):
    """Carries a ``BatchUrl`` from a resolver batch to the transport, so it
    sends there without resolving the URL again. The client clears it while
    middleware run, so calls they make resolve their own."""

    @classmethod
    def default(cls) -> BatchUrl | None:
        return None
