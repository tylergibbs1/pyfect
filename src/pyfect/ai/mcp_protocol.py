"""The MCP protocol revisions a server or client speaks (Effect's
``McpProtocol``).

Each revision is a ``ProtocolAdapter``: its version, whether it keeps a
session from ``initialize`` (``"stateful"``) or carries the client's
identity in every request's ``_meta`` (``"stateless"``, 2026-07-28), its
JSON-RPC batch and HTTP header policy, and the fields its schema knows.
A server takes a non-empty tuple of them; the first is the one offered
when a client asks for a version the server does not speak::

    mcp_server.layer_stdio(
        name="notes", version="1.0.0",
        protocols=(mcp_protocol.v2025_11_25, mcp_protocol.v2025_06_18),
    )

``make_registry`` checks such a tuple (not empty, no version twice) and
``Registry.select`` picks the adapter for an offered version.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar, cast

from pyfect._core import Effect
from pyfect.ai.mcp_schema import (
    INVALID_PARAMS_ERROR_CODE,
    RESOURCE_NOT_FOUND_ERROR_CODE,
    McpReverseOperationError,
    McpReverseOperationUnsupported,
    ReverseError,
    ReverseOperation,
)
from pyfect.effect import fail, succeed
from pyfect.errors import IllegalArgumentError

type ProtocolVersion = Literal["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]
type StatefulProtocolVersion = Literal["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]
type Runtime = Literal["stateful", "stateless"]

_ORDER: tuple[str, ...] = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28")


V_co = TypeVar("V_co", bound=str, covariant=True, default=ProtocolVersion)
"""Covariant so a revision's adapter is an adapter of any version union it
is in; PEP 695 infers invariance from the dataclass's ``__replace__``."""


@dataclass(frozen=True, slots=True)
class ProtocolAdapter(Generic[V_co]):
    """One MCP revision (see the module docstring)."""

    protocol_version: V_co
    runtime: Runtime
    accepts_batches: bool
    requires_version_header: bool

    def _at_least(self, version: str) -> bool:
        own = _ORDER.index(self.protocol_version) if self.protocol_version in _ORDER else 0
        return own >= _ORDER.index(version)

    @property
    def is_stateless(self) -> bool:
        return self.runtime == "stateless"

    @property
    def supports_audio(self) -> bool:
        """Audio content, tool annotations, the ``completions`` capability
        and progress messages (2025-03-26)."""
        return self._at_least("2025-03-26")

    @property
    def supports_structured_content(self) -> bool:
        """``structuredContent``, ``outputSchema``, resource links, titles
        and elicitation (2025-06-18)."""
        return self._at_least("2025-06-18")

    @property
    def supports_icons(self) -> bool:
        """Icons, ``Implementation.description`` / ``websiteUrl`` and
        ``Annotations.lastModified`` (2025-11-25)."""
        return self._at_least("2025-11-25")

    @property
    def supports_any_structured_content(self) -> bool:
        """``structuredContent`` and ``outputSchema`` of any JSON type, not
        only objects (2026-07-28)."""
        return self._at_least("2026-07-28")

    @property
    def reports_tool_errors_as_results(self) -> bool:
        """A tool's invalid input or execution failure is an ``isError``
        result, not a JSON-RPC error (2025-11-25)."""
        return self._at_least("2025-11-25")

    @property
    def resource_not_found_code(self) -> int:
        """The error code of an unknown resource URI."""
        return INVALID_PARAMS_ERROR_CODE if self.is_stateless else RESOURCE_NOT_FOUND_ERROR_CODE


type AnyProtocolAdapter = ProtocolAdapter[Any]

