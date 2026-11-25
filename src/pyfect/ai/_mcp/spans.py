"""The server span of each MCP request, after the OpenTelemetry MCP semantic conventions
(Effect's ``requestSpanOptions`` and ``endRequestSpan``).

A request's span is named after its method, with the tool or prompt appended for
``tools/call`` and ``prompts/get`` (``tools/call get_weather``). A W3C ``traceparent`` in
``params._meta`` is its parent, and the transport's span (the HTTP server span) is linked.
The span ends once the response is written: an error response records its code
(``rpc.status_code``, and ``error.type`` unless the request itself was at fault), and a
``tools/call`` result with ``isError`` is a ``tool_error``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.ai._tool_arguments import stringify_tool_arguments
from pyfect.ai.mcp_schema import JsonObject
from pyfect.ai.toolkit import RecordToolArguments
from pyfect.clock import Clock
from pyfect.effect import sync, with_fiber
from pyfect.exit import Exit, Success
from pyfect.exit import void as exit_void
from pyfect.http.headers import Headers
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.trace_context import w3c
from pyfect.tracer import ExternalSpan, ParentSpan, Span, SpanLink, SpanOptions
from pyfect.tracer._refs import TracerTimingEnabled
from pyfect.tracer._spans import in_parent_span, span_using

_SESSION_HEADER = "mcp-session-id"

type Transport = Literal["stdio", "http", "custom"]

# JSON-RPC errors caused by the request rather than the server: parse error, invalid
# request, method not found, invalid params and resource not found. Per the MCP semantic
# conventions they do not mark the span as failed.
_REQUEST_ERROR_CODES = frozenset({-32700, -32600, -32601, -32602, -32002})

_NETWORK_TRANSPORTS: Mapping[Transport, str] = {"http": "tcp", "stdio": "pipe"}


@dataclass(frozen=True, slots=True)
class RequestSpan:
    """What a request's span is made from. ``protocol_version`` is read when the span
    starts, and again when it ends if it had none (``initialize`` negotiates it)."""

    id: object
    method: str
    params: JsonObject
    protocol_version: Callable[[], str | None]
    transport: Transport


type RecordError = Callable[[int], None]
"""Records on the span that the server itself answered with an error code."""

type Write[E, R] = Callable[[JsonObject, RecordError], Effect[None, E, R]]


@dataclass(slots=True)
class _Answered:
    reply: JsonObject | None = None
    error_code: int | None = None
    """Set when the server answered with an error of its own (a failed write)."""


def traced[E, R](
    request: RequestSpan,
    answered: Effect[Any, Any, R],
    to_reply: Callable[[Exit[Any, Any]], Effect[JsonObject, E, R]],
    write: Write[E, R] | None,
) -> Effect[JsonObject, E, R]:
    """``answered`` inside the request's span, its response (``to_reply`` of its exit),
    and ``write`` of that, after which the span ends."""

    def run(fiber: Fiber[Any, Any]) -> Effect[JsonObject, E, R]:
        name, options = _options(fiber, request)

        def body(span: Span) -> Effect[JsonObject, E, R]:
            state = _Answered()

            def recorded(reply: JsonObject) -> JsonObject:
                state.reply = reply
                return reply

            def record_error(code: int) -> None:
                state.error_code = code

            def respond(exit: Exit[Any, Any]) -> Effect[JsonObject, E, R]:
                replied = to_reply(exit).map(recorded)
                if write is not None:
                    send = write
                    replied = replied.flat_map(lambda reply: send(reply, record_error).as_(reply))
                return replied.on_exit(
                    lambda last: sync(
                        lambda: _end(
                            fiber, span, request=request, answered=exit, last=last, state=state
                        )
                    )
                )

            return in_parent_span(answered, span).exit().flat_map(respond)

        return span_using(name, body, options)

    return with_fiber(run)


def _options(fiber: Fiber[Any, Any], request: RequestSpan) -> tuple[str, SpanOptions]:
    params = request.params
    attributes: dict[str, object] = {"mcp.method.name": request.method}
    version = request.protocol_version()
    if version is not None:
        attributes["mcp.protocol.version"] = version
    if request.id is not None:
        attributes["jsonrpc.request.id"] = str(request.id)
    session_id = _session_id(fiber) if request.transport == "http" else None
    if session_id is not None:
        attributes["mcp.session.id"] = session_id
    network = _NETWORK_TRANSPORTS.get(request.transport)
    if network is not None:
        attributes["network.transport"] = network
    record_arguments = fiber.get_ref(RecordToolArguments)
    target = _target(request.method, params, attributes, record_arguments=record_arguments)
    options: SpanOptions = {"kind": "server", "attributes": attributes}
    parent = _remote_parent(params)
    if parent is not None:
        options["parent"] = parent
        ambient = fiber.get_ref(ParentSpan)
        if ambient is not None:
            options["links"] = [SpanLink(ambient)]
    name = request.method if target is None else f"{request.method} {target}"
    return name, options


def _target(
    method: str, params: JsonObject, attributes: dict[str, object], *, record_arguments: bool
) -> str | None:
    """Adds the attributes of what the request names; the tool or prompt is returned, for
    the span's name."""
    match method:
        case "tools/call":
            attributes["gen_ai.operation.name"] = "execute_tool"
            if record_arguments and "arguments" in params:
                attributes["gen_ai.tool.call.arguments"] = stringify_tool_arguments(
                    params["arguments"]
                )
            name = params.get("name")
            if isinstance(name, str):
                attributes["gen_ai.tool.name"] = name
                return name
        case "prompts/get":
            name = params.get("name")
            if isinstance(name, str):
                attributes["gen_ai.prompt.name"] = name
                return name
        case "resources/read" | "resources/subscribe" | "resources/unsubscribe":
            # Resource URIs can be unbounded and sensitive, so they stay out of the name.
            uri = params.get("uri")
            if isinstance(uri, str):
                attributes["mcp.resource.uri"] = uri
        case _:
            pass
    return None


