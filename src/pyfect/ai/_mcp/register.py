"""Registering tools, resources and prompts with the ``McpServer``, and
asking the client for input (``elicit``)."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, LiteralString, Never, cast, overload

import pyfect as fx
from pyfect import _json_text, error_reporter
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.ai import ai_error as AiErr
from pyfect.ai import tool as Tool
from pyfect.ai._mcp.core import (
    CompletionHandler,
    McpServer,
    PromptEntry,
    RequestServices,
    ResourceEntry,
    ResourceTemplateEntry,
    ToolEntry,
    omit_request_services,
)
from pyfect.ai._mcp.tool_schema import tool_json_schema
from pyfect.ai.ai_error import AiError
from pyfect.ai.mcp_schema import (
    ELICIT_REQUEST_FORM_PARAMS,
    TOOL_JSON,
    Annotations,
    CallToolResult,
    ClientCapabilities,
    CompleteResult,
    CompletionContext,
    ContentBlock,
    ElicitationDeclined,
    ElicitRequestFormParams,
    GetPromptResult,
    InternalError,
    InvalidParams,
    JsonObject,
    McpError,
    McpRequestContext,
    McpServerClient,
    Param,
    Prompt,
    PromptArgument,
    PromptMessage,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    Role,
    ToolAnnotations,
)
from pyfect.ai.mcp_schema import Tool as McpTool
from pyfect.ai.toolkit import FailureOriginAnnotation, HandlerResult, Handlers, Toolkit
from pyfect.cause import Cause, Fail, UnhandledError
from pyfect.context import Context
from pyfect.effect import fail, fail_cause, gen, succeed, suspend
from pyfect.errors import TaggedError
from pyfect.http.find_my_way import Router, RouterConfig

INTERNAL_TOOL_ERROR_MESSAGE = "Tool execution failed due to an internal server error."
INTERNAL_ERROR_MESSAGE = "Internal server error"

type ResourceContent = ReadResourceResult | str | bytes
"""What a resource handler gives: a result, a text or binary contents."""


def _first_message(cause: Cause[object]) -> str:
    """The first error's text for the peer: a typed error that is no
    exception gives itself when a string, else its ``message`` (not its
    ``repr``, which shows every field)."""
    errors = cause.pretty_errors()
    if not errors:
        return "Internal error"
    first = errors[0]
    if isinstance(first, UnhandledError):
        error = first.error
        message = error if isinstance(error, str) else getattr(error, "message", None)
        return message if isinstance(message, str) else "Internal error"
    return str(first)


def _internal[A](effect: Effect[A, Any, Any]) -> Effect[A, InternalError, Any]:
    """``effect`` with every failure an ``InternalError`` of its message. A
    defect is logged and reported, and its text stays here: the peer gets
    ``INTERNAL_ERROR_MESSAGE``, as for a tool (Effect sends the defect's
    message)."""

    def answer(cause: Cause[object]) -> Effect[A, InternalError]:
        if not cause.has_dies:
            return fail(InternalError(_first_message(cause)))
        reported = fx.log_error(cause).and_then(error_reporter.report(cause))
        return reported.and_then(fail(InternalError(INTERNAL_ERROR_MESSAGE)))

    return effect.catch_cause(answer)


def _stringify(value: object) -> str:
    return _json_text.stringify(value)


def _tool_error_result(message: str) -> CallToolResult:
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def _content_of(encoded: object, *, void: bool) -> list[ContentBlock]:
    """The JSON text of an encoded result; none for a void tool's (Effect's
    ``undefined``, which Python's ``None`` cannot tell from ``null``)."""
    return [] if void and encoded is None else [{"type": "text", "text": _stringify(encoded)}]


def _error_message(error: object) -> str:
    """Effect's ``error.message`` of an ``Error`` (empty for anything else):
    a tagged error's ``message`` field or property, an exception's text."""
    if not isinstance(error, BaseException):
        return ""
    message = getattr(error, "message", None)
    if isinstance(message, str):
        return message
    return "" if isinstance(error, TaggedError) else str(error)


