"""The errors of AI services (Effect's ``AiError``).

Every AI operation fails with one ``AiError``: the ``module`` and ``method``
that failed and a ``reason`` saying why (a rate limit, a bad request, an
invalid tool result, ...). Recover from one kind of reason with
``fx.catch_reason(AiError, RateLimitError, handler)``; ``is_retryable`` and
``retry_after`` read the reason.

Each error is a schema: its wire form is Effect's (camelCase keys with a
``_tag``), so errors sent to a model as tool results, or stored in a chat
history, read the same in both libraries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, ClassVar, Literal, NotRequired, Self, TypedDict, cast

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect.ai._wire import Const, Key, key, wire_codec
from pyfect.duration import format_duration, to_seconds
from pyfect.errors import TaggedError
from pyfect.http import error as http_error
from pyfect.http.headers import current_redacted_names
from pyfect.redacted import Redacted

type HttpMethod = Literal[
    "GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS", "TRACE", "QUERY"
]


class HttpRequestDetails(TypedDict):
    """The request an error happened on (Effect's ``HttpRequestDetails``)."""

    method: HttpMethod
    url: str
    urlParams: Sequence[tuple[str, str | Redacted[str]]]
    hash: NotRequired[str]
    headers: Mapping[str, str | Redacted[str]]


class HttpResponseDetails(TypedDict):
    """The response an error came with (Effect's ``HttpResponseDetails``)."""

    status: int
    headers: Mapping[str, str | Redacted[str]]


class HttpContext(TypedDict):
    """The HTTP exchange behind a provider error."""

    request: HttpRequestDetails
    response: NotRequired[HttpResponseDetails]
    body: NotRequired[str]


class UsageInfo(TypedDict, total=False):
    """Token usage reported with an output error."""

    promptTokens: int
    completionTokens: int
    totalTokens: int


type ProviderMetadata = dict[str, JsonValue]
"""Provider-specific details, by provider name."""

_HeaderValue = S.Union(S.String, S.Redacted(S.String))

HTTP_REQUEST_DETAILS = S.Struct(
    HttpRequestDetails,
    method=S.Literals("GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS", "TRACE", "QUERY"),
    urlParams=S.Array(S.Tuple(S.String, _HeaderValue)),
    headers=S.Record(S.String, _HeaderValue),
).annotate(identifier="HttpRequestDetails")
HTTP_RESPONSE_DETAILS = S.Struct(
    HttpResponseDetails, status=S.Int, headers=S.Record(S.String, _HeaderValue)
).annotate(identifier="HttpResponseDetails")
HTTP_CONTEXT = S.Struct(
    HttpContext, request=HTTP_REQUEST_DETAILS, response=HTTP_RESPONSE_DETAILS
).annotate(identifier="HttpContext")
USAGE_INFO = S.Struct(UsageInfo).annotate(identifier="UsageInfo")
PROVIDER_METADATA = S.Record(S.String, S.NullOr(S.Json))
"""Effect's ``ProviderMetadata`` schema."""


def _metadata_key() -> Key:
    return key("metadata", "metadata", PROVIDER_METADATA, default=dict)


def _http_key() -> Key:
    return key("http", "http", HTTP_CONTEXT, optional=True)


def _redact_headers(headers: object) -> dict[str, str]:
    from pyfect.http.headers import Headers

    assert isinstance(headers, Headers)
    return {k: str(v) for k, v in headers.redact(current_redacted_names()).items()}


class AiErrorReason(TaggedError):
    """What every reason has: whether retrying may help, and a message."""

    _tag: ClassVar[str]

    @classmethod
    def __codec__(cls) -> S.Bottom[Self, Mapping[str, object]]:
        return cls.__dict__["_wire"]

    @property
    def is_retryable(self) -> bool:
        return False

    @property
    def message(self) -> str:
        raise NotImplementedError


@dataclass(eq=False)
class NetworkError(AiErrorReason):
    """The request did not reach the provider (or could not be built)."""

    _tag: ClassVar[str] = "NetworkError"
    reason: Literal["TransportError", "EncodeError", "InvalidUrlError"]
    request: HttpRequestDetails
    description: str | None = None

    @property
    def is_retryable(self) -> bool:
        return self.reason == "TransportError"

    @staticmethod
    def from_request_error(
        error: http_error.TransportError | http_error.EncodeError | http_error.InvalidUrlError,
    ) -> NetworkError:
        request = error.request
        details: HttpRequestDetails = {
            "method": request.method,
            "url": request.url,
            "urlParams": list(request.url_params),
            "headers": _redact_headers(request.headers),
        }
        if request.hash is not None:
            details["hash"] = request.hash
        return NetworkError(reason=error.tag, request=details, description=error.description)

    @property
    def message(self) -> str:
        base = (
            f"{self.reason}: {self.description}"
            if self.description
            else f"{self.reason}: A network error occurred."
        )
        base += f" ({self.request['method']} {self.request['url']})"
        match self.reason:
            case "EncodeError":
                suggestion = (
                    "Check that the request body data is properly formatted and matches "
                    "the expected content type."
                )
            case "InvalidUrlError":
                suggestion = (
                    "Verify that the URL format is correct and that all required parameters "
                    "have been provided. Check for any special characters that may need encoding."
                )
            case "TransportError":
                suggestion = (
                    "Check your network connection and verify that the requested URL is accessible."
                )
        return f"{base}\n\n{suggestion}"


@dataclass(eq=False)
class RateLimitError(AiErrorReason):
    """Too many requests; ``retry_after`` says when to try again."""

    _tag: ClassVar[str] = "RateLimitError"
    retry_after: timedelta | None = None
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    http: HttpContext | None = None

    @property
    def is_retryable(self) -> bool:
        return True

    @property
    def message(self) -> str:
        msg = "Rate limit exceeded"
        if self.retry_after:
            msg += f". Retry after {format_duration(to_seconds(self.retry_after))}"
        return msg


@dataclass(eq=False)
class QuotaExhaustedError(AiErrorReason):
    """The account's quota is used up until ``reset_at``."""

    _tag: ClassVar[str] = "QuotaExhaustedError"
    reset_at: datetime | None = None
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    http: HttpContext | None = None

    @property
    def message(self) -> str:
        msg = "Quota exhausted"
        if self.reset_at:
            msg += f". Resets at {_iso(self.reset_at)}"
        return f"{msg}. Check your account billing and usage limits."


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


type AuthenticationKind = Literal[
    "InvalidKey", "ExpiredKey", "MissingKey", "InsufficientPermissions", "Unknown"
]

_AUTH_SUGGESTIONS: dict[str, str] = {
    "InvalidKey": "Verify your API key is correct",
    "ExpiredKey": "Your API key has expired. Generate a new one",
    "MissingKey": "No API key provided. Set the appropriate environment variable",
    "InsufficientPermissions": "Your API key lacks required permissions",
    "Unknown": "Authentication failed. Check your credentials",
}


@dataclass(eq=False)
class AuthenticationError(AiErrorReason):
    """The credentials were refused."""

    _tag: ClassVar[str] = "AuthenticationError"
    kind: AuthenticationKind
    description: str | None = None
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    http: HttpContext | None = None

    @property
    def message(self) -> str:
        msg = f"{self.kind}: {_AUTH_SUGGESTIONS[self.kind]}"
        if self.description:
            msg += f". {self.description}"
        return msg


@dataclass(eq=False)
class ContentPolicyError(AiErrorReason):
    """The input or output broke the provider's content policy."""

    _tag: ClassVar[str] = "ContentPolicyError"
    description: str
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    http: HttpContext | None = None

    @property
    def message(self) -> str:
        return f"Content policy violation: {self.description}"


@dataclass(eq=False)
class InvalidRequestError(AiErrorReason):
    """The provider rejected the request."""

    _tag: ClassVar[str] = "InvalidRequestError"
    parameter: str | None = None
    constraint: str | None = None
    description: str | None = None
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    http: HttpContext | None = None

    @property
    def message(self) -> str:
        msg = "Invalid request"
        if self.parameter:
            msg += f": parameter '{self.parameter}'"
        if self.constraint:
            msg += f" {self.constraint}"
        if self.description:
            msg += f". {self.description}"
        return msg


@dataclass(eq=False)
class InternalProviderError(AiErrorReason):
    """The provider failed (a 5xx)."""

    _tag: ClassVar[str] = "InternalProviderError"
    description: str
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    http: HttpContext | None = None

    @property
    def is_retryable(self) -> bool:
        return True

    @property
    def message(self) -> str:
        return f"Internal provider error: {self.description}"


@dataclass(eq=False)
class InvalidResponseError(AiErrorReason):
    """The provider's response could not be read."""

    _tag: ClassVar[str] = "InvalidResponseError"
    description: str
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    http: HttpContext | None = None

    @staticmethod
    def from_schema_error(error: S.SchemaError) -> InvalidResponseError:
        return InvalidResponseError(description=str(error))

    @property
    def message(self) -> str:
        return f"Invalid response: {self.description}"


@dataclass(eq=False)
class InvalidOutputError(AiErrorReason):
    """The model's output did not fit what was expected."""

    _tag: ClassVar[str] = "InvalidOutputError"
    description: str
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    usage: UsageInfo | None = None

    @property
    def is_retryable(self) -> bool:
        return True

    @staticmethod
    def from_schema_error(error: S.SchemaError) -> InvalidOutputError:
        return InvalidOutputError(description=str(error))

    @property
    def message(self) -> str:
        return f"Invalid output: {self.description}"


@dataclass(eq=False)
class StructuredOutputError(AiErrorReason):
    """The model's structured output did not decode with the schema."""

    _tag: ClassVar[str] = "StructuredOutputError"
    description: str
    response_text: str
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    usage: UsageInfo | None = None

    @property
    def is_retryable(self) -> bool:
        return True

    @staticmethod
    def from_schema_error(error: S.SchemaError, response_text: str) -> StructuredOutputError:
        return StructuredOutputError(description=str(error), response_text=response_text)

    @property
    def message(self) -> str:
        return f"Structured output validation failed: {self.description}"


@dataclass(eq=False)
class UnsupportedSchemaError(AiErrorReason):
    """A schema the provider cannot express."""

    _tag: ClassVar[str] = "UnsupportedSchemaError"
    description: str
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])

    @property
    def message(self) -> str:
        return f"Unsupported schema: {self.description}"


