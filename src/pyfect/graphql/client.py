"""A typed GraphQL client from a group (Effect's ``GraphQLClient``).

``make(Group)`` reads the ``GraphQLProtocol`` and the group's middleware
services and gives an instance of the group whose operations are methods.
A query or mutation method gives an ``Effect``, a subscription method a
``Stream`` retried by ``subscription_retry`` while its failures are
retryable (``default_subscription_retry``: 500ms, then x1.5 up to 5s, never
shorter than a ``retry_after``). ``pages`` / ``items`` follow cursor
connections; ``make_test`` / ``layer_test`` stand a client in for tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Never, Protocol, ReadOnly, TypedDict, cast

from pyfect import effect as fx
from pyfect import stream
from pyfect.context import Context, TagLike
from pyfect.duration import Seconds
from pyfect.effect import Effect
from pyfect.graphql._codec import Codec
from pyfect.graphql._types import (
    BatchUrl,
    ExecutionResult,
    ForcePost,
    GraphQLProtocol,
    GraphQLProtocolService,
    GraphQLRequest,
    ResolvedUrl,
)
from pyfect.graphql.client_error import GraphQLClientError, PaginationError
from pyfect.graphql.group import GraphQLGroup, GroupTypes, group_middlewares, operations_of
from pyfect.graphql.middleware import ExecuteOptions, Implementation, SubscribeOptions
from pyfect.graphql.operation import (
    NO_VARIABLES,
    AnyOperation,
    CallOptions,
    Method,
    Operation,
    PartialResult,
    RawExecutor,
    Subscription,
    SubscriptionMethod,
)
from pyfect.http import headers as _headers
from pyfect.http import url_params as _url_params
from pyfect.http.headers import Input as HeadersInput
from pyfect.http.url_params import Input as UrlParamsInput
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.option import Option, Some
from pyfect.schedule import Schedule, exponential, from_step, set_input_type, to_step
from pyfect.schedule._model import Decision, Metadata, Stop
from pyfect.stream import Stream


class GroupClass[G, T](Protocol):
    """A ``GraphQLGroup`` subclass: its instances are clients ``G`` and its
    middleware tags ``T``."""

    def __graphql_group__(self) -> GroupTypes[G, T]: ...


def _retry_delay(metadata: Metadata[Seconds, GraphQLClientError]) -> Effect[Seconds]:
    capped = Seconds(min(metadata.duration, 5.0))
    retry_after = metadata.input.retry_after
    return fx.succeed(capped if retry_after is None else Seconds(max(capped, retry_after)))


default_subscription_retry: Schedule[Seconds, GraphQLClientError] = (
    exponential(0.5, 1.5).pipe(set_input_type(GraphQLClientError)).modify_delay(_retry_delay)
)
"""500ms, then x1.5 each retry, capped at 5s and never shorter than the
error's ``retry_after``."""


def retryable_only[O, E, R](
    schedule: Schedule[O, GraphQLClientError, E, R],
) -> Schedule[O | None, object, E, R]:
    """``schedule`` stepped only by retryable ``GraphQLClientError``s; any
    other failure (a middleware's, a fatal one) stops it."""

    def guard(
        step: Callable[[float, GraphQLClientError], Effect[Decision[O], E, R]],
    ) -> Callable[[float, object], Effect[Decision[O | None], E, R]]:
        def guarded(now: float, input: object) -> Effect[Decision[O | None], E, R]:
            if isinstance(input, GraphQLClientError) and input.is_retryable:
                return step(now, input)
            return fx.succeed(Stop(None))

        return guarded

    return from_step(to_step(schedule).map(guard))


def _request_of(operation: AnyOperation, variables: object, options: CallOptions) -> GraphQLRequest:
    return GraphQLRequest(
        kind=operation.kind,
        query=operation.document,
        operation_name=operation.name,
        variables=variables,
        headers=_headers.EMPTY if options.headers is None else _headers.from_input(options.headers),
        url_params=_url_params.EMPTY
        if options.url_params is None
        else _url_params.from_input(options.url_params),
    )


