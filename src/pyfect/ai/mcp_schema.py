"""The Model Context Protocol's messages, errors and request services
(Effect's ``McpSchema``).

MCP is a JSON-RPC protocol, so its values are ``TypedDict`` s in the wire
form, with MCP's camelCase keys (``inputSchema``, ``structuredContent``);
each has a schema named in capitals (``TOOL`` for ``Tool``) that validates
it. Binary data (images, audio, blobs) stays base64 text, as on the wire.

``Method`` describes one request or notification: its name, the schema of
its params and of its result (``CREATE_MESSAGE.payload_schema``). The MCP
errors (``InvalidParams``, ``InternalError``, ...) carry their JSON-RPC
``code``. ``McpRequestContext`` is the request a handler serves and
``McpServerClient`` the session it belongs to (for requests to the client,
such as ``mcp_server.elicit``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    Never,
    NotRequired,
    TypedDict,
    TypeVar,
    cast,
    overload,
)

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect.context import Tag
from pyfect.errors import TaggedError

# --- JSON-RPC ---------------------------------------------------------------------------

PARSE_ERROR_CODE = -32700
INVALID_REQUEST_ERROR_CODE = -32600
METHOD_NOT_FOUND_ERROR_CODE = -32601
INVALID_PARAMS_ERROR_CODE = -32602
INTERNAL_ERROR_CODE = -32603
HEADER_MISMATCH_ERROR_CODE = -32020
MISSING_REQUIRED_CLIENT_CAPABILITY_ERROR_CODE = -32021
UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE = -32022
RESOURCE_NOT_FOUND_ERROR_CODE = -32002
"""What revisions before 2026-07-28 answer an unknown resource with."""

type RequestId = str | int | float
"""A JSON-RPC id: a string or a finite number, never a boolean. Read one
from a message only through ``parse_request_id``."""
type JsonObject = dict[str, JsonValue]

REQUEST_ID = S.Union(S.String, S.Finite)


def parse_request_id(value: object) -> RequestId | None:
    """``value`` as a request id (Effect's ``RequestId``: a string or a finite
    number), else ``None``. ``True`` is not ``1``, and a list or an object
    is no id at all."""
    kind = type(value)
    if kind is str or kind is int:
        return cast("str | int", value)
    if kind is float and math.isfinite(cast("float", value)):
        return cast("float", value)
    return None


JSON_OBJECT = S.Record(S.String, S.Json)


class JsonRpcRequest(TypedDict):
    """A JSON-RPC 2.0 request: an id, a method and its params."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    method: str
    params: NotRequired[JsonObject]


class JsonRpcNotification(TypedDict):
    """A JSON-RPC 2.0 notification: a method and its params, with no id and no reply."""

    jsonrpc: Literal["2.0"]
    method: str
    params: NotRequired[JsonObject]


class JsonRpcErrorObject(TypedDict):
    """The error of a JSON-RPC 2.0 response: a code, a message and optional data."""

    code: int
    message: str
    data: NotRequired[JsonValue]


class JsonRpcSuccess(TypedDict):
    """A successful JSON-RPC 2.0 response: the request's id and its result."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    result: JsonObject


class JsonRpcError(TypedDict):
    """A failed JSON-RPC 2.0 response: the request's id and the error."""

    jsonrpc: Literal["2.0"]
    id: RequestId | None
    error: JsonRpcErrorObject


type JsonRpcResponse = JsonRpcSuccess | JsonRpcError
type JsonRpcMessage = JsonRpcRequest | JsonRpcNotification | JsonRpcResponse

JSON_RPC_REQUEST = S.Struct(JsonRpcRequest, id=REQUEST_ID, params=JSON_OBJECT)
JSON_RPC_NOTIFICATION = S.Struct(JsonRpcNotification, params=JSON_OBJECT)
JSON_RPC_ERROR_OBJECT = S.Struct(JsonRpcErrorObject, data=S.Json)
JSON_RPC_SUCCESS = S.Struct(JsonRpcSuccess, id=REQUEST_ID, result=JSON_OBJECT)
JSON_RPC_ERROR = S.Struct(JsonRpcError, id=S.NullOr(REQUEST_ID), error=JSON_RPC_ERROR_OBJECT)
JSON_RPC_RESPONSE = S.Union(JSON_RPC_SUCCESS, JSON_RPC_ERROR)
JSON_RPC_MESSAGE = S.Union(
    JSON_RPC_REQUEST, JSON_RPC_NOTIFICATION, JSON_RPC_SUCCESS, JSON_RPC_ERROR
)


# --- metadata ---------------------------------------------------------------------------


class _ProgressMeta(TypedDict):
    progressToken: NotRequired[RequestId]


REQUEST_META_OBJECT = S.StructWithRest(
    S.Struct(_ProgressMeta, progressToken=REQUEST_ID), S.Record(S.String, S.Json)
)


class RequestMeta(TypedDict):
    """A request's ``_meta``: a progress token and any other keys."""

    _meta: NotRequired[dict[str, JsonValue]]


REQUEST_META = S.Struct(RequestMeta, _meta=REQUEST_META_OBJECT)

# --- identity and capabilities ----------------------------------------------------------


class Icon(TypedDict):
    """An icon for an MCP server, tool, resource or prompt: its URL, type, sizes and theme."""

    src: str
    mimeType: NotRequired[str]
    sizes: NotRequired[list[str]]
    theme: NotRequired[Literal["light", "dark"]]


ICON = S.Struct(Icon)


class Implementation(TypedDict):
    """A client's or server's name and version."""

    name: str
    version: str
    title: NotRequired[str]
    icons: NotRequired[list[Icon]]
    description: NotRequired[str]
    websiteUrl: NotRequired[str]


IMPLEMENTATION = S.Struct(Implementation)


