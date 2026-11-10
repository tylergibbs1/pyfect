"""The errors of an MCP client (Effect's ``McpClientError``).

Every client operation fails with one ``McpClientError`` whose ``reason``
says why: the transport failed, the server answered with a JSON-RPC
error (``ProtocolError``, with its ``code``) or an HTTP error status, the
deadline passed, a limit was exceeded, a result did not validate, or the
tool reported an error. Handle one kind with
``fx.catch_reason(McpClientError, TimeoutError, handler)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Self, cast

from pyfect import schema as S
from pyfect._js import or_default
from pyfect._json_value import JsonValue
from pyfect._wire_codec import Const, Key, key, wire_codec
from pyfect.ai.mcp_schema import CALL_TOOL_RESULT, CallToolResult
from pyfect.errors import TaggedError


class McpClientErrorReason(TaggedError):
    """What every reason has: a message."""

    _tag: ClassVar[str]

    @classmethod
    def __codec__(cls) -> S.Bottom[Self, Mapping[str, object]]:
        return cls.__dict__["_wire"]

    @property
    def message(self) -> str:
        raise NotImplementedError


@dataclass(eq=False)
class TransportError(McpClientErrorReason):
    """The process or connection failed."""

    _tag: ClassVar[str] = "TransportError"
    description: str | None = None
    cause: object = None

    @property
    def message(self) -> str:
        return or_default(self.description, "MCP transport failed")


@dataclass(eq=False)
class ProtocolError(McpClientErrorReason):
    """The server answered with a JSON-RPC error, or broke the protocol."""

    _tag: ClassVar[str] = "ProtocolError"
    code: int | None = None
    data: JsonValue = None
    description: str | None = None
    cause: object = None

    @property
    def message(self) -> str:
        message = or_default(self.description, "MCP protocol error")
        return message if self.code is None else f"{message} (code {self.code})"


@dataclass(eq=False)
class HttpError(McpClientErrorReason):
    """The server answered with an HTTP error status (and maybe a JSON-RPC
    error in the body)."""

    _tag: ClassVar[str] = "HttpError"
    status: int
    code: int | None = None
    data: JsonValue = None
    description: str | None = None
    www_authenticate: str | None = None
    retry_after: str | None = None

    @property
    def message(self) -> str:
        message = f"MCP HTTP status {self.status}"
        return message if self.description is None else f"{message}: {self.description}"


@dataclass(eq=False)
class UnsupportedError(McpClientErrorReason):
    """The server, the protocol or the client lacks what was asked for."""

    _tag: ClassVar[str] = "UnsupportedError"
    description: str
    result: CallToolResult | None = None

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class ClosedError(McpClientErrorReason):
    """The client's scope closed, or the server forgot the session."""

    _tag: ClassVar[str] = "ClosedError"
    session_expired: bool = False
    description: str | None = None

    @property
    def message(self) -> str:
        if self.session_expired:
            return "MCP session expired"
        return or_default(self.description, "MCP connection closed")


@dataclass(eq=False)
class TimeoutError(McpClientErrorReason):
    """An operation passed its deadline."""

    _tag: ClassVar[str] = "TimeoutError"
    operation: str

    @property
    def message(self) -> str:
        return f"MCP {self.operation} deadline exceeded"


@dataclass(eq=False)
class LimitError(McpClientErrorReason):
    """A message, page or listing exceeded the client's limits."""

    _tag: ClassVar[str] = "LimitError"
    description: str

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class ConfigurationError(McpClientErrorReason):
    """The client was configured wrongly."""

    _tag: ClassVar[str] = "ConfigurationError"
    description: str
    cause: object = None

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class ValidationError(McpClientErrorReason):
    """A payload or result did not match its schema."""

    _tag: ClassVar[str] = "ValidationError"
    description: str
    cause: object = None

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class ToolError(McpClientErrorReason):
    """The tool reported an error (``isError``); ``result`` is all of it."""

    _tag: ClassVar[str] = "ToolError"
    result: CallToolResult

    @property
    def message(self) -> str:
        text = next((b["text"] for b in self.result["content"] if b["type"] == "text"), None)
        return (
            "MCP tool reported an error" if text is None else f"MCP tool reported an error: {text}"
        )