# --- tools ---------------------------------------------------------------------------------


def _object_schema(tool: Tool.AnyTool, *, strict: bool) -> Effect[JsonObject]:
    raw = tool.json_schema if isinstance(tool, Tool.Dynamic) else None
    schema = raw if raw is not None else tool_json_schema(tool.parameters_schema, strict=strict)
    if raw is None:
        problem = (
            "its parameters must encode to a JSON Schema with an object root "
            '(type: "object"), such as a Schema.Struct. Use Tool.EMPTY_PARAMS for a tool '
            "without parameters."
        )
    else:
        problem = 'its raw JSON Schema must have an object root (type: "object").'
    decode = cast(
        "Callable[[object], Effect[JsonObject, S.SchemaError]]", S.decode_unknown_effect(TOOL_JSON)
    )
    return decode(schema).catch_all(
        lambda error: fx.die(
            ValueError(
                f"McpServer cannot register tool '{tool.name}': {problem}\n\n{error.message}"
            )
        )
    )


def _tool_annotations(annotations: Context[Any]) -> ToolAnnotations:
    out: ToolAnnotations = {}
    title = annotations.get_option(Tool.Title)
    if title is not None:
        out["title"] = title.value
    out["readOnlyHint"] = annotations.get_unsafe(Tool.Readonly)
    out["destructiveHint"] = annotations.get_unsafe(Tool.Destructive)
    out["idempotentHint"] = annotations.get_unsafe(Tool.Idempotent)
    out["openWorldHint"] = annotations.get_unsafe(Tool.OpenWorld)
    return out


def _is_parameter_error(error: object) -> bool:
    return isinstance(error, AiError) and isinstance(
        error.reason, AiErr.ToolParameterValidationError
    )


def register_toolkit[N: LiteralString, RP, HE, R](
    toolkit: Toolkit[N, RP, HE, R],
) -> Effect[None, Never, McpServer | Handlers[N] | R]:
    """Serve every tool of ``toolkit`` (Effect's ``registerToolkit``).

    A tool's ``inputSchema`` is its parameters' JSON Schema, which must be
    an object; a success is the call's ``structuredContent`` and its JSON
    text. Invalid parameters are a JSON-RPC invalid-params error, a declared
    failure an ``isError`` result, and anything else is logged, reported and
    answered with a generic ``isError`` result."""

    @gen
    def register():
        server = yield from McpServer()
        kit = yield from toolkit
        services = omit_request_services((yield from fx.context()))

        def internal_tool_error(cause: Cause[object]) -> Effect[CallToolResult, InvalidParams]:
            if cause.has_interrupts_only:
                return fail_cause(cast("Cause[Never]", cause))
            return (
                fx.log_error(cause)
                .and_then(error_reporter.report(cause))
                .as_(_tool_error_result(INTERNAL_TOOL_ERROR_MESSAGE))
            )

        entries: list[ToolEntry] = []
        for tool in kit.tools.values():
            strict = tool.annotations.get_unsafe(Tool.Strict) is True
            if strict and isinstance(tool, Tool.Dynamic) and tool.json_schema is not None:
                yield from fx.die(
                    ValueError(
                        f"McpServer cannot strictly validate the raw JSON Schema for tool "
                        f"'{tool.name}'; use a schema instead"
                    )
                )
            input_schema = yield from _object_schema(tool, strict=strict)
            mcp_tool: McpTool = {
                "name": tool.name,
                "inputSchema": input_schema,
                "annotations": _tool_annotations(tool.annotations),
            }
            # Revisions before 2026-07-28 list it only for an object (projection).
            mcp_tool["outputSchema"] = tool_json_schema(tool.success_schema, strict=False)
            description = Tool.get_description(tool)
            if description is not None:
                mcp_tool["description"] = description
            meta = tool.annotations.get_option(Tool.Meta)
            if meta is not None:
                mcp_tool["_meta"] = cast("JsonObject", meta.value)
            entries.append(
                ToolEntry(
                    mcp_tool,
                    tool.annotations,
                    _tool_handler(kit, tool, services, internal_tool_error),
                )
            )
        # Every tool is checked before any is added: a toolkit registers whole or not at all.
        for entry in entries:
            yield from server.add_tool(entry)

    return register


