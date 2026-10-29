"""``McpClientError`` messages follow Effect's ``description ?? default``:
an empty description is kept (checked against Effect's
``McpClientError.ts`` under Node)."""

from pyfect.ai import mcp_client_error as M


def test_empty_description_is_kept():
    assert M.TransportError(description="").message == ""
    assert M.ProtocolError(description="").message == ""
    assert M.ProtocolError(description="", code=1).message == " (code 1)"
    assert M.ClosedError(description="").message == ""


def test_missing_description_uses_the_default():
    assert M.TransportError().message == "MCP transport failed"
    assert M.ProtocolError(code=-32601).message == "MCP protocol error (code -32601)"
    assert M.ClosedError().message == "MCP connection closed"
    assert M.ClosedError(description="", session_expired=True).message == "MCP session expired"