class ListChanged(TypedDict):
    """An MCP capability that can notify when its list changes."""

    listChanged: NotRequired[bool]


class ResourcesCapability(TypedDict):
    """The MCP resources capability: whether subscriptions and list change notices work."""

    subscribe: NotRequired[bool]
    listChanged: NotRequired[bool]


class ClientCapabilities(TypedDict, total=False):
    """What an MCP client supports: roots, sampling, elicitation and extensions."""

    experimental: dict[str, JsonObject]
    extensions: dict[str, JsonValue]
    roots: ListChanged
    sampling: JsonObject
    elicitation: JsonObject


class ServerCapabilities(TypedDict, total=False):
    """What an MCP server supports: tools, resources, prompts, logging and completions."""

    experimental: dict[str, JsonObject]
    extensions: dict[str, JsonValue]
    logging: JsonObject
    completions: JsonObject
    prompts: ListChanged
    resources: ResourcesCapability
    tools: ListChanged


CLIENT_CAPABILITIES = S.Struct(
    ClientCapabilities,
    experimental=S.Record(S.String, JSON_OBJECT),
    extensions=S.Record(S.String, S.Json),
    sampling=JSON_OBJECT,
    elicitation=JSON_OBJECT,
)
SERVER_CAPABILITIES = S.Struct(
    ServerCapabilities,
    experimental=S.Record(S.String, JSON_OBJECT),
    extensions=S.Record(S.String, S.Json),
    logging=JSON_OBJECT,
    completions=JSON_OBJECT,
)


class InitializeParams(TypedDict):
    """An MCP ``initialize`` request: the protocol version, client capabilities and info."""

    protocolVersion: str
    capabilities: ClientCapabilities
    clientInfo: Implementation
    _meta: NotRequired[dict[str, JsonValue]]


INITIALIZE_PARAMS = S.Struct(
    InitializeParams, capabilities=CLIENT_CAPABILITIES, _meta=REQUEST_META_OBJECT
)


class InitializeResult(TypedDict):
    """The reply to MCP ``initialize``: the protocol version, server capabilities and info."""

    protocolVersion: str
    capabilities: ServerCapabilities
    serverInfo: Implementation
    instructions: NotRequired[str]


INITIALIZE_RESULT = S.Struct(InitializeResult, capabilities=SERVER_CAPABILITIES)

# --- content ----------------------------------------------------------------------------

type Role = Literal["user", "assistant"]


class Annotations(TypedDict, total=False):
    """Hints on MCP content: its audience, priority and when it last changed."""

    audience: list[Role]
    priority: float
    lastModified: str


ANNOTATIONS = S.Struct(Annotations)


class TextContent(TypedDict):
    """MCP text content."""

    type: Literal["text"]
    text: str
    annotations: NotRequired[Annotations]
    _meta: NotRequired[JsonObject]


class ImageContent(TypedDict):
    """MCP image content, as base64 data with its MIME type."""

    type: Literal["image"]
    data: str
    mimeType: str
    annotations: NotRequired[Annotations]
    _meta: NotRequired[JsonObject]


class AudioContent(TypedDict):
    """MCP audio content, as base64 data with its MIME type."""

    type: Literal["audio"]
    data: str
    mimeType: str
    annotations: NotRequired[Annotations]
    _meta: NotRequired[JsonObject]


class ResourceLink(TypedDict):
    """MCP content that links to a resource by URI instead of embedding it."""

    type: Literal["resource_link"]
    uri: str
    name: str
    title: NotRequired[str]
    description: NotRequired[str]
    mimeType: NotRequired[str]
    size: NotRequired[int]
    annotations: NotRequired[Annotations]
    _meta: NotRequired[JsonObject]


class TextResourceContents(TypedDict):
    """The text contents of an MCP resource."""

    uri: str
    text: str
    mimeType: NotRequired[str]
    _meta: NotRequired[JsonObject]


class BlobResourceContents(TypedDict):
    """The binary contents of an MCP resource, as base64."""

    uri: str
    blob: str
    mimeType: NotRequired[str]
    _meta: NotRequired[JsonObject]


type ResourceContents = TextResourceContents | BlobResourceContents


class EmbeddedResource(TypedDict):
    """MCP content that embeds a resource's contents."""

    type: Literal["resource"]
    resource: ResourceContents
    annotations: NotRequired[Annotations]
    _meta: NotRequired[JsonObject]


type ContentBlock = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource

_META = {"_meta": JSON_OBJECT}
TEXT_CONTENT = S.Struct(TextContent, **_META)
IMAGE_CONTENT = S.Struct(ImageContent, **_META)
AUDIO_CONTENT = S.Struct(AudioContent, **_META)
RESOURCE_LINK = S.Struct(ResourceLink, **_META)
TEXT_RESOURCE_CONTENTS = S.Struct(TextResourceContents, **_META)
BLOB_RESOURCE_CONTENTS = S.Struct(BlobResourceContents, **_META)
RESOURCE_CONTENTS = S.Union(TEXT_RESOURCE_CONTENTS, BLOB_RESOURCE_CONTENTS)
EMBEDDED_RESOURCE = S.Struct(EmbeddedResource, resource=RESOURCE_CONTENTS, **_META)
CONTENT_BLOCK = S.Union(
    TEXT_CONTENT, IMAGE_CONTENT, AUDIO_CONTENT, RESOURCE_LINK, EMBEDDED_RESOURCE
)

# --- tools ------------------------------------------------------------------------------


class ToolAnnotations(TypedDict, total=False):
    """Hints about an MCP tool: its title, and if it is read-only, destructive or idempotent."""

    title: str
    readOnlyHint: bool
    destructiveHint: bool
    idempotentHint: bool
    openWorldHint: bool


