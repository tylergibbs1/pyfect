"""RPC messages as JSON-RPC 2.0 (the framing-free half of Effect's
``RpcSerialization.jsonRpc``).

A request batch (an array) is answered by one array once each of its
requests has its exit; ``Batches`` tracks them per connection.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from pyfect._json_text import stringify

EFFECT_METHOD = "@effect/rpc/"
JSON_RPC_INTERNAL_ERROR = -32603
_CONTROL_TAGS = frozenset({"Ping", "Pong", "Interrupt", "Ack", "Eof"})

type Message = dict[str, Any]


@dataclass(slots=True, eq=False)
class _Batch:
    size: int = 0
    responses: dict[object, Mapping[str, Any]] = field(
        default_factory=dict[object, Mapping[str, Any]]
    )


type Batches = dict[object, _Batch]


def _key(request_id: object) -> object:
    """A request id as a dict key: ``1`` and ``"1"`` stay apart, as in a JS
    ``Map``."""
    return (type(request_id), request_id)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return cast("Mapping[str, Any]", value) if isinstance(value, Mapping) else None


# --- decoding --------------------------------------------------------------------------


def decode_json_rpc(
    decoded: object, batches: Batches, *, control_messages: bool = True
) -> list[object]:
    """The messages of a parsed JSON-RPC value; items that are not objects
    are skipped. Without ``control_messages``, an ``@effect/rpc/*`` method
    is an ordinary notification, for plain JSON-RPC peers."""
    if isinstance(decoded, list):
        batch = _Batch()
        messages: list[object] = []
        for item in cast("list[object]", decoded):
            found = _mapping(item)
            if found is None:
                continue
            message = _decode_message(found, control_messages)
            messages.append(message)
            if message["_tag"] == "Request" and not message.get("isNotification"):
                batch.size += 1
                batches[_key(message["id"])] = batch
        return messages
    found = _mapping(decoded)
    return [] if found is None else [_decode_message(found, control_messages)]


def _decode_message(decoded: Mapping[str, Any], control_messages: bool) -> Message:
    if "method" in decoded:
        return _decode_request(decoded, control_messages)
    return _decode_response(decoded)


def _decode_request(request: Mapping[str, Any], control_messages: bool) -> Message:
    method = request["method"]
    request_id = request.get("id")
    if (
        control_messages
        and request_id is None
        and isinstance(method, str)
        and method.startswith(EFFECT_METHOD)
    ):
        tag = method[len(EFFECT_METHOD) :]
        params = _mapping(request.get("params"))
        if params is not None and "requestId" in params:
            return {"_tag": tag, "requestId": params["requestId"]}
        return {"_tag": tag}
    params = request.get("params")
    headers = request.get("headers")
    message: Message = {
        "_tag": "Request",
        "id": "" if request_id is None else request_id,
        "tag": method,
        "payload": params,
        "headers": [] if headers is None else headers,
    }
    if "id" not in request:
        message["isNotification"] = True
    if request.get("discard") is True:
        message["discard"] = True
    if request.get("spanId"):
        message["traceId"] = request.get("traceId")
        message["spanId"] = request["spanId"]
        message["sampled"] = request.get("sampled")
    return message


def _decode_response(response: Mapping[str, Any]) -> Message:
    response_id = response.get("id")
    request_id = "" if response_id is None else response_id
    error = _mapping(response.get("error")) if "error" in response else None
    if error is not None and error.get("_tag") == "Defect":
        return {"_tag": "Defect", "defect": error.get("data")}
    if response.get("chunk") is True:
        return {"_tag": "Chunk", "requestId": request_id, "values": response.get("result")}
    if error is None:
        exit: Message = {"_tag": "Success", "value": response.get("result")}
    elif error.get("_tag") == "Cause":
        exit = {"_tag": "Failure", "cause": error.get("data")}
    else:
        exit = {"_tag": "Failure", "cause": [{"_tag": "Fail", "error": error}]}
    return {"_tag": "Exit", "requestId": request_id, "exit": exit}


# --- encoding --------------------------------------------------------------------------


def encode_json_rpc(response: object, batches: Batches) -> Message | list[Message] | None:
    """The JSON-RPC value of a message or a list of them; ``None`` while a
    batch waits for more of its exits."""
    if not isinstance(response, list):
        return _encode_raw(cast("Mapping[str, Any]", response), batches)
    encoded = [
        e
        for r in cast("list[Mapping[str, Any]]", response)
        if (e := _encode_raw(r, batches)) is not None
    ]
    if not encoded:
        return None
    if len(encoded) == 1:
        return encoded[0]
    messages: list[Message] = []
    for current in encoded:
        if isinstance(current, list):
            messages.extend(current)
        else:
            messages.append(current)
    return messages


def _encode_raw(response: Mapping[str, Any], batches: Batches) -> Message | list[Message] | None:
    # Only exits complete a batch: chunks and control messages go out at once.
    if response["_tag"] != "Exit":
        return _encode_message(response)
    key = _key(response["requestId"])
    batch = batches.pop(key, None)
    if batch is None:
        return _encode_message(response)
    batch.responses[key] = response
    if batch.size == len(batch.responses):
        return [_encode_message(r) for r in batch.responses.values()]
    return None


def _encode_message(response: Mapping[str, Any]) -> Message:
    tag = response["_tag"]
    if tag == "Request":
        return _encode_request(response)
    if tag in _CONTROL_TAGS:
        message: Message = {"jsonrpc": "2.0", "method": EFFECT_METHOD + tag}
        if "requestId" in response:
            message["params"] = {"requestId": response["requestId"]}
        return message
    if tag == "Chunk":
        return {
            "jsonrpc": "2.0",
            "chunk": True,
            "id": response["requestId"],
            "result": response["values"],
        }
    if tag == "Exit":
        return _encode_exit(response)
    return {
        "jsonrpc": "2.0",
        "id": JSON_RPC_INTERNAL_ERROR,
        "error": {
            "_tag": "Defect",
            "code": 1,
            "message": "A defect occurred",
            "data": response.get("defect"),
        },
    }


def _encode_request(request: Mapping[str, Any]) -> Message:
    message: Message = {
        "jsonrpc": "2.0",
        "method": request["tag"],
        "params": request.get("payload"),
    }
    if not request.get("isNotification"):
        message["id"] = request["id"]
    if request.get("headers"):
        message["headers"] = request["headers"]
    if request.get("discard"):
        message["discard"] = True
    for key in ("traceId", "spanId", "sampled"):
        if request.get(key) is not None:
            message[key] = request[key]
    return message


def _encode_exit(response: Mapping[str, Any]) -> Message:
    exit = cast("Mapping[str, Any]", response["exit"])
    message: Message = {"jsonrpc": "2.0"}
    if response.get("requestId") is not None:
        message["id"] = response["requestId"]
    if exit["_tag"] == "Success":
        message["result"] = exit.get("value")
        return message
    cause = cast("Sequence[Mapping[str, Any]]", exit["cause"])
    failure = next((f for f in cause if f.get("_tag") == "Fail"), None)
    error = None if failure is None else _mapping(failure.get("error"))
    message["error"] = {
        "_tag": "Cause",
        "code": 0 if error is None or "code" not in error else _number(error["code"]),
        "message": error["message"]
        if error is not None and "message" in error
        else stringify(cause),
        "data": cause,
    }
    return message


def _number(value: object) -> int | float | None:
    """JS ``Number(value)`` as JSON writes it: ``None`` for ``NaN``."""
    if isinstance(value, (bool, int)):
        return int(value)
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if value is None:
        return 0
    try:
        number = float(value.strip() or "0") if isinstance(value, str) else math.nan
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return int(number) if number.is_integer() else number


__all__ = [
    "EFFECT_METHOD",
    "JSON_RPC_INTERNAL_ERROR",
    "Batches",
    "decode_json_rpc",
    "encode_json_rpc",
]
