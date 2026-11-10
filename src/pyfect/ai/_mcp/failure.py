"""The JSON-RPC error of a failed request whose cause holds an interruption
(Effect's ``RpcServer`` exit encoding under the MCP serialization).

Effect writes a failed exit as ``{"_tag": "Cause", code, message, data}``:
``code`` and ``message`` from the cause's first ``Fail``, ``data`` the cause.
The MCP serialization strips that to the bare error only when the cause is
one ``Fail``; middleware that adds an interruption keeps the cause whole, so
its answer carries the serialized cause. A cause with no ``Fail`` is an
internal error. Each ``Fail`` is first mapped as the method maps failures:
``ProtocolError.fromFeature``, or for a legacy ``tools/call``
``ProtocolError.fromTool``, which cannot map a middleware's failure and so
dies (an internal error).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

from pyfect import schema as S
from pyfect.ai._mcp.invoke import RequestRejected
from pyfect.ai.mcp_schema import INTERNAL_ERROR_CODE, JsonRpcErrorObject, McpError
from pyfect.cause import Cause, Die, Fail, Interrupt

INTERNAL_ERROR: JsonRpcErrorObject = {"code": INTERNAL_ERROR_CODE, "message": "Internal error"}
_FEATURE_FAILED: JsonRpcErrorObject = {
    "code": INTERNAL_ERROR_CODE,
    "message": "MCP feature handler failed",
}
_encode_defect = S.encode_sync(S.to_codec_json(S.Defect()))


def _from_feature(error: object) -> JsonRpcErrorObject:
    """Effect's ``ProtocolError.fromFeature``: an MCP error as itself, else
    any value with a finite ``code`` and a string ``message``."""
    if isinstance(error, RequestRejected):
        return error.error.to_wire()
    if isinstance(error, McpError):
        return error.to_wire()
    if isinstance(error, Mapping):
        fields = cast("Mapping[str, Any]", error)
        code, message = fields.get("code"), fields.get("message")
        number = isinstance(code, int | float) and not isinstance(code, bool)
        if number and math.isfinite(cast("float", code)) and isinstance(message, str):
            wire: JsonRpcErrorObject = {"code": cast("int", code), "message": message}
            if "data" in fields:
                wire["data"] = fields["data"]
            return wire
    return _FEATURE_FAILED


def _reason(reason: object) -> dict[str, Any]:
    if isinstance(reason, Fail):
        return {"_tag": "Fail", "error": _from_feature(cast("Fail[Any]", reason).error)}
    if isinstance(reason, Die):
        return {"_tag": "Die", "defect": _encode_defect(reason.defect)}
    return {"_tag": "Interrupt", "fiberId": cast("Interrupt", reason).fiber_id}


def interrupted_failure(cause: Cause[object], *, legacy_tool_call: bool) -> Mapping[str, Any]:
    """The error answering ``cause``, a failure holding an interruption."""
    first = next((r for r in cause.reasons if isinstance(r, Fail)), None)
    if first is None or legacy_tool_call:
        return INTERNAL_ERROR
    error = _from_feature(cast("Fail[Any]", first).error)
    return {
        "_tag": "Cause",
        "code": error["code"],
        "message": error["message"],
        "data": [_reason(r) for r in cause.reasons],
    }


__all__ = ["INTERNAL_ERROR", "interrupted_failure"]