TOOL_ANNOTATIONS = S.Struct(ToolAnnotations)

_PROPERTY_SCHEMA = S.Union(JSON_OBJECT, S.Boolean)


class _ToolJsonFields(TypedDict):
    type: Literal["object"]
    properties: NotRequired[dict[str, JsonObject | bool]]
    required: NotRequired[list[str]]


TOOL_JSON = S.StructWithRest(
    S.Struct(_ToolJsonFields, properties=S.Record(S.String, _PROPERTY_SCHEMA)),
    S.Record(S.String, S.Json),
)
"""A tool's input schema: a JSON Schema object whose ``properties`` are
schemas (objects) or booleans (JSON Schema 2020-12, 4.3.2)."""

type ToolJson = dict[str, Any]
"""A JSON Schema with ``"type": "object"`` at its root."""


class Tool(TypedDict):
    """A tool a server offers."""

    name: str
    inputSchema: ToolJson
    title: NotRequired[str]
    description: NotRequired[str]
    outputSchema: NotRequired[ToolJson]
    annotations: NotRequired[ToolAnnotations]
    icons: NotRequired[list[Icon]]
    execution: NotRequired[JsonObject]
    _meta: NotRequired[JsonObject]


TOOL = S.Struct(
    Tool, inputSchema=TOOL_JSON, outputSchema=JSON_OBJECT, execution=JSON_OBJECT, **_META
)


class CallToolResult(TypedDict):
    """The result of an MCP tool call: content blocks, structured content and an error flag."""

    content: list[ContentBlock]
    structuredContent: NotRequired[JsonValue]
    isError: NotRequired[bool]
    _meta: NotRequired[JsonObject]


CALL_TOOL_RESULT = S.Struct(
    CallToolResult, content=S.List(CONTENT_BLOCK), structuredContent=S.Json, **_META
)


class CallToolParams(TypedDict):
    """An MCP ``tools/call`` request: the tool's name and its arguments."""

    name: str
    arguments: NotRequired[JsonObject]
    _meta: NotRequired[dict[str, JsonValue]]


CALL_TOOL_PARAMS = S.Struct(CallToolParams, arguments=JSON_OBJECT, _meta=REQUEST_META_OBJECT)

# --- resources --------------------------------------------------------------------------


class Resource(TypedDict):
    """An MCP resource a server lists: its URI, name, description and MIME type."""

    uri: str
    name: str
    title: NotRequired[str]
    description: NotRequired[str]
    mimeType: NotRequired[str]
    size: NotRequired[int]
    annotations: NotRequired[Annotations]
    icons: NotRequired[list[Icon]]
    _meta: NotRequired[JsonObject]


class ResourceTemplate(TypedDict):
    """An MCP resource template: a URI template for a family of resources."""

    uriTemplate: str
    name: str
    title: NotRequired[str]
    description: NotRequired[str]
    mimeType: NotRequired[str]
    annotations: NotRequired[Annotations]
    icons: NotRequired[list[Icon]]
    _meta: NotRequired[JsonObject]


class ReadResourceResult(TypedDict):
    """The reply to MCP ``resources/read``: the resource's contents."""

    contents: list[ResourceContents]
    _meta: NotRequired[JsonObject]


RESOURCE = S.Struct(Resource, **_META)
RESOURCE_TEMPLATE = S.Struct(ResourceTemplate, **_META)
READ_RESOURCE_RESULT = S.Struct(ReadResourceResult, contents=S.List(RESOURCE_CONTENTS), **_META)

# --- prompts ----------------------------------------------------------------------------


class PromptArgument(TypedDict):
    """An argument an MCP prompt takes: its name, description and whether it is required."""

    name: str
    title: NotRequired[str]
    description: NotRequired[str]
    required: NotRequired[bool]


class Prompt(TypedDict):
    """An MCP prompt a server lists: its name, description and arguments."""

    name: str
    title: NotRequired[str]
    description: NotRequired[str]
    arguments: NotRequired[list[PromptArgument]]
    icons: NotRequired[list[Icon]]
    _meta: NotRequired[JsonObject]


class PromptMessage(TypedDict):
    """A message in an MCP prompt: a role and its content."""

    role: Role
    content: ContentBlock


class GetPromptResult(TypedDict):
    """The reply to MCP ``prompts/get``: the prompt's messages."""

    messages: list[PromptMessage]
    description: NotRequired[str]
    _meta: NotRequired[JsonObject]


PROMPT_ARGUMENT = S.Struct(PromptArgument)
PROMPT = S.Struct(Prompt, **_META)
PROMPT_MESSAGE = S.Struct(PromptMessage, content=CONTENT_BLOCK)
GET_PROMPT_RESULT = S.Struct(GetPromptResult, messages=S.List(PROMPT_MESSAGE), **_META)

# --- completions ------------------------------------------------------------------------


class PromptReference(TypedDict):
    """A reference to an MCP prompt by name, for argument completion."""

    type: Literal["ref/prompt"]
    name: str
    title: NotRequired[str]


class ResourceTemplateReference(TypedDict):
    """A reference to an MCP resource template by URI, for argument completion."""

    type: Literal["ref/resource"]
    uri: str


class CompleteArgument(TypedDict):
    """The argument being completed in MCP ``completion/complete``: its name and value so far."""

    name: str
    value: str


class CompletionContext(TypedDict, total=False):
    """Values the client already chose for other arguments."""

    arguments: dict[str, str]


class CompleteParams(TypedDict):
    """An MCP ``completion/complete`` request: what to complete and the context."""

    ref: PromptReference | ResourceTemplateReference
    argument: CompleteArgument
    context: NotRequired[CompletionContext]
    _meta: NotRequired[dict[str, JsonValue]]