v2024_11_05: ProtocolAdapter[Literal["2024-11-05"]] = ProtocolAdapter(
    "2024-11-05", "stateful", accepts_batches=False, requires_version_header=False
)
"""MCP 2024-11-05. Over HTTP it is served on the single-endpoint Streamable
HTTP transport, not the historical two-endpoint HTTP+SSE one."""
v2025_03_26: ProtocolAdapter[Literal["2025-03-26"]] = ProtocolAdapter(
    "2025-03-26", "stateful", accepts_batches=True, requires_version_header=False
)
"""MCP 2025-03-26, the revision that accepts JSON-RPC batches."""
v2025_06_18: ProtocolAdapter[Literal["2025-06-18"]] = ProtocolAdapter(
    "2025-06-18", "stateful", accepts_batches=False, requires_version_header=True
)
"""MCP 2025-06-18."""
v2025_11_25: ProtocolAdapter[Literal["2025-11-25"]] = ProtocolAdapter(
    "2025-11-25", "stateful", accepts_batches=False, requires_version_header=True
)
"""MCP 2025-11-25."""
v2026_07_28: ProtocolAdapter[Literal["2026-07-28"]] = ProtocolAdapter(
    "2026-07-28", "stateless", accepts_batches=False, requires_version_header=True
)
"""MCP 2026-07-28: no ``initialize`` and no sessions; each request's
``_meta`` carries the protocol version, client info and capabilities, and
``server/discover`` describes the server."""


@dataclass(frozen=True, slots=True)
class Registry:
    """The adapters a server speaks, in the order given."""

    protocols: tuple[AnyProtocolAdapter, ...]

    def select(self, offered: str | None) -> AnyProtocolAdapter:
        """The adapter of the ``offered`` version, else the first one."""
        for protocol in self.protocols:
            if protocol.protocol_version == offered:
                return protocol
        return self.protocols[0]

    def find(self, version: str) -> AnyProtocolAdapter | None:
        """The adapter of ``version``, if the server speaks it."""
        return next((p for p in self.protocols if p.protocol_version == version), None)

    def select_stateful(self, offered: str | None) -> AnyProtocolAdapter | None:
        """The stateful adapter of ``offered``, else the first stateful one."""
        stateful = [p for p in self.protocols if not p.is_stateless]
        found = next((p for p in stateful if p.protocol_version == offered), None)
        return found or (stateful[0] if stateful else None)

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(p.protocol_version for p in self.protocols)


def make_registry(
    protocols: Sequence[AnyProtocolAdapter],
) -> Effect[Registry, IllegalArgumentError]:
    """The registry of ``protocols``: fails when there are none or two
    declare the same version. Later changes to ``protocols`` are not seen."""
    copied = tuple(protocols)
    if not copied:
        return fail(IllegalArgumentError("McpServer requires at least one MCP protocol"))
    seen: set[str] = set()
    for protocol in copied:
        if protocol.protocol_version in seen:
            return fail(
                IllegalArgumentError(f"Duplicate MCP protocol version: {protocol.protocol_version}")
            )
        seen.add(protocol.protocol_version)
    return succeed(Registry(copied))


def reverse_error(operation: ReverseOperation) -> Callable[[object], ReverseError]:
    """The error of a failed request to the client: an unsupported
    operation (any value tagged ``McpReverseOperationUnsupported``, so one
    from another copy of the class too) stays itself, anything else is
    wrapped in an ``McpReverseOperationError`` of ``operation``."""

    def of(cause: object) -> ReverseError:
        if getattr(cause, "_tag", None) == McpReverseOperationUnsupported._tag:  # pyright: ignore[reportPrivateUsage]
            return cast("McpReverseOperationUnsupported", cause)
        return McpReverseOperationError(operation, cause)

    return of


__all__ = [
    "AnyProtocolAdapter",
    "ProtocolAdapter",
    "ProtocolVersion",
    "Registry",
    "Runtime",
    "StatefulProtocolVersion",
    "make_registry",
    "reverse_error",
    "v2024_11_05",
    "v2025_03_26",
    "v2025_06_18",
    "v2025_11_25",
    "v2026_07_28",
]