@dataclass(frozen=True, slots=True)
class _Chain:
    """One operation's middleware chain in front of the transport."""

    operation: AnyOperation
    codec: Codec
    middlewares: Sequence[Implementation[Any, Any]]
    protocol: GraphQLProtocolService

    def execute(
        self, index: int, request: GraphQLRequest, force_post: bool, batch_url: BatchUrl | None
    ) -> Effect[ExecutionResult, Any, Any]:
        if index == len(self.middlewares):
            sent = self.protocol.execute(request)
            if force_post:
                sent = sent.pipe(fx.provide_service(ForcePost, True))
            if batch_url is not None:
                sent = sent.pipe(fx.provide_service(ResolvedUrl, batch_url))
            return sent.map_error(self.codec.fail).flat_map(self.codec.decode_answer)
        return self.middlewares[index].execute(
            ExecuteOptions(
                operation=self.operation,
                request=request,
                next=lambda next_request: self.execute(
                    index + 1, next_request, force_post, batch_url
                ),
            )
        )

    def run(self, request: GraphQLRequest, force_post: bool) -> Effect[ExecutionResult, Any, Any]:
        """The chain, handing a resolver batch's URL to the transport only,
        so calls made by middleware resolve their own."""

        def start(batch_url: BatchUrl | None) -> Effect[ExecutionResult, Any, Any]:
            if batch_url is None:
                return self.execute(0, request, force_post, None)
            return self.execute(0, request, force_post, batch_url).pipe(
                fx.provide_service(ResolvedUrl, None)
            )

        return ResolvedUrl().flat_map(start)

    def subscribe(self, index: int, request: GraphQLRequest) -> Stream[ExecutionResult, Any, Any]:
        if index == len(self.middlewares):
            return (
                self.protocol.subscribe(request)
                .map_error(self.codec.fail)
                .map_effect(self.codec.decode_answer)
            )
        return self.middlewares[index].subscribe(
            SubscribeOptions(
                operation=self.operation,
                request=request,
                next=lambda next_request: self.subscribe(index + 1, next_request),
            )
        )


def _call_context(options: CallOptions) -> Context[Any]:
    return Context.empty() if options.context is None else options.context


def _make_method(chain: _Chain, retry: Schedule[Any, object, Any, Any]) -> object:
    operation = chain.operation
    codec = chain.codec

    def request(variables: object, options: CallOptions) -> Effect[GraphQLRequest, Any, Any]:
        return codec.encode_variables(variables).map(
            lambda encoded: _request_of(operation, encoded, options)
        )

    if operation.kind == "subscription":

        def subscribe(variables: object, options: CallOptions) -> Stream[Any, Any, Any]:
            events: Stream[Any, Any, Any] = (
                stream.from_effect(request(variables, options))
                .flat_map(lambda built: chain.subscribe(0, built))
                .map_effect(codec.decode_strict)
                .retry(retry)
            )
            return events.pipe(stream.provide_context(_call_context(options)))

        return SubscriptionMethod[Any, Any, Any, Any](operation, subscribe)

    def call(variables: object, options: CallOptions) -> Effect[Any, Any, Any]:
        decode = codec.decode_partial if options.partial else codec.decode_strict
        result: Effect[Any, Any, Any] = (
            request(variables, options)
            .flat_map(lambda built: chain.run(built, False))
            .flat_map(decode)
        )
        return result.pipe(fx.provide_context(_call_context(options)))

    raw = RawExecutor(execute=lambda built: chain.run(built, True), url=chain.protocol.url)
    return Method[Any, Any, Any, Any](operation, call, raw)


def make[G, T](
    group: GroupClass[G, T],
    *,
    subscription_retry: Schedule[object, GraphQLClientError, Any, Any] | None = None,
) -> Effect[G, Never, GraphQLProtocol | T]:
    """A client of ``group``'s operations, sending through the
    ``GraphQLProtocol`` and running the middleware services the context
    holds."""
    cls = cast("type[GraphQLGroup[Any]]", group)
    retry = retryable_only(
        default_subscription_retry if subscription_retry is None else subscription_retry
    )
    added = group_middlewares(cls)

    def build(protocol: GraphQLProtocolService, context: Context[Any]) -> G:
        methods: dict[AnyOperation, object] = {}
        for operation in operations_of(cls):
            middlewares = [context.unsafe_get(tag) for tag in (*added, *operation.middlewares)]
            chain = _Chain(operation, Codec(operation), middlewares, protocol)
            methods[operation] = _make_method(chain, retry)
        return cast("G", cls(methods))

    built: Effect[G, Never, Any] = GraphQLProtocol().flat_map(
        lambda protocol: fx.context().map(lambda context: build(protocol, context))
    )
    return built


# --- pages ---------------------------------------------------------------------------


class PageInfo(TypedDict):
    """A connection's ``pageInfo``."""

    hasNextPage: ReadOnly[bool]
    endCursor: ReadOnly[str | None]


class Connection(TypedDict):
    """A Relay cursor connection: its ``pageInfo``."""

    pageInfo: ReadOnly[PageInfo]


class NodesConnection[N](Connection):
    """A connection with ``nodes``."""

    nodes: ReadOnly[Sequence[N] | None]


@dataclass(frozen=True, slots=True, kw_only=True)
class PageOptions:
    """Options sent with every page request."""

    headers: HeadersInput | None = None
    url_params: UrlParamsInput | None = None
    context: Context[Any] | None = None