class Completion(TypedDict):
    """MCP completion values, with the total count and whether more exist."""

    values: list[str]
    total: NotRequired[int]
    hasMore: NotRequired[bool]


class CompleteResult(TypedDict):
    """The reply to MCP ``completion/complete``."""

    completion: Completion
    _meta: NotRequired[JsonObject]


COMPLETE_PARAMS = S.Struct(CompleteParams, _meta=REQUEST_META_OBJECT)
COMPLETE_RESULT = S.Struct(CompleteResult, **_META)

# --- logging ----------------------------------------------------------------------------

type LoggingLevel = Literal[
    "debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"
]
LOGGING_LEVEL = S.Literals(
    "debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"
)
LOGGING_LEVELS: tuple[LoggingLevel, ...] = (
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
    "alert",
    "emergency",
)
"""The levels from least to most severe."""

# --- sampling ---------------------------------------------------------------------------


class SamplingMessage(TypedDict):
    """A message in an MCP sampling request: a role and its content."""

    role: Role
    content: JsonValue
    _meta: NotRequired[JsonObject]


class CreateMessageParams(TypedDict):
    """An MCP ``sampling/createMessage`` request: messages, max tokens and model hints."""

    messages: list[SamplingMessage]
    maxTokens: int
    modelPreferences: NotRequired[JsonObject]
    systemPrompt: NotRequired[str]
    includeContext: NotRequired[Literal["none", "thisServer", "allServers"]]
    temperature: NotRequired[float]
    stopSequences: NotRequired[list[str]]
    metadata: NotRequired[JsonObject]
    tools: NotRequired[list[Tool]]
    toolChoice: NotRequired[JsonObject]
    _meta: NotRequired[dict[str, JsonValue]]


SAMPLING_MESSAGE = S.Struct(SamplingMessage, content=S.Json, **_META)
CREATE_MESSAGE_PARAMS = S.Struct(
    CreateMessageParams,
    messages=S.List(SAMPLING_MESSAGE),
    modelPreferences=JSON_OBJECT,
    metadata=JSON_OBJECT,
    tools=S.List(TOOL),
    toolChoice=JSON_OBJECT,
    _meta=REQUEST_META_OBJECT,
)


class CreateMessageResult(TypedDict):
    """The reply to MCP ``sampling/createMessage``: the model's message and stop reason."""

    role: Role
    content: JsonValue
    model: str
    stopReason: NotRequired[str]
    _meta: NotRequired[JsonObject]


CREATE_MESSAGE_RESULT = S.Struct(CreateMessageResult, content=S.Json, **_META)

# --- roots ------------------------------------------------------------------------------


class Root(TypedDict):
    """An MCP root: a URI the client lets the server work within."""

    uri: str
    name: NotRequired[str]
    _meta: NotRequired[JsonObject]


class ListRootsResult(TypedDict):
    """The reply to MCP ``roots/list``: the client's roots."""

    roots: list[Root]
    _meta: NotRequired[JsonObject]


ROOT = S.Struct(Root, **_META)
LIST_ROOTS_RESULT = S.Struct(ListRootsResult, roots=S.List(ROOT), **_META)

# --- elicitation ------------------------------------------------------------------------


class ElicitationString(TypedDict):
    """A string field in an MCP elicitation form, with its length limits and format."""

    type: Literal["string"]
    title: NotRequired[str]
    description: NotRequired[str]
    minLength: NotRequired[int]
    maxLength: NotRequired[int]
    format: NotRequired[Literal["email", "uri", "date", "date-time"]]
    default: NotRequired[str]


class ElicitationNumber(TypedDict):
    """A number field in an MCP elicitation form, with its bounds."""

    type: Literal["number", "integer"]
    title: NotRequired[str]
    description: NotRequired[str]
    minimum: NotRequired[float]
    maximum: NotRequired[float]
    default: NotRequired[float]


class ElicitationBoolean(TypedDict):
    """A yes-or-no field in an MCP elicitation form."""

    type: Literal["boolean"]
    title: NotRequired[str]
    description: NotRequired[str]
    default: NotRequired[bool]


class UntitledSingleSelectEnum(TypedDict):
    """An MCP elicitation field that picks one of a list of values."""

    type: Literal["string"]
    enum: list[str]
    title: NotRequired[str]
    description: NotRequired[str]
    default: NotRequired[str]


class EnumOption(TypedDict):
    """One option of a titled MCP elicitation enum: its value and title."""

    const: str
    title: str


class TitledSingleSelectEnum(TypedDict):
    """An MCP elicitation field that picks one of a list of titled options."""

    type: Literal["string"]
    oneOf: list[EnumOption]
    title: NotRequired[str]
    description: NotRequired[str]
    default: NotRequired[str]


class LegacyTitledEnum(TypedDict):
    """An MCP elicitation enum with titles in ``enumNames``, the older form."""

    type: Literal["string"]
    enum: list[str]
    enumNames: list[str]
    title: NotRequired[str]
    description: NotRequired[str]
    default: NotRequired[str]


class _UntitledItems(TypedDict):
    type: Literal["string"]
    enum: list[str]


class _TitledItems(TypedDict):
    anyOf: list[EnumOption]


class UntitledMultiSelectEnum(TypedDict):
    """An MCP elicitation field that picks several of a list of values."""

    type: Literal["array"]
    items: _UntitledItems
    title: NotRequired[str]
    description: NotRequired[str]
    minItems: NotRequired[int]
    maxItems: NotRequired[int]
    default: NotRequired[list[str]]


class TitledMultiSelectEnum(TypedDict):
    """An MCP elicitation field that picks several of a list of titled options."""

    type: Literal["array"]
    items: _TitledItems
    title: NotRequired[str]
    description: NotRequired[str]
    minItems: NotRequired[int]
    maxItems: NotRequired[int]
    default: NotRequired[list[str]]