@dataclass(eq=False)
class UnknownError(AiErrorReason):
    """Anything the other reasons do not cover."""

    _tag: ClassVar[str] = "UnknownError"
    description: str | None = None
    metadata: ProviderMetadata = field(default_factory=dict[str, JsonValue])
    http: HttpContext | None = None

    @property
    def message(self) -> str:
        return self.description if self.description is not None else "Unknown error"


@dataclass(eq=False)
class ToolNotFoundError(AiErrorReason):
    """The model called a tool the toolkit does not have."""

    _tag: ClassVar[str] = "ToolNotFoundError"
    tool_name: str
    available_tools: Sequence[str]

    @property
    def is_retryable(self) -> bool:
        return True

    @property
    def message(self) -> str:
        available = ", ".join(self.available_tools) if self.available_tools else "none"
        return f"Tool '{self.tool_name}' not found. Available tools: {available}"


@dataclass(eq=False)
class ToolParameterValidationError(AiErrorReason):
    """The model called a tool with parameters its schema rejects."""

    _tag: ClassVar[str] = "ToolParameterValidationError"
    tool_name: str
    description: str

    @property
    def is_retryable(self) -> bool:
        return True

    @property
    def message(self) -> str:
        return f"Invalid parameters for tool '{self.tool_name}': {self.description}"