def _tool_handler(
    kit: Any,
    tool: Tool.AnyTool,
    services: Context[Any],
    internal_tool_error: Callable[[Cause[object]], Effect[CallToolResult, InvalidParams]],
) -> Callable[[JsonObject | None], Effect[CallToolResult, InvalidParams, RequestServices]]:
    encode_failure = cast(
        "Callable[[object], Effect[object, S.SchemaError]]",
        S.encode_unknown_effect(tool.failure_schema),
    )
    is_declared_failure = S.is_(tool.failure_schema)
    void = tool.success_schema is S.Null
    strict = tool.annotations.get_unsafe(Tool.Strict) is True
    options: S.ParseOptions = {
        "errors": "all",
        "on_excess_property": "error" if strict else "ignore",
    }

    def declared_failure_result(error: object) -> Effect[CallToolResult, Any]:
        message = _error_message(error)
        if message:
            return succeed(_tool_error_result(message))
        return encode_failure(error).map(
            lambda encoded: cast(
                "CallToolResult", {"isError": True, "content": _content_of(encoded, void=False)}
            )
        )

    def handle_cause(cause: Cause[object]) -> Effect[CallToolResult, InvalidParams]:
        found = cause.find_recoverable_error()
        if isinstance(found, Fail):
            error = found.error
            origin = Context(dict(found.annotations)).get_or_else(
                FailureOriginAnnotation, lambda: None
            )
            if origin == "parameters" and _is_parameter_error(error):
                return fail(InvalidParams(cast("AiError", error).reason.message))
            if origin == "handler" and is_declared_failure(error):
                return declared_failure_result(error).catch_cause(internal_tool_error)
        return internal_tool_error(cause)

    def to_result(result: HandlerResult) -> Effect[CallToolResult, Any]:
        if result.is_failure and result.failure_origin != "handler":
            origin = Context.make(FailureOriginAnnotation, result.failure_origin or "result")
            return fail_cause(Cause((Fail(result.result),)).annotate(origin))
        out: CallToolResult = {
            "isError": result.is_failure,
            "content": _content_of(result.encoded_result, void=void),
        }
        if not result.is_failure and not (void and result.encoded_result is None):
            out["structuredContent"] = cast("Any", result.encoded_result)
        return succeed(out)

    def handle(
        arguments: JsonObject | None,
    ) -> Effect[CallToolResult, InvalidParams, RequestServices]:
        called: Effect[Any, Any, Any] = kit.handle(tool.name, arguments or {}, None, options)
        return (
            called.flat_map(lambda results: results.run_last())
            .flat_map(fx.from_option)
            .flat_map(to_result)
            .catch_cause(handle_cause)
            .pipe(fx.provide_context(services))
        )

    return handle


# --- resources -----------------------------------------------------------------------------


def _resolve_content(uri: str, content: ResourceContent) -> ReadResourceResult:
    if isinstance(content, str):
        return {"contents": [{"uri": uri, "text": content}]}
    if isinstance(content, bytes):
        return {"contents": [{"uri": uri, "blob": base64.b64encode(content).decode("ascii")}]}
    return content


def _resource_annotations(
    audience: Sequence[Role] | None, priority: float | None
) -> Annotations | None:
    annotations: Annotations = {}
    if audience is not None:
        annotations["audience"] = list(audience)
    if priority is not None:
        annotations["priority"] = priority
    return annotations or None


def _described[T: Mapping[str, Any]](
    value: T,
    *,
    title: str | None,
    description: str | None,
    mime_type: str | None,
    annotations: Annotations | None,
) -> T:
    out = cast("dict[str, Any]", value)
    for key, item in (
        ("title", title),
        ("description", description),
        ("mimeType", mime_type),
        ("annotations", annotations),
    ):
        if item is not None:
            out[key] = item
    return value


