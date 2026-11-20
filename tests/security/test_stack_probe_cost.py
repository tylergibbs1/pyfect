"""(pyfect) A stack probe costs the same at any depth and any recursion limit.

Recursive walks (schema decoding, equality, nested text) ask ``stack_nearly_full`` at every
level whether the next level belongs on a fresh stack. ``sys._getframe(n)`` walks ``n``
frames, so a probe that looks ``getrecursionlimit()`` frames back costs as much as the stack is
deep once the limit is raised, and a deep walk costs the square of its depth.
"""

from __future__ import annotations

import ast
import sys
import threading
import time
from collections.abc import Callable, Iterator
from types import FrameType
from typing import Literal, TypedDict

import _source
import pytest
from _growth import Work, assert_near_linear
from _guards import guards

import pyfect as fx
from pyfect import schema as S
from pyfect._stack import _STACK_FRAMES, stack_nearly_full  # pyright: ignore[reportPrivateUsage]

_RAISED_LIMIT = 100_000
_PROBES = 10


@pytest.fixture(autouse=True)
def _raised_limit() -> Iterator[None]:
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(_RAISED_LIMIT)
    try:
        yield
    finally:
        sys.setrecursionlimit(limit)


class And(TypedDict):
    op: Literal["and"]
    left: And | Or | Eq
    right: And | Or | Eq


class Or(TypedDict):
    op: Literal["or"]
    left: And | Or | Eq
    right: And | Or | Eq


class Eq(TypedDict):
    op: Literal["eq"]
    field: str


def _nested(depth: int) -> object:
    value: object = {"op": "eq", "field": "x"}
    for _ in range(depth):
        value = {"op": "or", "left": {"op": "eq", "field": "y"}, "right": value}
    return value


def _at_depth[A](frames: int, f: Callable[[], A]) -> A:
    return f() if frames <= 0 else _at_depth(frames - 1, f)


def _probes(count: int) -> None:
    for _ in range(count):
        stack_nearly_full()


_GUARD = guards("a8c73765", "stack-probe-walks-to-the-limit")


def test_a_nested_recursive_union_decodes_in_time_linear_in_its_depth() -> None:
    decode = S.decode_unknown_exit(S.Union(S.Struct(And), S.Struct(Or), S.Struct(Eq)))

    def sized(depth: int) -> Work:
        value = _nested(depth)
        return lambda: decode(value)

    assert isinstance(sized(3000)(), fx.Success)
    # Past the first stack the walk runs on other threads: count the process's time.
    assert_near_linear(sized, 16, max_size=4096, clock=time.process_time)


def test_a_probe_at_every_level_costs_time_linear_in_the_depth() -> None:
    # The patch is guarded by the frames counted below, which do not depend on load.
    def sized(depth: int) -> Work:
        return lambda: _at_depth(depth, lambda: _probes(depth))

    assert_near_linear(sized, 64, max_size=1 << 15)


def _frames_walked_by_probes(depth: int, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The frames each of a few probes walks, ``depth`` frames down: ``sys._getframe(n)``
    walks ``n`` frames, or the whole stack when it is shallower than ``n``."""
    getframe = sys._getframe  # pyright: ignore[reportPrivateUsage]
    thread = threading.get_ident()
    walked: list[int] = []

    def counting(n: int = 0) -> FrameType:
        if threading.get_ident() != thread:
            return getframe(n + 1)
        try:
            frame = getframe(n + 1)
        except ValueError:
            walked.append(_stack_depth(getframe(1)))
            raise
        walked.append(n)
        return frame

    with monkeypatch.context() as patch:
        patch.setattr(sys, "_getframe", counting)
        _at_depth(depth, lambda: _probes(_PROBES))
    return walked


def _stack_depth(frame: FrameType | None) -> int:
    depth = 0
    while frame is not None:
        depth, frame = depth + 1, frame.f_back
    return depth


@_GUARD
def test_a_probe_costs_the_same_far_down_a_stack_as_near_its_top(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    near = _frames_walked_by_probes(1_000, monkeypatch)
    far = _frames_walked_by_probes(50_000, monkeypatch)
    assert len(near) == _PROBES, near
    assert far == near, (near, far)
    assert max(near) < _STACK_FRAMES, near


def test_only_the_probe_measures_the_stack() -> None:
    """Whatever a walk asks of the stack's depth goes through ``stack_nearly_full``, whose
    cost is bounded: no other module looks ``getrecursionlimit()`` frames back."""
    src = _source.SRC
    readers: set[str] = set()
    for path in _source.files(src):
        for node in _source.walk(path):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_getframe"
                and any("getrecursionlimit" in ast.unparse(arg) for arg in node.args)
            ):
                readers.add(path.relative_to(src).as_posix())
    assert readers <= {"_stack.py"}, readers