type PrimitiveSchemaDefinition = (
    LegacyTitledEnum
    | UntitledSingleSelectEnum
    | TitledSingleSelectEnum
    | UntitledMultiSelectEnum
    | TitledMultiSelectEnum
    | ElicitationString
    | ElicitationNumber
    | ElicitationBoolean
)

PRIMITIVE_SCHEMA_DEFINITION = S.Union(
    S.Struct(LegacyTitledEnum),
    S.Struct(UntitledSingleSelectEnum),
    S.Struct(TitledSingleSelectEnum),
    S.Struct(UntitledMultiSelectEnum),
    S.Struct(TitledMultiSelectEnum),
    S.Struct(ElicitationString),
    S.Struct(ElicitationNumber),
    S.Struct(ElicitationBoolean),
)
"""The property schemas a form may request; the enum forms are tried
before the plain string so their keys survive decoding."""


class RequestedSchema(TypedDict):
    """The form an MCP elicitation asks for: its fields and which are required."""

    type: Literal["object"]
    properties: dict[str, PrimitiveSchemaDefinition]
    required: NotRequired[list[str]]


class ElicitRequestFormParams(TypedDict):
    """An MCP form elicitation: a message and the form to fill in."""

    message: str
    requestedSchema: RequestedSchema
    mode: NotRequired[Literal["form"]]
    _meta: NotRequired[dict[str, JsonValue]]


REQUESTED_SCHEMA = S.Struct(
    RequestedSchema, properties=S.Record(S.String, PRIMITIVE_SCHEMA_DEFINITION)
)
ELICIT_REQUEST_FORM_PARAMS = S.Struct(
    ElicitRequestFormParams, requestedSchema=REQUESTED_SCHEMA, _meta=REQUEST_META_OBJECT
)


class ElicitRequestURLParams(TypedDict):
    """A URL-mode elicitation (2025-11-25): the client opens ``url``."""

    mode: Literal["url"]
    message: str
    elicitationId: str
    url: str
    _meta: NotRequired[dict[str, JsonValue]]


ELICIT_REQUEST_URL_PARAMS = S.Struct(ElicitRequestURLParams, _meta=REQUEST_META_OBJECT)

type ElicitRequestParams = ElicitRequestFormParams | ElicitRequestURLParams
ELICIT_REQUEST_PARAMS: S.Codec[ElicitRequestParams, Any] = S.Union(
    ELICIT_REQUEST_FORM_PARAMS, ELICIT_REQUEST_URL_PARAMS
)


class ElicitResult(TypedDict):
    """The reply to an MCP elicitation: accepted with content, declined or cancelled."""

    action: Literal["accept", "decline", "cancel"]
    content: NotRequired[dict[str, JsonValue]]
    _meta: NotRequired[JsonObject]


ELICIT_RESULT = S.Struct(ElicitResult, content=JSON_OBJECT, **_META)

# --- methods ----------------------------------------------------------------------------