def register_resource[E = Never, R = Never](
    *,
    uri: str,
    name: str,
    content: Effect[ResourceContent, E, R],
    title: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
    audience: Sequence[Role] | None = None,
    priority: float | None = None,
    annotations: Context[Never] | None = None,
) -> Effect[None, Never, McpServer | R]:
    """Serve ``content`` at ``uri``: a string is its text, bytes its blob.
    A failure is answered as an internal error with its message, a defect
    with a generic one."""
    require_effect(content, "content")

    @gen
    def register():
        services = omit_request_services((yield from fx.context()))
        server = yield from McpServer()
        resource: Resource = _described(
            {"uri": uri, "name": name},
            title=title,
            description=description,
            mime_type=mime_type,
            annotations=_resource_annotations(audience, priority),
        )
        handle: Effect[ReadResourceResult, McpError, Any] = _internal(
            content.map(lambda c: _resolve_content(uri, c))
        ).pipe(fx.provide_context(services))
        yield from server.add_resource(
            ResourceEntry(resource, annotations or Context.empty(), handle)
        )

    return register


@dataclass(frozen=True, slots=True)
class UriTemplate[*Ts]:
    """A resource URI template with typed parameters (Effect's tagged
    template ``registerResource`...```), made by ``uri_template``. A URI is
    matched as Effect matches it, by find-my-way on ``/`` + the URI: each
    parameter one percent-decoded path segment, the query and fragment
    left out, duplicate and trailing slashes ignored."""

    uri_template: str
    names: tuple[str, ...]
    schemas: tuple[S.Top, ...]
    router: Router[None]

    def match(self, uri: str) -> Mapping[str, str] | None:
        found = self.router.find("GET", f"/{uri}")
        if found is None:
            return None
        return {self.names[int(index)]: value for index, value in found.params.items()}


def _router_text(text: str) -> str:
    # Effect's ``segment.replace(":", "::")``: JavaScript replaces the first one only.
    return text.replace(":", "::", 1)


type _Part[A] = S.Codec[A, Any, Any, Any] | Param[A]


@overload
def uri_template[A](s0: str, p0: _Part[A], s1: str = "", /) -> UriTemplate[A]: ...
@overload
def uri_template[A, B](
    s0: str, p0: _Part[A], s1: str, p1: _Part[B], s2: str = "", /
) -> UriTemplate[A, B]: ...
@overload
def uri_template[A, B, C](
    s0: str, p0: _Part[A], s1: str, p1: _Part[B], s2: str, p2: _Part[C], s3: str = "", /
) -> UriTemplate[A, B, C]: ...
def uri_template(*parts: Any) -> UriTemplate[*tuple[Any, ...]]:
    """A URI template of literal text and parameters, in order::

        uri_template("file:///notes/", S.String)              # file:///notes/{param0}
        uri_template("users://", param("id", S.Int), "/profile")

    A parameter is one path segment, percent-decoded, then decoded from its
    text by its schema; a bare schema is named ``param<index>``; two
    parameters need text between them."""
    texts: list[str] = [parts[0]]
    names: list[str] = []
    schemas: list[S.Top] = []
    path = _router_text(parts[0])
    for index in range(1, len(parts), 2):
        part = parts[index]
        name = part.name if isinstance(part, Param) else f"param{index // 2}"
        schema: S.Top = cast("Param[Any]", part).schema if isinstance(part, Param) else part
        literal = parts[index + 1] if index + 1 < len(parts) else ""
        names.append(name)
        schemas.append(S.to_codec_string_tree(cast("S.Codec[Any, Any, Any, Any]", schema)))
        texts.append(f"{{{name}}}{literal}")
        if literal == "" and index + 2 < len(parts):
            raise ValueError(f"uri_template: parameter {name!r} needs text before the next one")
        path += f":{index // 2}{_router_text(literal)}"
    router = Router[None](RouterConfig(case_sensitive=True))
    router.on("GET", f"/{path}", None)
    return UriTemplate("".join(texts), tuple(names), tuple(schemas), router)


