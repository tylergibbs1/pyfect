"""In ``pyfect.ai``, a fiber stopped from a finalizer has its exit read, so defects surface.

``x.ensuring(fiber.interrupt())`` throws the interrupted fiber's exit away, and with it any
defect its interrupt finalizers raised: Toolkit dropped a tool handler's defects this way
(Effect #10437). Stop it with ``interrupt().and_then(await_exit())`` and decide what the exit
means instead. Only ``pyfect.ai`` is checked: elsewhere (a cluster's monitor fiber, say) the
stopped fiber runs pyfect's own code and Effect drops its exit too.
"""

from __future__ import annotations

import ast

import _source

_SRC = _source.SRC / "ai"


def _discards_exit(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "ensuring"
        and len(node.args) == 1
        and isinstance(arg := node.args[0], ast.Call)
        and isinstance(arg.func, ast.Attribute)
        and arg.func.attr == "interrupt"
        and not arg.args
    )


def test_no_finalizer_interrupts_a_fiber_without_reading_its_exit() -> None:
    found = [
        f"{path.relative_to(_SRC)}:{node.lineno}"
        for path in _source.files(_SRC)
        for node in _source.walk(path)
        if isinstance(node, ast.Call) and _discards_exit(node)
    ]
    assert not found, found


def test_the_guard_sees_the_pattern() -> None:
    call = _source.parse("stream.ensuring(fiber.interrupt())").body[0]
    assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)
    assert _discards_exit(call.value)
