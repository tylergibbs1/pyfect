"""Ports of Effect's ``test/ai/McpServer/McpProtocol.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
Effect's synthetic test adapters carry their own RPC schemas; pyfect's
``ProtocolAdapter`` is a revision's version and policies, so the tests
build adapters with made-up versions.

Omitted:

- ``McpProtocolRegistry / should route to only the selected namespace when
  protocol schemas are incompatible``: adapters do not carry RPC groups to
  namespace; the server picks one adapter per session and projects its
  results for that revision (``pyfect.ai._mcp.projection``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as M
from pyfect.ai._mcp import projection
from pyfect.errors import IllegalArgumentError


def _adapter(version: str) -> P.AnyProtocolAdapter:
    return P.ProtocolAdapter(
        version, "stateful", accepts_batches=False, requires_version_header=True
    )


@testing.effect
def test_rejects_an_empty_declaration():
    """McpProtocolRegistry / should reject an empty declaration when runtime input bypasses the non-empty type"""  # noqa: E501
    error = yield from P.make_registry([]).flip()
    assert isinstance(error, IllegalArgumentError)
    assert "at least one MCP protocol" in str(error)


@testing.effect
def test_rejects_duplicate_versions():
    """McpProtocolRegistry / should reject duplicate versions when distinct adapters declare the same version"""  # noqa: E501
    first = _adapter("test-a")
    second = P.ProtocolAdapter(
        "test-a", "stateless", accepts_batches=True, requires_version_header=False
    )
    error = yield from P.make_registry([first, second]).flip()
    assert isinstance(error, IllegalArgumentError)
    assert "Duplicate MCP protocol version: test-a" in str(error)


@testing.effect
def test_selects_the_matching_adapter():
    """McpProtocolRegistry / should select the matching adapter when the offered version is declared"""  # noqa: E501
    first, second = _adapter("test-a"), _adapter("test-b")
    registry = yield from P.make_registry([first, second])
    assert registry.select("test-b") is second


@testing.effect
def test_selects_the_first_adapter_for_an_unsupported_version():
    """McpProtocolRegistry / should select the first declared adapter when the offered version is unsupported"""  # noqa: E501
    first, second = _adapter("test-a"), _adapter("test-b")
    registry = yield from P.make_registry([first, second])
    assert registry.select("unsupported") is first


@testing.effect
def test_preserves_declaration_order_after_the_source_mutates():
    """McpProtocolRegistry / should preserve declaration order when the source array mutates after registry creation"""  # noqa: E501
    first, second = _adapter("test-a"), _adapter("test-b")
    protocols = [first, second]
    registry = yield from P.make_registry(protocols)
    protocols.reverse()
    assert registry.select("unsupported") is first
    assert registry.select("test-b") is second


def test_accepts_resource_links_in_prompt_messages():
    """MCP v2025-06-18 schema / accepts resource links in prompt messages"""
    message: Any = S.decode_unknown_sync(M.PROMPT_MESSAGE)(
        {
            "role": "user",
            "content": {"type": "resource_link", "uri": "file:///example.txt", "name": "example"},
        }
    )
    assert message["content"]["type"] == "resource_link"
    result: M.GetPromptResult = {"messages": [message]}
    projected = projection.get_prompt_result(P.v2025_06_18, result)
    assert projected["messages"][0]["content"]["type"] == "resource_link"


def test_omits_later_core_annotation_fields():
    """MCP v2025-06-18 schema / omits later core annotation fields"""
    annotations: M.Annotations = {"audience": ["user"], "lastModified": "2026-07-26"}
    assert "lastModified" not in projection.annotations_of(P.v2025_06_18, annotations)
    assert projection.annotations_of(P.v2025_11_25, annotations) == annotations


@dataclass(frozen=True)
class _ForeignUnsupported:
    """An unsupported error from another copy of the class: only its tag
    says what it is."""

    _tag = "McpReverseOperationUnsupported"
    operation: str
    protocol_version: str
    reason: str


def test_preserves_tagged_unsupported_errors():
    """McpProtocol errors / should preserve tagged unsupported errors without requiring the local class prototype"""  # noqa: E501
    unsupported = _ForeignUnsupported("roots/list", "2025-06-18", "Client did not advertise roots")
    assert cast("object", P.reverse_error("roots/list")(unsupported)) is unsupported

    cause = RuntimeError("Transport failed")
    wrapped = P.reverse_error("roots/list")(cause)
    assert isinstance(wrapped, M.McpReverseOperationError)
    assert wrapped.cause is cause