@dataclass(eq=False)
class InvalidToolResultError(AiErrorReason):
    """A tool handler returned a value its success schema rejects."""

    _tag: ClassVar[str] = "InvalidToolResultError"
    tool_name: str
    description: str

    @property
    def message(self) -> str:
        return f"Tool '{self.tool_name}' returned invalid result: {self.description}"


@dataclass(eq=False)
class ToolResultEncodingError(AiErrorReason):
    """A tool's result could not be encoded for the model."""

    _tag: ClassVar[str] = "ToolResultEncodingError"
    tool_name: str
    tool_result: object
    description: str

    @property
    def message(self) -> str:
        return f"Failed to encode result for tool '{self.tool_name}': {self.description}"


@dataclass(eq=False)
class ToolConfigurationError(AiErrorReason):
    """A provider-defined tool was configured wrongly."""

    _tag: ClassVar[str] = "ToolConfigurationError"
    tool_name: str
    description: str

    @property
    def message(self) -> str:
        return f"Invalid configuration for tool '{self.tool_name}': {self.description}"


@dataclass(eq=False)
class ToolkitRequiredError(AiErrorReason):
    """A prompt holds tool approvals, and no toolkit was given to run them."""

    _tag: ClassVar[str] = "ToolkitRequiredError"
    pending_approvals: Sequence[str]
    description: str | None = None

    @property
    def message(self) -> str:
        tools = ", ".join(self.pending_approvals)
        return f"Toolkit required to resolve pending tool approvals: {tools}"


