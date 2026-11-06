"""What each stdio server does when its input ends, whenever that happens.

Effect's ``McpServer.layerStdio`` and ``RpcServer.layerProtocolStdio`` interrupt the fiber that
built them (run under Node: ``Layer.launch`` of either exits 130, every time, with stdin at
EOF, and a program in the scope of ``layerStdio`` is interrupted too). pyfect's layers do the
same. ``mcp_server.run_stdio`` has no Effect counterpart: it returns, so the exit is a success.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import exit as exit_
from pyfect import layer, sink, stdio, stream, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol, mcp_server, tool, toolkit
from pyfect.errors import Done
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, RpcRequest, make, serialization
from pyfect.rpc import server as rpc_server

_PROTOCOLS = (mcp_protocol.v2025_11_25,)
_PING = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n").encode()
_ROOT = Path(__file__).parent.parent

# How long the input stays open: from before the writer has run to well after it is waiting.
_OPEN_FOR = [*range(12), 50]


class _Greeter(RpcGroup):
    hello = make("hello", payload=S.String, success=S.String)


def _hello(_: RpcRequest[str]) -> fx.Effect[str]:
    return fx.succeed("world")


_RPC_SERVER: Any = (
    rpc_server.layer(_Greeter)
    .pipe(layer.provide(_Greeter.to_layer(_Greeter.handlers().handle(_Greeter.hello)(_hello))))
    .pipe(layer.provide(rpc_server.layer_protocol_stdio))
    .pipe(layer.provide(serialization.layer_ndjson))
)


class _EchoParams(TypedDict):
    text: str


_Echo = tool.make("echo", parameters=S.Struct(_EchoParams), success=S.String)
_Tools = toolkit.make(_Echo)
_TOOL_HANDLERS = _Tools.to_layer(_Echo.handler(lambda params, _: fx.succeed(params["text"])))
_APP: Any = mcp_server.toolkit(_Tools).pipe(layer.provide(_TOOL_HANDLERS))


def _input(lines: tuple[bytes, ...] = ()) -> Any:
    """Input a test ends by hand, and the ``Stdio`` over it whose output lands in ``written``."""
    stdin = Queue[bytes, Done]()
    for line in lines:
        stdin.offer_unsafe(line)
    written: list[str] = []

    def write(data: str | bytes) -> fx.Effect[None]:
        text = data if isinstance(data, str) else data.decode()
        return fx.sync(lambda: written.append(text))

    def output(*, end_on_done: bool = False) -> Any:
        return sink.for_each(write)

    return stdin, written, stdio.layer_test(stdin=stream.from_queue(stdin), stdout=output)


def _run_stdio() -> Any:
    return mcp_server.run_stdio(name="s", version="1", protocols=_PROTOCOLS)


def _layer_stdio() -> Any:
    return mcp_server.layer_stdio(name="s", version="1", protocols=_PROTOCOLS)


def _forked(effect: Any) -> fx.Effect[Any]:
    return effect.fork()


def _yields(count: int) -> fx.Effect[None]:
    return fx.for_each(range(count), lambda _: fx.yield_now()).as_void()


def _exit_soon(fiber: Any) -> fx.Effect[Any]:
    """The fiber's exit; a server that runs on after its input ended fails, not hangs."""

    @fx.gen
    def wait():
        yield from _yields(500)
        ended = fiber.poll_unsafe()
        assert ended is not None, "still running after its input ended"
        return ended

    return wait


def _interrupted(ended: exit_.Exit[Any, Any]) -> bool:
    return isinstance(ended, exit_.Failure) and ended.cause.has_interrupts_only


@pytest.mark.parametrize("open_for", _OPEN_FOR)
@testing.effect
def test_run_stdio_succeeds_whenever_its_input_ends(open_for: int):
    stdin, _, io = _input()
    server = yield from mcp_server.make()
    served = _run_stdio().pipe(fx.provide_service(mcp_server.McpServer, server))
    fiber = yield from _forked(served.pipe(fx.provide(io)))
    yield from _yields(open_for)
    yield from stdin.end()
    assert exit_.is_success((yield from _exit_soon(fiber)))


@testing.effect
def test_run_stdio_writes_its_answers_before_it_returns():
    stdin, written, io = _input((_PING,))
    server = yield from mcp_server.make()
    served = _run_stdio().pipe(fx.provide_service(mcp_server.McpServer, server))
    fiber = yield from _forked(served.pipe(fx.provide(io)))
    yield from _yields(50)
    yield from stdin.end()
    assert exit_.is_success((yield from _exit_soon(fiber)))
    assert [json.loads(line)["id"] for line in "".join(written).splitlines()] == [1]