P_co = TypeVar("P_co", covariant=True)
A_co = TypeVar("A_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Method(Generic[P_co, A_co]):
    """One MCP request or notification (Effect's ``Rpc.make`` of it): the
    method name and the schemas of its params and its result."""

    name: str
    payload_schema: S.Codec[P_co, Any, Never, Never]
    success_schema: S.Codec[A_co, Any, Never, Never]


class _Cursor(TypedDict):
    cursor: NotRequired[str]
    _meta: NotRequired[dict[str, JsonValue]]


class _Uri(TypedDict):
    uri: str
    _meta: NotRequired[dict[str, JsonValue]]


class _GetPromptParams(TypedDict):
    name: str
    arguments: NotRequired[dict[str, str]]
    _meta: NotRequired[dict[str, JsonValue]]


class _SetLevelParams(TypedDict):
    level: LoggingLevel


class _ListToolsResult(TypedDict):
    """The reply to MCP ``tools/list``: a page of tools and the next cursor."""

    tools: list[Tool]
    nextCursor: NotRequired[str]


class _ListResourcesResult(TypedDict):
    """The reply to MCP ``resources/list``: a page of resources and the next cursor."""

    resources: list[Resource]
    nextCursor: NotRequired[str]


class _ListResourceTemplatesResult(TypedDict):
    """The reply to MCP ``resources/templates/list``: a page of templates."""

    resourceTemplates: list[ResourceTemplate]
    nextCursor: NotRequired[str]


class _ListPromptsResult(TypedDict):
    """The reply to MCP ``prompts/list``: a page of prompts and the next cursor."""

    prompts: list[Prompt]
    nextCursor: NotRequired[str]


ListToolsResult = _ListToolsResult
ListResourcesResult = _ListResourcesResult
ListResourceTemplatesResult = _ListResourceTemplatesResult
ListPromptsResult = _ListPromptsResult

_CURSOR = S.Struct(_Cursor, _meta=REQUEST_META_OBJECT)
_URI = S.Struct(_Uri, _meta=REQUEST_META_OBJECT)

PING = Method("ping", REQUEST_META, JSON_OBJECT)
INITIALIZE = Method("initialize", INITIALIZE_PARAMS, INITIALIZE_RESULT)
LIST_TOOLS = Method("tools/list", _CURSOR, S.Struct(_ListToolsResult, tools=S.List(TOOL)))
CALL_TOOL = Method("tools/call", CALL_TOOL_PARAMS, CALL_TOOL_RESULT)
LIST_RESOURCES = Method(
    "resources/list", _CURSOR, S.Struct(_ListResourcesResult, resources=S.List(RESOURCE))
)
LIST_RESOURCE_TEMPLATES = Method(
    "resources/templates/list",
    _CURSOR,
    S.Struct(_ListResourceTemplatesResult, resourceTemplates=S.List(RESOURCE_TEMPLATE)),
)
READ_RESOURCE = Method("resources/read", _URI, READ_RESOURCE_RESULT)
SUBSCRIBE = Method("resources/subscribe", _URI, JSON_OBJECT)
UNSUBSCRIBE = Method("resources/unsubscribe", _URI, JSON_OBJECT)
LIST_PROMPTS = Method("prompts/list", _CURSOR, S.Struct(_ListPromptsResult, prompts=S.List(PROMPT)))
GET_PROMPT = Method(
    "prompts/get", S.Struct(_GetPromptParams, _meta=REQUEST_META_OBJECT), GET_PROMPT_RESULT
)
COMPLETE = Method("completion/complete", COMPLETE_PARAMS, COMPLETE_RESULT)
SET_LEVEL = Method("logging/setLevel", S.Struct(_SetLevelParams), JSON_OBJECT)
CREATE_MESSAGE = Method("sampling/createMessage", CREATE_MESSAGE_PARAMS, CREATE_MESSAGE_RESULT)
LIST_ROOTS = Method("roots/list", REQUEST_META, LIST_ROOTS_RESULT)
ELICIT = Method("elicitation/create", ELICIT_REQUEST_PARAMS, ELICIT_RESULT)

CLIENT_REQUESTS: Mapping[str, Method[Any, Any]] = {
    method.name: method
    for method in (
        PING,
        INITIALIZE,
        LIST_TOOLS,
        CALL_TOOL,
        LIST_RESOURCES,
        LIST_RESOURCE_TEMPLATES,
        READ_RESOURCE,
        SUBSCRIBE,
        UNSUBSCRIBE,
        LIST_PROMPTS,
        GET_PROMPT,
        COMPLETE,
        SET_LEVEL,
    )
}
"""The requests a client sends (Effect's ``ClientRequestRpcs``), by name."""

SERVER_REQUESTS: Mapping[str, Method[Any, Any]] = {
    method.name: method for method in (PING, CREATE_MESSAGE, LIST_ROOTS, ELICIT)
}
"""The requests a server sends (Effect's ``ServerRequestRpcs``), by name."""

# --- errors -----------------------------------------------------------------------------


@dataclass(eq=False)
class McpError(TaggedError):
    """A JSON-RPC error a request fails with: its ``code`` and ``message``."""

    _tag: ClassVar[str] = "McpError"
    CODE: ClassVar[int] = INTERNAL_ERROR_CODE
    message: str
    data: JsonValue = None

    @property
    def code(self) -> int:
        return self.CODE

    def __str__(self) -> str:
        return self.message

    def to_wire(self) -> JsonRpcErrorObject:
        error: JsonRpcErrorObject = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


@dataclass(eq=False)
class ParseError(McpError):
    """MCP error -32700: the message is not valid JSON."""

    _tag: ClassVar[str] = "ParseError"
    CODE: ClassVar[int] = PARSE_ERROR_CODE


@dataclass(eq=False)
class InvalidRequest(McpError):
    """MCP error -32600: the message is not a valid JSON-RPC request."""

    _tag: ClassVar[str] = "InvalidRequest"
    CODE: ClassVar[int] = INVALID_REQUEST_ERROR_CODE


@dataclass(eq=False)
class MethodNotFound(McpError):
    """MCP error -32601: the server has no such method."""

    _tag: ClassVar[str] = "MethodNotFound"
    CODE: ClassVar[int] = METHOD_NOT_FOUND_ERROR_CODE


@dataclass(eq=False)
class InvalidParams(McpError):
    """MCP error -32602: the method's params are invalid."""

    _tag: ClassVar[str] = "InvalidParams"
    CODE: ClassVar[int] = INVALID_PARAMS_ERROR_CODE


@dataclass(eq=False)
class InternalError(McpError):
    """MCP error -32603: the server failed while handling the request."""

    _tag: ClassVar[str] = "InternalError"
    CODE: ClassVar[int] = INTERNAL_ERROR_CODE


@dataclass(eq=False)
class ProtocolError(McpError):
    """An error with any other code (a resource not found, ...)."""

    _tag: ClassVar[str] = "ProtocolError"
    error_code: int = INTERNAL_ERROR_CODE

    @property
    def code(self) -> int:
        return self.error_code


type ReverseOperation = Literal["roots/list", "sampling/createMessage", "elicitation/create"]


@dataclass(eq=False)
class McpReverseOperationUnsupported(TaggedError):
    """The client or the protocol cannot take a request from the server."""

    _tag: ClassVar[str] = "McpReverseOperationUnsupported"
    operation: ReverseOperation
    protocol_version: str
    reason: str


@dataclass(eq=False)
class McpReverseOperationError(TaggedError):
    """A request to the client failed (the transport, or the client's
    error answer as ``cause``)."""

    _tag: ClassVar[str] = "McpReverseOperationError"
    operation: ReverseOperation
    cause: object


type ReverseError = McpReverseOperationUnsupported | McpReverseOperationError


@dataclass(eq=False)
class ElicitationDeclined(TaggedError):
    """The user declined an elicitation (or it could not be sent: ``cause``)."""

    _tag: ClassVar[str] = "ElicitationDeclined"
    request: ElicitRequestFormParams
    cause: object = None


# --- 2026-07-28 subscriptions -----------------------------------------------------------


class SubscriptionFilter(TypedDict, total=False):
    """What a ``subscriptions/listen`` stream carries."""

    toolsListChanged: bool
    promptsListChanged: bool
    resourcesListChanged: bool
    resourceSubscriptions: list[str]


class SubscriptionsListenParams(TypedDict):
    """An MCP ``subscriptions/listen`` request: which notifications to receive."""

    notifications: SubscriptionFilter
    _meta: NotRequired[dict[str, JsonValue]]


SUBSCRIPTION_FILTER = S.Struct(SubscriptionFilter)
SUBSCRIPTIONS_LISTEN = Method(
    "subscriptions/listen",
    S.Struct(
        SubscriptionsListenParams, notifications=SUBSCRIPTION_FILTER, _meta=REQUEST_META_OBJECT
    ),
    JSON_OBJECT,
)


# --- 2026-07-28 multi round-trip requests -----------------------------------------------


class RootsInputRequest(TypedDict):
    """Input a tool call needs from the client: its list of roots."""

    method: Literal["roots/list"]
    params: NotRequired[dict[str, JsonValue]]


class SamplingInputRequest(TypedDict):
    """Input a tool call needs from the client: a sampled model message."""

    method: Literal["sampling/createMessage"]
    params: CreateMessageParams


class InputRequestUrlParams(TypedDict):
    """A URL-mode elicitation on 2026-07-28, which has no ``elicitationId``."""

    mode: Literal["url"]
    message: str
    url: str


class ElicitationInputRequest(TypedDict):
    """Input a tool call needs from the client: the user's answer to an elicitation."""

    method: Literal["elicitation/create"]
    params: ElicitRequestFormParams | InputRequestUrlParams


type McpInputRequest = RootsInputRequest | SamplingInputRequest | ElicitationInputRequest
"""A request for client input, keyed in ``InputRequired.input_requests``."""

type McpInputResponse = Mapping[str, Any]
"""The client's answer to an ``McpInputRequest``, keyed as the request was."""


@dataclass(frozen=True, slots=True, init=False)
class InputRequired:
    """A handler's outcome when it cannot complete until the client supplies
    keyed input in a later request. ``request_state`` is opaque to the client,
    which returns it unchanged with the responses. At least one is given."""

    input_requests: Mapping[str, McpInputRequest] | None
    request_state: str | None

    @overload
    def __init__(
        self, *, input_requests: Mapping[str, McpInputRequest], request_state: str | None = None
    ) -> None: ...

    @overload
    def __init__(
        self, *, input_requests: Mapping[str, McpInputRequest] | None = None, request_state: str
    ) -> None: ...

    def __init__(
        self,
        *,
        input_requests: Mapping[str, McpInputRequest] | None = None,
        request_state: str | None = None,
    ) -> None:
        object.__setattr__(self, "input_requests", input_requests)
        object.__setattr__(self, "request_state", request_state)


# --- request services -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReverseClient:
    """Requests a server sends its client (Effect's ``McpReverseClient``)."""

    list_roots: Callable[[], Effect[ListRootsResult, ReverseError]]
    create_message: Callable[[CreateMessageParams], Effect[CreateMessageResult, ReverseError]]
    elicit: Callable[[ElicitRequestParams], Effect[ElicitResult, ReverseError]]


@dataclass(frozen=True, slots=True)
class RequestContext:
    """The request a handler serves: its client, protocol and ``_meta``."""

    client_id: int
    protocol_version: str
    client_capabilities: ClientCapabilities
    client_info: Implementation | None
    request_metadata: Mapping[str, JsonValue]
    input_responses: Mapping[str, McpInputResponse] | None = None
    """A retried request's answers to its ``InputRequired`` (2026-07-28)."""
    request_state: str | None = None
    """The ``request_state`` a retried request returned (2026-07-28)."""


class McpRequestContext(Tag[RequestContext], key="effect/ai/McpSchema/McpRequestContext"):
    """The current MCP request."""


@dataclass(frozen=True, slots=True)
class ServerClient:
    """The session a request belongs to, and its reverse client."""

    client_id: int
    protocol_version: str
    client_capabilities: ClientCapabilities
    client_info: Implementation | None
    initialize_payload: Mapping[str, JsonValue]
    get_client: Effect[ReverseClient]
    request_metadata: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])