type CompletionFunction = Callable[[str, CompletionContext], Effect[Sequence[Any], Any, Any]]
"""Completes one argument: the values for what the user typed so far."""


def _completion(
    schema: S.Top, complete: CompletionFunction, services: Context[Any]
) -> CompletionHandler:
    encode = cast(
        "Callable[[object], Effect[list[str], S.SchemaError]]",
        S.encode_unknown_effect(S.List(cast("S.Codec[Any, Any, Any, Any]", schema))),
    )

    def handler(
        value: str, context: CompletionContext
    ) -> Effect[CompleteResult, InternalError, Any]:
        completed: Effect[CompleteResult, Any, Any] = (
            suspend(lambda: complete(value, context))
            .flat_map(encode)
            .map(
                lambda values: cast(
                    "CompleteResult",
                    {"completion": {"values": values, "total": len(values), "hasMore": False}},
                )
            )
        )
        return _internal(completed).pipe(fx.provide_context(services))

    return handler


def register_resource_template[*Ts, E = Never, R = Never](
    template: UriTemplate[*Ts],
    *,
    name: str,
    content: Callable[[str, *Ts], Effect[ResourceContent, E, R]],
    completion: Mapping[str, CompletionFunction] | None = None,
    title: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
    audience: Sequence[Role] | None = None,
    priority: float | None = None,
    annotations: Context[Never] | None = None,
) -> Effect[None, Never, McpServer | R]:
    """Serve the URIs ``template`` matches: ``content`` gets the URI and
    the decoded parameters. ``completion`` completes parameters by name."""

    @gen
    def register():
        services = omit_request_services((yield from fx.context()))
        server = yield from McpServer()
        decode = cast(
            "Callable[[object], Effect[tuple[Any, ...], S.SchemaError]]",
            S.decode_unknown_effect(S.Tuple(*cast("Any", template.schemas))),
        )
        resource_template: ResourceTemplate = _described(
            {"uriTemplate": template.uri_template, "name": name},
            title=title,
            description=description,
            mime_type=mime_type,
            annotations=_resource_annotations(audience, priority),
        )
        by_name = dict(zip(template.names, template.schemas, strict=True))
        completions = {
            param_name: _completion(by_name[param_name], complete, services)
            for param_name, complete in (completion or {}).items()
        }

        def handle(
            uri: str, params: Mapping[str, str]
        ) -> Effect[ReadResourceResult, McpError, Any]:
            values = [params[n] for n in template.names]
            read: Effect[ReadResourceResult, McpError, Any] = (
                decode(values)
                .map_error(lambda error: InvalidParams(error.message))
                .flat_map(
                    lambda decoded: _internal(
                        suspend(lambda: cast("Any", content)(uri, *decoded)).map(
                            lambda c: _resolve_content(uri, c)
                        )
                    )
                )
            )
            return read.pipe(fx.provide_context(services))

        yield from server.add_resource_template(
            ResourceTemplateEntry(
                resource_template,
                annotations or Context.empty(),
                template.match,
                completions,
                handle,
            )
        )

    return register


# --- prompts -------------------------------------------------------------------------------


def _prompt_arguments(parameters: S.Top | None) -> list[PromptArgument]:
    if parameters is None:
        return []
    document = S.to_json_schema_document(parameters).schema
    properties = cast("Mapping[str, Mapping[str, Any]]", document.get("properties") or {})
    required = set(cast("list[str]", document.get("required") or []))
    arguments: list[PromptArgument] = []
    for arg_name, schema in properties.items():
        argument: PromptArgument = {"name": arg_name, "required": arg_name in required}
        description = schema.get("description")
        if isinstance(description, str):
            argument["description"] = description
        arguments.append(argument)
    return arguments


