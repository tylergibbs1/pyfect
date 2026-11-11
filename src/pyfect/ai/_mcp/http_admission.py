"""Whether the Streamable HTTP endpoint takes a POST, before any of it runs
(Effect's ``admitHttp`` and ``selectHttpProtocol``): the session and
protocol-version headers, a 2026-07-28 request's metadata and routing
headers, and which batches a revision accepts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pyfect.ai._mcp import skills
from pyfect.ai._mcp.dispatch import CLIENT_CAPABILITIES_META, PROTOCOL_VERSION_META
from pyfect.ai._mcp.routing_header import decode_routing_header
from pyfect.ai.mcp_protocol import AnyProtocolAdapter, Registry
from pyfect.ai.mcp_schema import (
    HEADER_MISMATCH_ERROR_CODE,
    INVALID_PARAMS_ERROR_CODE,
    INVALID_REQUEST_ERROR_CODE,
    METHOD_NOT_FOUND_ERROR_CODE,
    PARSE_ERROR_CODE,
    UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE,
    JsonObject,
    RequestId,
    parse_request_id,
)

SESSION_HEADER = "mcp-session-id"
VERSION_HEADER = "mcp-protocol-version"
METHOD_HEADER = "mcp-method"
NAME_HEADER = "mcp-name"

STATELESS_METHODS = frozenset(
    {
        "server/discover",
        "completion/complete",
        "prompts/get",
        "prompts/list",
        "resources/list",
        "resources/templates/list",
        "resources/read",
        "tools/call",
        "tools/list",
        "subscriptions/listen",
        "notifications/cancelled",
    }
    | skills.METHODS
)
"""The messages a 2026-07-28 server takes (Effect's ``ClientRpcs``, with the
Skills extension's)."""


@dataclass(frozen=True, slots=True)
class Accepted:
    acknowledge: bool
    """Nothing in the body expects an answer: reply 202."""


@dataclass(frozen=True, slots=True)
class Rejected:
    status: int
    error: JsonObject | None = None
    """The JSON-RPC error of the reply; none for an empty one."""
    id: RequestId | None = None


type Admission = Accepted | Rejected

type Session = AnyProtocolAdapter | Literal["absent", "unknown"]
"""The protocol of the session the POST names, when it names a live one."""


@dataclass(frozen=True, slots=True)
class Unparsable:
    """A body that is not JSON."""


def _record(value: object) -> dict[str, Any] | None:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _is_id(value: object) -> bool:
    return isinstance(value, str) or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    )


def _error(code: int, message: str, data: object = None) -> JsonObject:
    error: JsonObject = {"code": code, "message": message}
    if data is not None:
        error["data"] = cast("Any", data)
    return error


def _header_mismatch(message: str) -> Rejected:
    return Rejected(400, _error(HEADER_MISMATCH_ERROR_CODE, message))


def has_request_protocol_version(message: object) -> bool:
    params = _record((_record(message) or {}).get("params")) or {}
    record = _record(params.get("_meta"))
    return record is not None and PROTOCOL_VERSION_META in record


