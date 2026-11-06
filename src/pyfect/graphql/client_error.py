"""The errors of a GraphQL client (Effect's ``GraphQLClientError``).

Every client method fails with a ``GraphQLClientError``: the ``operation``
that failed and a ``reason`` saying why. ``ResponseError`` is a response
with GraphQL ``errors``; ``TransportError`` a response that never came or
was not GraphQL; ``EncodeError`` / ``DecodeError`` variables or data that
did not match their schemas; ``PaginationError`` cursor paging that could
not go on. ``is_retryable`` and ``retry_after`` read the reason.

Each error is a schema class, so errors round-trip through
``S.encode_sync`` / ``S.decode_unknown_sync``; headers encode as a plain
string record and ``retryAfter`` as milliseconds.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import NotRequired

from typing_extensions import TypedDict

from pyfect import schema as S
from pyfect.duration import Seconds
from pyfect.graphql._schemas import HEADERS, SECONDS_FROM_MILLIS
from pyfect.http import error as http_error
from pyfect.http.headers import Headers, parse_retry_after, retry_after_delay
from pyfect.result import Ok
from pyfect.schema._undefined import Undefined


class Location(TypedDict):
    """Where in the document an error happened."""

    line: float
    column: float


class GraphQLError(TypedDict, extra_items=S.JsonValue):
    """One entry of a response's ``errors``, as the GraphQL specification
    describes it. ``path[0]`` is the response key (the alias, when the
    document used one). Other top-level keys, such as GitHub's ``type``,
    are kept as JSON values."""

    message: str
    locations: NotRequired[Sequence[Location]]
    path: NotRequired[Sequence[str | float]]
    extensions: NotRequired[Mapping[str, S.JsonValue]]


GRAPHQL_ERROR = S.Struct(
    GraphQLError,
    locations=S.Array(S.Struct(Location)),
    path=S.Array(S.Union(S.String, S.Number)),
)
"""The schema of a ``GraphQLError``."""

_JSON_OBJECT = S.Record(S.String, S.Json)

_RETRYABLE_STANDARD_CLOSE_CODES = frozenset({1000, 1001, 1005, 1006, 1012, 1013, 1014})
_FATAL_GRAPHQL_WS_CLOSE_CODES = frozenset({4400, 4401, 4403, 4406, 4409, 4429, 4500})


def is_fatal_close_code(code: int) -> bool:
    """A WebSocket close code that retrying cannot fix: every standard
    ``1xxx`` code but 1000, 1001, 1005, 1006, 1012, 1013 and 1014, and the
    graphql-ws codes 4400, 4401, 4403, 4406, 4409, 4429 and 4500."""
    if 1000 <= code < 2000:
        return code not in _RETRYABLE_STANDARD_CLOSE_CODES
    return code in _FATAL_GRAPHQL_WS_CLOSE_CODES


def _is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def parse_retry_after_header(value: str | None, now_millis: float) -> Seconds | None:
    """A ``Retry-After`` value (whole seconds or an HTTP date) as a delay
    from ``now_millis``; anything else is ``None``."""
    if value is None:
        return None
    parsed = parse_retry_after(value)
    return retry_after_delay(parsed.value, now_millis) if isinstance(parsed, Ok) else None


class ResponseError(S.TaggedError, identifier="effect/graphql/GraphQLClientError/ResponseError"):
    """The server answered with GraphQL ``errors`` (a query or mutation
    fails on any, even with partial ``data``, which is kept raw here).
    ``status`` and ``headers`` are what the transport reported.
    ``retry_after`` reads the ``Retry-After`` header when the error is
    made; ``is_retryable`` holds for status 429 or 5xx, or any valid
    ``Retry-After``."""

    errors: tuple[GraphQLError, ...] = S.field(S.NonEmptyArray(GRAPHQL_ERROR))
    data: S.JsonValue = S.field(S.Union(S.Json, Undefined), default=None)
    extensions: Mapping[str, S.JsonValue] | None = S.field(
        S.Union(_JSON_OBJECT, Undefined), default=None
    )
    status: int | None = S.field(S.Union(S.Int, Undefined), default=None)
    headers: Headers | None = S.field(S.Union(HEADERS, Undefined), default=None)

    def __post_init__(self) -> None:
        header = None if self.headers is None else self.headers.get("retry-after")
        object.__setattr__(
            self, "_retry_after", parse_retry_after_header(header, time.time_ns() // 1_000_000)
        )

    @property
    def retry_after(self) -> Seconds | None:
        retry_after: Seconds | None = self.__dict__["_retry_after"]
        return retry_after

    @property
    def is_retryable(self) -> bool:
        if self.retry_after is not None:
            return True
        return self.status is not None and _is_retryable_status(self.status)

    @property
    def message(self) -> str:
        return "; ".join(error["message"] for error in self.errors)


class TransportError(S.TaggedError, identifier="effect/graphql/GraphQLClientError/TransportError"):
    """No GraphQL response came: a network failure, an HTTP response that
    is not GraphQL (``status`` and ``headers`` set), or a closed WebSocket
    (``close_code``). ``fatal`` marks a failure retrying cannot fix;
    ``cause`` is the original error."""

    description: str
    status: int | None = S.field(S.Union(S.Int, Undefined), default=None)
    headers: Headers | None = S.field(S.Union(HEADERS, Undefined), default=None)
    retry_after: Seconds | None = S.field(
        S.Union(SECONDS_FROM_MILLIS, Undefined), default=None, key="retryAfter"
    )
    close_code: int | None = S.field(S.Union(S.Int, Undefined), default=None, key="closeCode")
    fatal: bool | None = S.field(S.Union(S.Boolean, Undefined), default=None)
    cause: BaseException | None = S.field(S.Union(S.Defect(), Undefined), default=None)

    def __post_init__(self) -> None:
        self.__cause__ = self.cause

    @property
    def is_retryable(self) -> bool:
        """A network failure, status 429 or 5xx, a ``retry_after``, or a
        close code that is not fatal; never when ``fatal``."""
        if self.fatal:
            return False
        if self.close_code is not None and is_fatal_close_code(self.close_code):
            return False
        if self.retry_after is not None:
            return True
        return self.status is None or _is_retryable_status(self.status)

    @property
    def message(self) -> str:
        return self.description

    @staticmethod
    def from_http_client_error(
        error: http_error.HttpClientError, *, now_millis: float | None = None
    ) -> TransportError:
        """``error`` with the response's ``status``, ``headers`` and
        ``Retry-After`` (an HTTP date measured from ``now_millis``, by
        default the wall clock)."""
        response = error.response
        headers = None if response is None else response.headers
        now = time.time_ns() // 1_000_000 if now_millis is None else now_millis
        return TransportError(
            description=error.message,
            status=None if response is None else response.status,
            headers=headers,
            retry_after=parse_retry_after_header(
                None if headers is None else headers.get("retry-after"), now
            ),
            cause=error,
        )


class EncodeError(S.TaggedError, identifier="effect/graphql/GraphQLClientError/EncodeError"):
    """The variables schema rejected the input; nothing was sent."""

    description: str

    @property
    def is_retryable(self) -> bool:
        return False

    @property
    def message(self) -> str:
        return self.description


class DecodeError(S.TaggedError, identifier="effect/graphql/GraphQLClientError/DecodeError"):
    """The response was not GraphQL, or its ``data`` did not match the
    result schema (``data: null`` without ``errors`` included)."""

    description: str

    @property
    def is_retryable(self) -> bool:
        return False

    @property
    def message(self) -> str:
        return self.description


class PaginationError(
    S.TaggedError, identifier="effect/graphql/GraphQLClientError/PaginationError"
):
    """``pages`` / ``items`` could not go on: the connection was ``null``
    after the first page, or ``hasNextPage`` was true with a ``null`` or
    unchanged ``endCursor``. ``cursor`` is the last one sent."""

    description: str
    cursor: str | None

    @property
    def is_retryable(self) -> bool:
        return False

    @property
    def message(self) -> str:
        return self.description


type Reason = ResponseError | TransportError | EncodeError | DecodeError | PaginationError

REASON = S.Union(ResponseError, TransportError, EncodeError, DecodeError, PaginationError)
"""The schema of every reason."""


class GraphQLClientError(S.TaggedError, identifier="~effect/graphql/GraphQLClientError"):
    """What every client method fails with: the ``operation`` and the
    ``reason`` (also its ``__cause__``)."""

    operation: str
    reason: Reason = S.field(REASON)

    def __post_init__(self) -> None:
        self.__cause__ = self.reason

    @property
    def is_retryable(self) -> bool:
        return self.reason.is_retryable

    @property
    def retry_after(self) -> Seconds | None:
        """The ``Retry-After`` hint of a response or transport reason."""
        reason = self.reason
        if isinstance(reason, ResponseError | TransportError):
            return reason.retry_after
        return None

    @property
    def status(self) -> int | None:
        reason = self.reason
        return reason.status if isinstance(reason, ResponseError | TransportError) else None

    @property
    def headers(self) -> Headers | None:
        reason = self.reason
        return reason.headers if isinstance(reason, ResponseError | TransportError) else None

    @property
    def message(self) -> str:
        return f"{self.operation}: {type(self.reason).__name__}: {self.reason.message}"


__all__ = [
    "GRAPHQL_ERROR",
    "REASON",
    "DecodeError",
    "EncodeError",
    "GraphQLClientError",
    "GraphQLError",
    "Location",
    "PaginationError",
    "Reason",
    "ResponseError",
    "TransportError",
    "is_fatal_close_code",
    "parse_retry_after_header",
]