def _session_id(fiber: Fiber[Any, Any]) -> str | None:
    context = fiber._context  # pyright: ignore[reportPrivateUsage]
    found, http_request = context.lookup(HttpServerRequest)
    return http_request.headers.get(_SESSION_HEADER) if found else None


def _remote_parent(params: JsonObject) -> ExternalSpan | None:
    """The client's span from ``params._meta``: only its W3C ``traceparent`` is read, as
    other ``_meta`` members can carry protocol claims."""
    meta = params.get("_meta")
    if not isinstance(meta, Mapping):
        return None
    traceparent = meta.get("traceparent")
    if not isinstance(traceparent, str):
        return None
    return w3c(Headers({"traceparent": traceparent}))


def _end(
    fiber: Fiber[Any, Any],
    span: Span,
    *,
    request: RequestSpan,
    answered: Exit[Any, Any],
    last: Exit[Any, Any],
    state: _Answered,
) -> None:
    """Ends ``span``: classified by the response written, with ``answered``'s exit (the
    request's), or ``last`` when writing the response failed."""
    now = fiber.get_ref(Clock).now_nanos_unsafe() if fiber.get_ref(TracerTimingEnabled) else 0
    if "mcp.protocol.version" not in span.attributes:
        version = request.protocol_version()
        if version is not None:
            span.attribute("mcp.protocol.version", version)
    if state.error_code is not None:
        span.attribute("rpc.status_code", str(state.error_code))
        span.attribute("error.type", str(state.error_code))
        span.end(now, last if not isinstance(last, Success) else answered)
        return
    if not isinstance(last, Success) or state.reply is None:
        span.end(now, answered if isinstance(last, Success) else last)
        return
    code = _error_code(state.reply)
    if code is not None:
        span.attribute("rpc.status_code", str(code))
        if code in _REQUEST_ERROR_CODES:
            span.end(now, exit_void)
            return
        span.attribute("error.type", str(code))
        span.end(now, answered)
        return
    if request.method == "tools/call" and _is_tool_error(state.reply):
        span.attribute("error.type", "tool_error")
    span.end(now, answered)


def _error_code(reply: JsonObject) -> int | None:
    error = reply.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def _is_tool_error(reply: JsonObject) -> bool:
    result = reply.get("result")
    return isinstance(result, Mapping) and result.get("isError") is True


__all__ = ["RecordError", "RequestSpan", "traced"]
