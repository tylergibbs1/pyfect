"""Schemas of RPC results (Effect's ``RpcSchema``).

``Stream(success, error)`` is the success schema of a streaming RPC: its
values are streams of ``success`` items failing with ``error``.
``ClientAbort`` annotates the interruption of a request the client
cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeIs, TypeVar, cast

from pyfect._stack_frame import StackFrame, StackTrace
from pyfect.context import Context, Tag
from pyfect.schema import Bottom, Codec, Top, declare
from pyfect.stream import Stream as _Stream

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)


def _is_stream(value: object) -> TypeIs[_Stream[Any, Any, Any]]:
    return isinstance(value, _Stream)


_STREAM = declare(_is_stream, expected="Stream")


@dataclass(frozen=True, slots=True, eq=False)
class StreamSchema(Bottom[_Stream[A_co, E_co], _Stream[A_co, E_co]], Generic[A_co, E_co]):
    """The schema of a streaming result: streams of ``success`` items that
    fail with ``error``. Only its parts cross the wire."""

    success: Codec[A_co, Any, Any, Any]
    error: Codec[E_co, Any, Any, Any]


def Stream[A, E](
    success: Codec[A, Any, Any, Any], error: Codec[E, Any, Any, Any], /
) -> StreamSchema[A, E]:
    """The success schema of an RPC streaming ``success`` items and failing
    with ``error`` (Effect's ``RpcSchema.Stream``)."""
    return StreamSchema(_STREAM.ast, success, error)


def is_stream_schema(schema: object) -> TypeIs[StreamSchema[Any, Any]]:
    return isinstance(schema, StreamSchema)


@dataclass(frozen=True, slots=True)
class StreamSchemas:
    """The item and error schemas of a streaming result."""

    success: Top
    error: Top


def get_stream_schemas(schema: object) -> StreamSchemas | None:
    """The parts of a ``Stream`` schema; ``None`` for any other schema."""
    if not isinstance(schema, StreamSchema):
        return None
    stream = cast("StreamSchema[Any, Any]", schema)
    return StreamSchemas(stream.success.__codec__(), stream.error.__codec__())


def _no_location() -> None:
    return None


class ClientAbort(Tag[bool], key="effect/rpc/RpcSchema/ClientAbort"):
    """Annotates the interruption of a request whose client cancelled it."""

    annotation: Context[Any]


ClientAbort.annotation = Context.make(ClientAbort, True).add(
    StackTrace, StackFrame("ClientAbort", _no_location)
)


__all__ = [
    "ClientAbort",
    "Stream",
    "StreamSchema",
    "StreamSchemas",
    "get_stream_schemas",
    "is_stream_schema",
]