@dataclass(eq=False)
class InvalidUserInputError(AiErrorReason):
    """The caller's input could not be sent."""

    _tag: ClassVar[str] = "InvalidUserInputError"
    description: str

    @property
    def message(self) -> str:
        return f"Invalid user input: {self.description}"


type AnyReason = (
    RateLimitError
    | QuotaExhaustedError
    | AuthenticationError
    | ContentPolicyError
    | InvalidRequestError
    | InvalidResponseError
    | InternalProviderError
    | NetworkError
    | InvalidOutputError
    | StructuredOutputError
    | UnsupportedSchemaError
    | UnknownError
    | ToolNotFoundError
    | ToolParameterValidationError
    | InvalidToolResultError
    | ToolResultEncodingError
    | ToolConfigurationError
    | ToolkitRequiredError
    | InvalidUserInputError
)


@dataclass(eq=False)
class AiError(TaggedError):
    """An AI operation failed: ``module.method`` and why (``reason``)."""

    _tag: ClassVar[str] = "AiError"
    module: str
    method: str
    reason: AnyReason

    def __post_init__(self) -> None:
        self.__cause__ = self.reason

    @property
    def is_retryable(self) -> bool:
        return self.reason.is_retryable

    @property
    def retry_after(self) -> timedelta | None:
        return self.reason.retry_after if isinstance(self.reason, RateLimitError) else None

    @property
    def message(self) -> str:
        return f"{self.module}.{self.method}: {self.reason.message}"

    @classmethod
    def __codec__(cls) -> S.Bottom[AiError, Mapping[str, object]]:
        return _AI_ERROR


def make(*, module: str, method: str, reason: AnyReason) -> AiError:
    return AiError(module=module, method=method, reason=reason)


def is_ai_error(u: object) -> bool:
    return isinstance(u, AiError)


def is_ai_error_reason(u: object) -> bool:
    return isinstance(u, AiErrorReason)


def reason_from_http_status(
    *,
    status: int,
    body: object = None,
    http: HttpContext | None = None,
    metadata: ProviderMetadata | None = None,
    description: str | None = None,
) -> AnyReason:
    """The reason an HTTP ``status`` stands for (400 a bad request, 401 /
    403 refused credentials, 429 a rate limit, 5xx a provider failure)."""
    meta: ProviderMetadata = metadata if metadata else {}
    desc = description or None
    match status:
        case 400:
            return InvalidRequestError(description=desc, metadata=meta, http=http)
        case 401:
            return AuthenticationError(
                kind="InvalidKey", description=desc, metadata=meta, http=http
            )
        case 403:
            return AuthenticationError(
                kind="InsufficientPermissions", description=desc, metadata=meta, http=http
            )
        case 429:
            return RateLimitError(metadata=meta, http=http)
        case _ if status >= 500:
            return InternalProviderError(
                description=desc or "Server error", metadata=meta, http=http
            )
        case _:
            return UnknownError(description=desc, metadata=meta, http=http)


def build_error_description(
    *,
    status: int,
    message: str | None,
    method: str,
    url: str,
    body: str | None,
    error_code: str | int | None = None,
    error_type: str | None = None,
    request_id: str | None = None,
) -> str:
    """A one-line description of a failed HTTP call (Effect's
    ``buildErrorDescription``)."""
    parts = [message if message else f"HTTP {status}", f"({method} {url})"]
    if error_code:
        parts.append(f"[code: {error_code}]")
    elif error_type:
        parts.append(f"[type: {error_type}]")
    if request_id:
        parts.append(f"[requestId: {request_id}]")
    if not message and body:
        parts.append(f"Response: {body[:200] + '...' if len(body) > 200 else body}")
    return " ".join(parts)