@pytest.mark.parametrize("open_for", _OPEN_FOR)
@testing.effect
def test_launching_mcp_layer_stdio_is_interrupted_when_its_input_ends(open_for: int):
    stdin, _, io = _input()
    server = _layer_stdio().pipe(layer.provide(io))
    fiber = yield from _forked(server.launch())
    yield from _yields(open_for)
    yield from stdin.end()
    assert _interrupted((yield from _exit_soon(fiber)))


@testing.effect
def test_launching_mcp_layer_stdio_below_a_toolkit_is_interrupted_when_its_input_ends():
    """The shape ``mcp_server``'s docs give. Under ``layer.merge`` the layer builds on a fiber of
    its own that has finished by then, so nothing ends, in Effect as well (run under Node)."""
    stdin, _, io = _input()
    server = _layer_stdio()
    served = _APP.pipe(layer.provide_merge(server)).pipe(layer.provide(io))
    fiber = yield from _forked(served.launch())
    yield from _yields(5)
    yield from stdin.end()
    assert _interrupted((yield from _exit_soon(fiber)))


@testing.effect
def test_a_program_in_the_scope_of_mcp_layer_stdio_is_interrupted_when_its_input_ends():
    stdin, _, io = _input()
    finish = fx.Deferred[None]()

    @fx.gen
    def program():
        yield from _layer_stdio().pipe(layer.provide(io)).build()
        yield from finish.wait()

    fiber = yield from _forked(fx.scoped(program))
    yield from _yields(5)
    yield from stdin.end()
    assert _interrupted((yield from _exit_soon(fiber)))


@testing.effect
def test_a_program_that_finishes_in_the_scope_of_mcp_layer_stdio_is_interrupted():
    """As in Effect (run under Node): closing the scope ends the server, which interrupts its
    builder, even with the input still open."""
    _, _, io = _input()

    @fx.gen
    def program():
        yield from _layer_stdio().pipe(layer.provide(io)).build()
        yield from _yields(5)
        return "finished"

    fiber = yield from _forked(fx.scoped(program))
    assert _interrupted((yield from _exit_soon(fiber)))


@pytest.mark.parametrize("open_for", _OPEN_FOR)
@testing.effect
def test_launching_rpc_layer_protocol_stdio_is_interrupted_when_its_input_ends(open_for: int):
    stdin, _, io = _input()
    fiber = yield from _forked(_RPC_SERVER.pipe(layer.provide(io)).launch())
    yield from _yields(open_for)
    yield from stdin.end()
    assert _interrupted((yield from _exit_soon(fiber)))


_SERVER_PROGRAM = """
import pyfect as fx
from pyfect import layer, stdio
from pyfect.ai import mcp_protocol, mcp_server
fx.run_main(
    mcp_server.layer_stdio(name="s", version="1", protocols=(mcp_protocol.v2025_11_25,))
    .pipe(layer.provide(stdio.layer))
    .launch()
)
"""
_EXAMPLE = str(_ROOT / "examples" / "mcp_server.py")
_INITIALIZE = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
)


def _exit_code(*args: str, then_close: Callable[[subprocess.Popen[str]], None]) -> int:
    with subprocess.Popen(
        [sys.executable, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=_ROOT,
    ) as server:
        then_close(server)
        _, stderr = server.communicate(timeout=30)
    assert stderr == ""
    return server.returncode


def _at_once(_: subprocess.Popen[str]) -> None:
    pass


def _open_with_no_input(_: subprocess.Popen[str]) -> None:
    time.sleep(1)


def _after_initialize(server: subprocess.Popen[str]) -> None:
    assert server.stdin is not None
    assert server.stdout is not None
    print(_INITIALIZE, file=server.stdin, flush=True)
    assert json.loads(server.stdout.readline())["id"] == 1
    time.sleep(1)


_MODES = [_at_once, _open_with_no_input, _after_initialize]


@pytest.mark.parametrize("then_close", _MODES)
def test_a_real_run_stdio_process_exits_0_when_its_input_closes(
    then_close: Callable[[subprocess.Popen[str]], None],
):
    """The backstop for what the tests above can't reach: real stdin on a real thread."""
    assert _exit_code(_EXAMPLE, then_close=then_close) == 0


@pytest.mark.parametrize("then_close", _MODES)
def test_a_real_layer_stdio_process_exits_130_when_its_input_closes(
    then_close: Callable[[subprocess.Popen[str]], None],
):
    assert _exit_code("-c", _SERVER_PROGRAM, then_close=then_close) == 130


def test_run_stdio_exits_0_every_time_with_input_closed_from_the_start():
    runs = [
        subprocess.run(
            [sys.executable, _EXAMPLE],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        ).returncode
        for _ in range(10)
    ]
    assert runs == [0] * 10