@dataclass(frozen=True, slots=True)
class Admitter:
    registry: Registry

    @property
    def _stateless(self) -> AnyProtocolAdapter | None:
        return next((p for p in self.registry.protocols if p.is_stateless), None)

    @property
    def _has_stateful(self) -> bool:
        return any(not p.is_stateless for p in self.registry.protocols)

    def unsupported(self, requested: str) -> Rejected:
        data = {"supported": list(self.registry.versions), "requested": requested}
        message = f"Unsupported protocol version '{requested}'"
        return Rejected(400, _error(UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE, message, data))

    def session(
        self, headers: Mapping[str, str], session: Session, *, initialize: bool
    ) -> Rejected | AnyProtocolAdapter | None:
        """The session's protocol, checked against the version header."""
        if session == "unknown":
            return Rejected(404)
        version = headers.get(VERSION_HEADER)
        bound = None if session == "absent" else session
        if not initialize and version is not None:
            if version not in self.registry.versions:
                return self.unsupported(version)
            if (
                bound is not None
                and bound.requires_version_header
                and version != bound.protocol_version
            ):
                return _header_mismatch(
                    f"MCP-Protocol-Version header '{version}' does not match negotiated "
                    f"protocol version '{bound.protocol_version}'"
                )
        return bound

    def select(  # noqa: PLR0911
        self, headers: Mapping[str, str], input: object, session: Session
    ) -> Rejected | AnyProtocolAdapter | None:
        """The protocol ``input`` is served on (``None``: no session yet)."""
        version = headers.get(VERSION_HEADER)
        record = _record(input)
        params = _record((record or {}).get("params"))
        metadata = _record((params or {}).get("_meta"))
        claimed = metadata is not None and PROTOCOL_VERSION_META in metadata
        claim = metadata.get(PROTOCOL_VERSION_META) if metadata is not None else None
        id = (record or {}).get("id")
        is_rpc = record is not None and record.get("jsonrpc") == "2.0"
        method = (record or {}).get("method")
        initialize = is_rpc and method == "initialize" and _is_id(id)
        cancellation = is_rpc and method == "notifications/cancelled" and "id" not in (record or {})
        stateless = self._stateless
        has_stateful = self._has_stateful
        stateless_request = claimed or (
            (not initialize or not has_stateful)
            and stateless is not None
            and (
                version == stateless.protocol_version
                or (not has_stateful and is_rpc and isinstance(method, str) and _is_id(id))
            )
        )
        if not stateless_request:
            return self.session(headers, session, initialize=initialize)
        if version is None:
            return _header_mismatch("MCP-Protocol-Version header is required")
        if not cancellation and (metadata is None or not isinstance(claim, str)):
            return Rejected(
                400, _error(INVALID_PARAMS_ERROR_CODE, "Required request metadata is missing")
            )
        if (not cancellation or claimed) and claim != version:
            return _header_mismatch("MCP-Protocol-Version header does not match request metadata")
        if not cancellation and _record((metadata or {}).get(CLIENT_CAPABILITIES_META)) is None:
            return Rejected(
                400,
                _error(
                    INVALID_PARAMS_ERROR_CODE,
                    f"{CLIENT_CAPABILITIES_META} request metadata is required",
                ),
            )
        if stateless is None or version != stateless.protocol_version:
            return self.unsupported(version)
        if not isinstance(method, str) or headers.get(METHOD_HEADER) != method:
            return _header_mismatch("Mcp-Method header does not match request method")
        key = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}.get(method)
        if key is not None:
            name = (params or {}).get(key)
            header = headers.get(NAME_HEADER)
            if not isinstance(name, str) or header is None or decode_routing_header(header) != name:
                return _header_mismatch("Mcp-Name header does not match request parameters")
        return stateless

    def admit(  # noqa: PLR0911
        self, headers: Mapping[str, str], parsed: object, session: Session
    ) -> Admission:
        """Whether to serve a POST of ``parsed`` (``Unparsable()`` for a
        body that is not JSON)."""
        if isinstance(parsed, Unparsable):
            version = headers.get(VERSION_HEADER)
            if version is not None and version not in self.registry.versions:
                return self.unsupported(version)
            selected = self.select(headers, None, session)
            # Session and protocol-header errors take precedence over parse errors.
            if isinstance(selected, Rejected) and (
                selected.error is None or selected.error["code"] == HEADER_MISMATCH_ERROR_CODE
            ):
                return selected
            return Rejected(200, _error(PARSE_ERROR_CODE, "Parse error"))
        if isinstance(parsed, list):
            return self._batch(headers, cast("list[object]", parsed), session)
        record = _record(parsed) or {}
        has_id = "id" in record
        id = parse_request_id(record.get("id"))
        is_rpc = record.get("jsonrpc") == "2.0"
        is_request = (
            is_rpc
            and (not has_id or _is_id(record["id"]))
            and isinstance(record.get("method"), str)
        )
        is_response = (
            is_rpc
            and has_id
            and (_is_id(record["id"]) or record["id"] is None)
            and (("result" in record) != ("error" in record))
        )
        selected = self.select(headers, parsed, session)
        if isinstance(selected, Rejected):
            return Rejected(selected.status, selected.error, id)
        if not is_request and not is_response:
            return Rejected(200, _error(INVALID_REQUEST_ERROR_CODE, "Invalid Request"), id)
        method = record.get("method")
        has_session = session != "absent"
        if method == "initialize" and has_session:
            message = "initialize must not include an MCP-Session-Id header"
            return Rejected(400, _error(INVALID_REQUEST_ERROR_CODE, message), id)
        stateless = selected is not None and selected.is_stateless
        if method != "initialize" and not has_session and not stateless:
            if not self._has_stateful:
                return Rejected(400, None, id)
            message = "MCP-Session-Id header is required; send initialize to start a session"
            return Rejected(400, _error(INVALID_REQUEST_ERROR_CODE, message), id)
        if is_request and stateless and method not in STATELESS_METHODS:
            message = f"Method not found: {method}"
            return Rejected(404, _error(METHOD_NOT_FOUND_ERROR_CODE, message), id)
        return Accepted(acknowledge=not is_request or not has_id)

    def _batch(
        self, headers: Mapping[str, str], messages: Sequence[object], session: Session
    ) -> Admission:
        if not messages:
            return Rejected(400, _error(INVALID_REQUEST_ERROR_CODE, "Invalid Request"))
        selected = self.select(headers, messages, session)
        if (
            isinstance(selected, Rejected)
            or any(has_request_protocol_version(m) for m in messages)
            or any((_record(m) or {}).get("method") == "initialize" for m in messages)
            or isinstance(session, str)
            or not session.accepts_batches
        ):
            return Rejected(400)
        expects_answer = any(
            "method" in record and "id" in record
            for record in (_record(m) for m in messages)
            if record is not None
        )
        return Accepted(acknowledge=not expects_answer)