# Schemas -----------------------------------------------------------------------------


def _codec(cls: type[AiErrorReason], *keys: Key) -> None:
    tag = cls._tag  # pyright: ignore[reportPrivateUsage]
    codec = wire_codec(cls, [Const("_tag", tag), *keys], identifier=f"effect/ai/AiError/{tag}")
    type.__setattr__(cls, "_wire", codec)


_codec(
    NetworkError,
    key("reason", "reason", S.Literals("TransportError", "EncodeError", "InvalidUrlError")),
    key("request", "request", HTTP_REQUEST_DETAILS),
    key("description", "description", S.String, optional=True),
)
_codec(
    RateLimitError,
    key("retryAfter", "retry_after", S.Duration, optional=True),
    _metadata_key(),
    _http_key(),
)
_codec(
    QuotaExhaustedError,
    key("resetAt", "reset_at", S.DateTimeUtc, optional=True),
    _metadata_key(),
    _http_key(),
)
_codec(
    AuthenticationError,
    key(
        "kind",
        "kind",
        S.Literals("InvalidKey", "ExpiredKey", "MissingKey", "InsufficientPermissions", "Unknown"),
    ),
    key("description", "description", S.String, optional=True),
    _metadata_key(),
    _http_key(),
)
for _cls in (ContentPolicyError, InternalProviderError, InvalidResponseError):
    _codec(_cls, key("description", "description", S.String), _metadata_key(), _http_key())
_codec(
    InvalidRequestError,
    key("parameter", "parameter", S.String, optional=True),
    key("constraint", "constraint", S.String, optional=True),
    key("description", "description", S.String, optional=True),
    _metadata_key(),
    _http_key(),
)
_codec(
    InvalidOutputError,
    key("description", "description", S.String),
    _metadata_key(),
    key("usage", "usage", USAGE_INFO, optional=True),
)
_codec(
    StructuredOutputError,
    key("description", "description", S.String),
    key("responseText", "response_text", S.String),
    _metadata_key(),
    key("usage", "usage", USAGE_INFO, optional=True),
)
_codec(UnsupportedSchemaError, key("description", "description", S.String), _metadata_key())
_codec(
    UnknownError,
    key("description", "description", S.String, optional=True),
    _metadata_key(),
    _http_key(),
)
_codec(
    ToolNotFoundError,
    key("toolName", "tool_name", S.String),
    key("availableTools", "available_tools", S.Array(S.String)),
)
for _cls in (ToolParameterValidationError, InvalidToolResultError, ToolConfigurationError):
    _codec(
        _cls, key("toolName", "tool_name", S.String), key("description", "description", S.String)
    )
_codec(
    ToolResultEncodingError,
    key("toolName", "tool_name", S.String),
    key("toolResult", "tool_result", S.Unknown),
    key("description", "description", S.String),
)
_codec(
    ToolkitRequiredError,
    key("pendingApprovals", "pending_approvals", S.Array(S.String)),
    key("description", "description", S.String, optional=True),
)
_codec(InvalidUserInputError, key("description", "description", S.String))

REASONS: tuple[type[AiErrorReason], ...] = (
    RateLimitError,
    QuotaExhaustedError,
    AuthenticationError,
    ContentPolicyError,
    InvalidRequestError,
    InvalidResponseError,
    InternalProviderError,
    NetworkError,
    InvalidOutputError,
    StructuredOutputError,
    UnsupportedSchemaError,
    UnknownError,
    ToolNotFoundError,
    ToolParameterValidationError,
    InvalidToolResultError,
    ToolResultEncodingError,
    ToolConfigurationError,
    ToolkitRequiredError,
    InvalidUserInputError,
)

AI_ERROR_REASON: S.Bottom[AnyReason, Mapping[str, object]] = cast(
    "Any", S.Union(*(r.__codec__() for r in REASONS))
)
"""The schema of every reason (Effect's ``AiErrorReason`` schema)."""

_AI_ERROR = wire_codec(
    AiError,
    [
        Const("_tag", "AiError"),
        key("module", "module", S.String),
        key("method", "method", S.String),
        key("reason", "reason", AI_ERROR_REASON),
    ],
    identifier="effect/ai/AiError/AiError",
)
