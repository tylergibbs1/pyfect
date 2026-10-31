"""Standard output of a stdio MCP server carries the protocol and nothing
else (QA ai-workflow MCP-4): a logged tool defect goes to standard error,
and no code on the server's path writes to standard output itself."""

from __future__ import annotations

import ast
from pathlib import Path

from oracle._mcp import stdio_harness

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.console import CurrentConsole

Boom = T.make("Boom", parameters=T.EMPTY_PARAMS, success=S.String)
_kit = K.make(Boom)


def _boom(_: object, __: object) -> fx.Effect[str]:
    raise RuntimeError("secret internal detail")


@testing.effect
def test_a_tool_defect_is_logged_to_stderr_not_stdout():
    console = testing.TestConsole()
    registered = M.register_toolkit(_kit).pipe(fx.provide(_kit.to_layer(Boom.handler(_boom))))
    harness = yield from stdio_harness(P.v2025_11_25, None, registered).pipe(
        fx.provide_service(CurrentConsole, console)
    )
    yield from harness.initialize()
    answer = yield from harness.send_request("tools/call", {"name": "Boom", "arguments": {}})
    assert answer["result"]["isError"] is True
    assert console.entries, "the defect is logged"
    assert {method for method, _ in console.entries} == {"error"}


_SERVER_PATH = Path(__file__).parent.parent / "src" / "pyfect" / "ai"
_STDOUT_NAMES = {"stdout", "__stdout__"}


def test_nothing_on_the_ai_server_path_writes_to_stdout():
    """``print`` and ``sys.stdout`` would write between protocol messages
    (a child process's ``stdout``, which the client reads, is fine)."""
    offenders: list[str] = []
    for path in sorted(_SERVER_PATH.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
                offenders.append(f"{path.name}:{node.lineno} print")
            if (
                isinstance(node, ast.Attribute)
                and node.attr in _STDOUT_NAMES
                and getattr(node.value, "id", None) == "sys"
            ):
                offenders.append(f"{path.name}:{node.lineno} {node.attr}")
    assert offenders == []