def register_prompt[P = Mapping[str, Never], E = Never, R = Never](
    *,
    name: str,
    content: Callable[[P], Effect[Sequence[PromptMessage] | str, E, R]],
    parameters: S.Codec[P, Any, Any, Any] | None = None,
    completion: Mapping[str, CompletionFunction] | None = None,
    title: str | None = None,
    description: str | None = None,
    annotations: Context[Never] | None = None,
) -> Effect[None, Never, McpServer | R]:
    """Serve a prompt: ``content`` gets the arguments ``parameters`` decodes
    (a struct of strings) and gives messages, or a string as one user
    message. ``completion`` completes arguments by name."""

    @gen
    def register():
        services = omit_request_services((yield from fx.context()))
        server = yield from McpServer()
        prompt: Prompt = {"name": name, "arguments": _prompt_arguments(parameters)}
        if title is not None:
            prompt["title"] = title
        if description is not None:
            prompt["description"] = description
        decode: Callable[[object], Effect[Any, S.SchemaError]] = (
            cast("Any", S.decode_unknown_effect(parameters))
            if parameters is not None
            else lambda _: succeed({})
        )
        fields: Mapping[str, Any] = getattr(parameters, "fields", {})
        completions = {
            argument: _completion(fields[argument], complete, services)
            for argument, complete in (completion or {}).items()
        }

        def messages_of(messages: Sequence[PromptMessage] | str) -> GetPromptResult:
            listed: list[PromptMessage] = (
                [{"role": "user", "content": {"type": "text", "text": messages}}]
                if isinstance(messages, str)
                else list(messages)
            )
            result: GetPromptResult = {"messages": listed}
            if description is not None:
                result["description"] = description
            return result

        def handle(arguments: Mapping[str, str]) -> Effect[GetPromptResult, McpError, Any]:
            got: Effect[GetPromptResult, McpError, Any] = (
                decode(dict(arguments))
                .map_error(lambda error: InvalidParams(error.message))
                .flat_map(lambda decoded: _internal(suspend(lambda: content(decoded))))
                .map(messages_of)
            )
            return got.pipe(fx.provide_context(services))

        yield from server.add_prompt(
            PromptEntry(prompt, annotations or Context.empty(), completions, handle)
        )

    return register


# --- elicitation ---------------------------------------------------------------------------


def elicit[A, R = Never](
    *, message: str, schema: S.Codec[A, Any, R, Any]
) -> Effect[A, ElicitationDeclined, McpServerClient | R]:
    """Ask the user, through the client, for input matching ``schema``.
    Declining fails with ``ElicitationDeclined`` (so does a client that
    cannot be asked), cancelling interrupts, and accepted content is
    decoded with ``schema``."""

    @gen
    def run():
        client = yield from McpServerClient()
        reverse = yield from client.get_client
        decode_request = cast(
            "Callable[[object], Effect[ElicitRequestFormParams, S.SchemaError]]",
            S.decode_unknown_effect(ELICIT_REQUEST_FORM_PARAMS),
        )
        request = yield from decode_request(
            {
                "mode": "form",
                "message": message,
                "requestedSchema": tool_json_schema(schema, strict=False),
            }
        ).or_die()
        result = yield from reverse.elicit(request).catch_cause(
            lambda cause: fail(ElicitationDeclined(request, cause.squash()))
        )
        action: Literal["accept", "decline", "cancel"] = result["action"]
        if action == "cancel":
            return (yield from fx.interrupt())
        if action == "decline":
            return (yield from fail(ElicitationDeclined(request)))
        decode = cast(
            "Callable[[object], Effect[A, S.SchemaError, R]]", S.decode_unknown_effect(schema)
        )
        return (yield from decode(result.get("content", {})).or_die())

    return run


def client_capabilities() -> Effect[ClientCapabilities, Never, McpRequestContext]:
    """The current request's client capabilities."""
    return McpRequestContext().map(lambda context: context.client_capabilities)
