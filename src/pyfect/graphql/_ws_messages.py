"""graphql-transport-ws server messages, parsed and checked as
graphql-ws's ``validateMessage`` does, so the transport only sees valid
ones."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeIs, cast

from pyfect.socket._socket import Chunk


@dataclass(frozen=True, slots=True)
class Ack:
    """``connection_ack``."""


@dataclass(frozen=True, slots=True)
class Ping:
    """``ping``: answered with ``pong``."""


@dataclass(frozen=True, slots=True)
class Pong:
    """``pong``."""


@dataclass(frozen=True, slots=True)
class Next:
    """``next``: one result of operation ``id``."""

    id: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Error:
    """``error``: the server rejected operation ``id``."""

    id: str
    payload: Sequence[Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class Complete:
    """``complete``: operation ``id`` has no more results."""

    id: str


@dataclass(frozen=True, slots=True)
class Invalid:
    """A frame that is not a valid server message, and why."""

    reason: str
    cause: BaseException | None = None


type ServerMessage = Ack | Ping | Pong | Next | Error | Complete


def _is_object(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, dict)


def _formatted_errors(payload: object) -> Sequence[Mapping[str, object]] | None:
    # At least one entry, each with a ``message``.
    if not isinstance(payload, list):
        return None
    errors = cast("list[object]", payload)
    valid = [error for error in errors if _is_object(error) and "message" in error]
    return valid if errors and len(valid) == len(errors) else None


def _type_name(message: Mapping[str, object]) -> str:
    return json.dumps(message["type"]) if "type" in message else "undefined"


def _keep_alive(kind: str, payload: object) -> ServerMessage | Invalid:
    if payload is not None and not _is_object(payload):
        return Invalid(f"{kind} with a payload that is not an object")
    return Ack() if kind == "connection_ack" else Ping() if kind == "ping" else Pong()


def _for_operation(kind: str, message: Mapping[str, object]) -> ServerMessage | Invalid:
    id = message.get("id")
    payload = message.get("payload")
    if not isinstance(id, str) or id == "":
        return Invalid(f"{kind} without an id")
    if kind == "complete":
        return Complete(id)
    if kind == "next":
        return (
            Next(id, payload)
            if _is_object(payload)
            else Invalid("next with a payload that is not an object")
        )
    errors = _formatted_errors(payload)
    if errors is None:
        return Invalid("error with a payload that is not a list of GraphQL errors")
    return Error(id, errors)


def parse(frame: Chunk) -> ServerMessage | Invalid:
    """The server message ``frame`` holds. The shape is checked before
    any id lookup, so an unknown id does not excuse an invalid message."""
    try:
        parsed: object = json.loads(frame if isinstance(frame, str) else bytes(frame))
    except ValueError as cause:
        return Invalid(str(cause), cause)
    if not _is_object(parsed):
        return Invalid("expected an object")
    kind = parsed.get("type")
    if kind in ("connection_ack", "ping", "pong"):
        return _keep_alive(cast("str", kind), parsed.get("payload"))
    if kind in ("next", "error", "complete"):
        return _for_operation(cast("str", kind), parsed)
    return Invalid(f"unknown type {_type_name(parsed)}")