type AnyReason = (
    TransportError
    | ProtocolError
    | HttpError
    | UnsupportedError
    | ClosedError
    | TimeoutError
    | LimitError
    | ConfigurationError
    | ValidationError
    | ToolError
)


@dataclass(eq=False)
class McpClientError(TaggedError):
    """An MCP client operation failed, and why (``reason``)."""

    _tag: ClassVar[str] = "McpClientError"
    reason: AnyReason

    @property
    def message(self) -> str:
        return self.reason.message

    @classmethod
    def __codec__(cls) -> S.Bottom[McpClientError, Mapping[str, object]]:
        return MCP_CLIENT_ERROR


def is_mcp_client_error(u: object) -> bool:
    return isinstance(u, McpClientError)


def is_mcp_client_error_reason(u: object) -> bool:
    return isinstance(u, McpClientErrorReason)


# Schemas (Effect's error classes are schemas: a returned tool failure is
# sent to the model encoded) ----------------------------------------------------------


def _codec(cls: type[McpClientErrorReason], *keys: Key) -> None:
    tag = cls._tag  # pyright: ignore[reportPrivateUsage]
    codec = wire_codec(
        cls, [Const("_tag", tag), *keys], identifier=f"effect/ai/McpClientError/{tag}"
    )
    type.__setattr__(cls, "_wire", codec)


def _optional(name: str, attr: str, schema: S.Top, unset: object = None) -> Key:
    return key(name, attr, schema, optional=True, unset=unset)


_DEFECT = S.Defect()
_codec(
    TransportError,
    _optional("description", "description", S.String),
    _optional("cause", "cause", _DEFECT),
)
_codec(
    ProtocolError,
    _optional("code", "code", S.Int),
    _optional("data", "data", S.Unknown),
    _optional("description", "description", S.String),
    _optional("cause", "cause", _DEFECT),
)
_codec(
    HttpError,
    key("status", "status", S.Int),
    _optional("code", "code", S.Int),
    _optional("data", "data", S.Unknown),
    _optional("description", "description", S.String),
    _optional("wwwAuthenticate", "www_authenticate", S.String),
    _optional("retryAfter", "retry_after", S.String),
)
_codec(
    UnsupportedError,
    key("description", "description", S.String),
    _optional("result", "result", CALL_TOOL_RESULT),
)
_codec(
    ClosedError,
    _optional("sessionExpired", "session_expired", S.Boolean, unset=False),
    _optional("description", "description", S.String),
)
_codec(TimeoutError, key("operation", "operation", S.String))
_codec(LimitError, key("description", "description", S.String))
for _described in (ConfigurationError, ValidationError):
    _codec(
        _described,
        key("description", "description", S.String),
        _optional("cause", "cause", _DEFECT),
    )
_codec(ToolError, key("result", "result", CALL_TOOL_RESULT))

REASONS: tuple[type[McpClientErrorReason], ...] = (
    TransportError,
    ProtocolError,
    HttpError,
    UnsupportedError,
    ClosedError,
    TimeoutError,
    LimitError,
    ConfigurationError,
    ValidationError,
    ToolError,
)

MCP_CLIENT_ERROR_REASON: S.Bottom[AnyReason, Mapping[str, object]] = cast(
    "Any", S.Union(*(r.__codec__() for r in REASONS))
)
"""The schema of every reason (Effect's ``McpClientErrorReason``)."""

MCP_CLIENT_ERROR: S.Bottom[McpClientError, Mapping[str, object]] = wire_codec(
    McpClientError,
    [Const("_tag", "McpClientError"), key("reason", "reason", MCP_CLIENT_ERROR_REASON)],
    identifier="effect/ai/McpClientError/McpClientError",
)
"""The schema of ``McpClientError`` (Effect's ``McpClientError`` class)."""

__all__ = [
    "MCP_CLIENT_ERROR",
    "MCP_CLIENT_ERROR_REASON",
    "REASONS",
    "AnyReason",
    "ClosedError",
    "ConfigurationError",
    "HttpError",
    "LimitError",
    "McpClientError",
    "McpClientErrorReason",
    "ProtocolError",
    "TimeoutError",
    "ToolError",
    "TransportError",
    "UnsupportedError",
    "ValidationError",
    "is_mcp_client_error",
    "is_mcp_client_error_reason",
]