def pages[V, A, ME, MR, C: Connection](
    method: Method[V, A, ME, MR],
    *,
    variables: V,
    connection: Callable[[A], C | None],
    options: PageOptions | None = None,
) -> Stream[C, GraphQLClientError | ME, MR]:
    """Each page of the ``connection`` ``method``'s result holds, sending
    its ``endCursor`` as the ``after`` variable until ``hasNextPage`` is
    false. The operation must declare an optional ``$after: String``. A
    null connection on the first page is an empty stream; on a later one,
    or a cursor that is null or does not advance, a ``PaginationError``."""
    given = PageOptions() if options is None else options
    call = cast("Callable[..., Effect[A, GraphQLClientError | ME, MR]]", method)
    name = method.operation.name
    first = cast("Mapping[str, object]", variables)

    def page(
        after: str | None,
    ) -> Effect[tuple[Iterable[C], Option[str]], GraphQLClientError | ME, MR]:
        def fail(description: str) -> Effect[Never, GraphQLClientError]:
            reason = PaginationError(description=description, cursor=after)
            return fx.fail(GraphQLClientError(operation=name, reason=reason))

        def next_page(result: A) -> Effect[tuple[Iterable[C], Option[str]], GraphQLClientError]:
            found = connection(result)
            if found is None:
                if after is None:
                    return fx.succeed(((), None))
                return fail("The connection was null on a page after the first")
            info = found["pageInfo"]
            end = info["endCursor"]
            if not info["hasNextPage"]:
                return fx.succeed(((found,), None))
            if end is None:
                return fail("hasNextPage is true but endCursor is null")
            if end == after:
                return fail(f'endCursor "{end}" did not advance')
            return fx.succeed(((found,), Some(end)))

        sent = first if after is None else {**first, "after": after}
        return call(
            sent, headers=given.headers, url_params=given.url_params, context=given.context
        ).flat_map(next_page)

    return stream.paginate(None, page)


def items[V, A, ME, MR, N](
    method: Method[V, A, ME, MR],
    *,
    variables: V,
    connection: Callable[[A], NodesConnection[N] | None],
    options: PageOptions | None = None,
) -> Stream[N, GraphQLClientError | ME, MR]:
    """The ``nodes`` of every page (``pages``), null entries included."""
    connections = pages(method, variables=variables, connection=connection, options=options)
    return connections.flat_map(lambda found: stream.from_iterable(found["nodes"] or ()))


# --- test clients ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class TestCallOptions:
    """The headers and URL params a test handler's caller passed."""

    headers: HeadersInput | None = None
    url_params: UrlParamsInput | None = None


type TestHandler = Callable[[Any, TestCallOptions], Effect[Any, Any] | Stream[Any, Any]]
"""A test handler: the caller's variables and options in, the result (a
stream, for a subscription) out."""


class UnimplementedError(Exception):
    """A test client's operation without a handler was called."""


def _test_method(operation: AnyOperation, handler: TestHandler | None) -> object:
    subscription = operation.kind == "subscription"
    if handler is None:
        defect = UnimplementedError(f'GraphQLClient: Unimplemented operation "{operation.name}"')

        def unimplemented(variables: object, options: CallOptions) -> Any:
            return stream.die(defect) if subscription else fx.die(defect)

        method = unimplemented
    else:
        run = handler

        def method(variables: object, options: CallOptions) -> Any:
            test_options = TestCallOptions(headers=options.headers, url_params=options.url_params)
            given: object = (
                {} if variables is None and operation.variables is NO_VARIABLES else variables
            )

            def thunk() -> Any:
                return run(given, test_options)

            if subscription:
                return stream.suspend(thunk)
            result: Effect[Any, Any] = fx.suspend(thunk)
            return result.map(lambda data: PartialResult(data, ())) if options.partial else result

    if subscription:
        return SubscriptionMethod[Any, Any, Any, Any](operation, method)
    return Method[Any, Any, Any, Any](operation, method)


def make_test[G, T](group: GroupClass[G, T], /, **handlers: TestHandler) -> G:
    """A client of ``group`` whose methods call ``handlers`` (keyed by the
    group's attribute names) instead of a transport; an operation without
    a handler dies with an ``UnimplementedError``. ``partial=True`` gives
    the handler's value with no errors."""
    cls = cast("type[GraphQLGroup[Any]]", group)
    declared = {name: _raw_attribute(cls, name) for name in handlers}
    unknown = [
        name for name, op in declared.items() if not isinstance(op, Operation | Subscription)
    ]
    if unknown:
        raise ValueError(f"make_test: {cls.__qualname__} has no operations {unknown!r}")
    methods: dict[AnyOperation, object] = {}
    for operation in operations_of(cls):
        handler = next((handlers[n] for n, op in declared.items() if op is operation), None)
        methods[operation] = _test_method(operation, handler)
    return cast("G", cls(methods))


def _raw_attribute(cls: type, name: str) -> object:
    for klass in cls.__mro__:
        if name in vars(klass):
            return vars(klass)[name]
    return None


def layer_test[G, T, I](
    tag: TagLike[G, I], group: GroupClass[G, T], /, **handlers: TestHandler
) -> Layer[I]:
    """A layer providing ``make_test(group, **handlers)`` as ``tag``'s
    service."""
    return layer_succeed(tag, make_test(group, **handlers))


__all__ = [
    "Connection",
    "GroupClass",
    "NodesConnection",
    "PageInfo",
    "PageOptions",
    "TestCallOptions",
    "TestHandler",
    "UnimplementedError",
    "default_subscription_retry",
    "items",
    "layer_test",
    "make",
    "make_test",
    "pages",
    "retryable_only",
]