class McpServerClient(Tag[ServerClient], key="effect/ai/McpSchema/McpServerClient"):
    """The current MCP session."""


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """What ``EnabledWhen`` decides with."""

    protocol_version: str
    capabilities: ClientCapabilities
    client_info: Implementation | None


class EnabledWhen(Tag[Callable[[ClientProfile], bool]], key="effect/ai/McpSchema/EnabledWhen"):
    """An annotation hiding a tool, resource or prompt from clients for
    which it returns ``False``."""


# --- resource template parameters ---------------------------------------------------------


T_co = TypeVar("T_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Param(Generic[T_co]):
    """A named URI-template parameter (Effect's ``McpSchema.param``)."""

    name: str
    schema: S.Codec[T_co, Any, Any, Any]


def param[T](name: str, schema: S.Codec[T, Any, Any, Any]) -> Param[T]:
    return Param(name, schema)


from pyfect.ai._mcp.skill_schema import (  # noqa: E402
    SKILL,
    SKILL_FRONTMATTER,
    SKILL_RESOURCE,
    Skill,
    SkillFrontmatter,
    SkillResource,
)

__all__ = [
    "ANNOTATIONS",
    "AUDIO_CONTENT",
    "BLOB_RESOURCE_CONTENTS",
    "CALL_TOOL",
    "CALL_TOOL_PARAMS",
    "CALL_TOOL_RESULT",
    "CLIENT_CAPABILITIES",
    "CLIENT_REQUESTS",
    "COMPLETE",
    "COMPLETE_PARAMS",
    "COMPLETE_RESULT",
    "CONTENT_BLOCK",
    "CREATE_MESSAGE",
    "CREATE_MESSAGE_PARAMS",
    "CREATE_MESSAGE_RESULT",
    "ELICIT",
    "ELICIT_REQUEST_FORM_PARAMS",
    "ELICIT_REQUEST_PARAMS",
    "ELICIT_REQUEST_URL_PARAMS",
    "ELICIT_RESULT",
    "EMBEDDED_RESOURCE",
    "GET_PROMPT",
    "GET_PROMPT_RESULT",
    "HEADER_MISMATCH_ERROR_CODE",
    "ICON",
    "IMAGE_CONTENT",
    "IMPLEMENTATION",
    "INITIALIZE",
    "INITIALIZE_PARAMS",
    "INITIALIZE_RESULT",
    "INTERNAL_ERROR_CODE",
    "INVALID_PARAMS_ERROR_CODE",
    "INVALID_REQUEST_ERROR_CODE",
    "JSON_OBJECT",
    "JSON_RPC_ERROR",
    "JSON_RPC_ERROR_OBJECT",
    "JSON_RPC_MESSAGE",
    "JSON_RPC_NOTIFICATION",
    "JSON_RPC_REQUEST",
    "JSON_RPC_RESPONSE",
    "JSON_RPC_SUCCESS",
    "LIST_PROMPTS",
    "LIST_RESOURCES",
    "LIST_RESOURCE_TEMPLATES",
    "LIST_ROOTS",
    "LIST_ROOTS_RESULT",
    "LIST_TOOLS",
    "LOGGING_LEVEL",
    "LOGGING_LEVELS",
    "METHOD_NOT_FOUND_ERROR_CODE",
    "MISSING_REQUIRED_CLIENT_CAPABILITY_ERROR_CODE",
    "PARSE_ERROR_CODE",
    "PING",
    "PRIMITIVE_SCHEMA_DEFINITION",
    "PROMPT",
    "PROMPT_ARGUMENT",
    "PROMPT_MESSAGE",
    "READ_RESOURCE",
    "READ_RESOURCE_RESULT",
    "REQUESTED_SCHEMA",
    "REQUEST_ID",
    "REQUEST_META",
    "REQUEST_META_OBJECT",
    "RESOURCE",
    "RESOURCE_CONTENTS",
    "RESOURCE_LINK",
    "RESOURCE_NOT_FOUND_ERROR_CODE",
    "RESOURCE_TEMPLATE",
    "ROOT",
    "SAMPLING_MESSAGE",
    "SERVER_CAPABILITIES",
    "SERVER_REQUESTS",
    "SET_LEVEL",
    "SKILL",
    "SKILL_FRONTMATTER",
    "SKILL_RESOURCE",
    "SUBSCRIBE",
    "SUBSCRIPTIONS_LISTEN",
    "SUBSCRIPTION_FILTER",
    "TEXT_CONTENT",
    "TEXT_RESOURCE_CONTENTS",
    "TOOL",
    "TOOL_ANNOTATIONS",
    "TOOL_JSON",
    "UNSUBSCRIBE",
    "UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE",
    "Annotations",
    "AudioContent",
    "BlobResourceContents",
    "CallToolParams",
    "CallToolResult",
    "ClientCapabilities",
    "ClientProfile",
    "CompleteArgument",
    "CompleteParams",
    "CompleteResult",
    "Completion",
    "CompletionContext",
    "ContentBlock",
    "CreateMessageParams",
    "CreateMessageResult",
    "ElicitRequestFormParams",
    "ElicitRequestParams",
    "ElicitRequestURLParams",
    "ElicitResult",
    "ElicitationBoolean",
    "ElicitationDeclined",
    "ElicitationInputRequest",
    "ElicitationNumber",
    "ElicitationString",
    "EmbeddedResource",
    "EnabledWhen",
    "EnumOption",
    "GetPromptResult",
    "Icon",
    "ImageContent",
    "Implementation",
    "InitializeParams",
    "InitializeResult",
    "InputRequestUrlParams",
    "InputRequired",
    "InternalError",
    "InvalidParams",
    "InvalidRequest",
    "JsonObject",
    "JsonRpcError",
    "JsonRpcErrorObject",
    "JsonRpcMessage",
    "JsonRpcNotification",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "JsonRpcSuccess",
    "LegacyTitledEnum",
    "ListChanged",
    "ListPromptsResult",
    "ListResourceTemplatesResult",
    "ListResourcesResult",
    "ListRootsResult",
    "ListToolsResult",
    "LoggingLevel",
    "McpError",
    "McpInputRequest",
    "McpInputResponse",
    "McpRequestContext",
    "McpReverseOperationError",
    "McpReverseOperationUnsupported",
    "McpServerClient",
    "Method",
    "MethodNotFound",
    "Param",
    "ParseError",
    "PrimitiveSchemaDefinition",
    "Prompt",
    "PromptArgument",
    "PromptMessage",
    "PromptReference",
    "ProtocolError",
    "ReadResourceResult",
    "RequestContext",
    "RequestId",
    "RequestMeta",
    "RequestedSchema",
    "Resource",
    "ResourceContents",
    "ResourceLink",
    "ResourceTemplate",
    "ResourceTemplateReference",
    "ResourcesCapability",
    "ReverseClient",
    "ReverseError",
    "ReverseOperation",
    "Role",
    "Root",
    "RootsInputRequest",
    "SamplingInputRequest",
    "SamplingMessage",
    "ServerCapabilities",
    "ServerClient",
    "Skill",
    "SkillFrontmatter",
    "SkillResource",
    "SubscriptionFilter",
    "SubscriptionsListenParams",
    "TextContent",
    "TextResourceContents",
    "TitledMultiSelectEnum",
    "TitledSingleSelectEnum",
    "Tool",
    "ToolAnnotations",
    "ToolJson",
    "UntitledMultiSelectEnum",
    "UntitledSingleSelectEnum",
    "param",
    "parse_request_id",
]
