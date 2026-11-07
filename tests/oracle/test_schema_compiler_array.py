"""Ports of Effect's ``SchemaCompilerArray.test.ts``.

Python mappings: a getter at an array index is a ``list`` subclass counting
reads of that index. A Python list has no holes, so the sparse input of
"keeps detailed errors and sparse input behavior" and the optional half of
"passes missing constructor results to the shared element step" (an
``optionalKey`` element leaving a hole) have no counterpart; ``S.Array``
takes no optional element.
"""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.deferred import Deferred
from pyfect.exit import Success
from pyfect.schema import compiler as SC
from pyfect.schema import getter as G
from pyfect.schema import jit_compiler
from pyfect.schema import transformation as T

from ._schema_compiler import fresh_registry

__all__ = ["fresh_registry"]


def _decoding(getter: G.Getter[Any, Any]) -> T.Transformation[Any, Any]:
    return T.Transformation(getter, G.passthrough())


@testing.effect
def test_keeps_detailed_errors_and_sparse_input_behavior():
    """keeps detailed errors and sparse input behavior"""
    schema = S.Array(S.NumberFromString)
    inputs: list[object] = [["1", "2"], ["bad", "2"], ["1", "bad", "bad"]]

    def snapshot() -> fx.Effect[list[object]]:
        def run() -> Any:
            parse = S.decode_unknown_effect(schema)
            results: list[object] = []
            for errors in ("first", "all"):
                for input in inputs:
                    result = yield from parse(input, errors=errors).result()
                    results.append(result)
            return results

        return fx.gen(run)

    interpreted = yield from snapshot()
    jit_compiler.enable(schema.ast)
    assert (yield from snapshot()) == interpreted


class _CountedList(list[object]):
    """A list counting reads of index 0 (Effect's getter at ``"0"``)."""

    reads = 0

    def __getitem__(self, index: Any) -> Any:
        if index == 0:
            self.reads += 1
        return super().__getitem__(index)


@testing.effect
def test_resumes_without_replaying_the_pending_element_or_rereading_its_accessor():
    """resumes without replaying the pending element or rereading its accessor"""
    events: list[str] = []

    def upper(value: str, _: object) -> fx.Effect[str]:
        def run() -> Any:
            events.append(value)
            yield from fx.yield_now()
            return value.upper()

        return fx.gen(run)

    element = S.String.pipe(S.decode(_decoding(G.transform_effect(upper))))
    schema = S.Array(element)
    input = _CountedList(["a", "b"])
    jit_compiler.enable(schema.ast)
    assert (yield from S.decode_unknown_effect(schema)(input)) == ("A", "B")
    assert events == ["a", "b"]
    assert input.reads == 1


def test_passes_missing_constructor_results_to_the_shared_element_step():
    """passes missing constructor results to the shared element step"""
    element = S.String.annotate(title="Array constructor element")
    SC.set(
        element.ast,
        SC.CompiledDecoder(
            decode_effect=lambda i, _o: Success(i), make_effect=lambda _i, _o: Success(SC.MISSING)
        ),
    )
    schema = S.Array(element)
    jit_compiler.enable(schema.ast)
    make = S.make(schema)
    try:
        make(("a",))
    except S.SchemaError:
        pass
    else:
        raise AssertionError("expected a SchemaError")


@testing.effect
def test_keeps_bounded_concurrency_on_the_interpreter_s_concurrent_traversal():
    """keeps bounded concurrency on the interpreter's concurrent traversal"""
    started = yield from fx.for_each(range(3), lambda _: Deferred[None].make())
    releases = yield from fx.for_each(range(3), lambda _: Deferred[None].make())
    calls = [0, 0, 0]

    def run(index: int, _: object) -> fx.Effect[int]:
        calls[index] += 1
        return started[index].succeed(None).and_then(releases[index].wait()).as_(index)

    element = S.Number.pipe(S.decode(_decoding(G.transform_effect(run))))
    schema = S.Array(element)
    jit_compiler.enable(schema.ast)
    fiber = yield from S.decode_unknown_effect(schema)([0, 1, 2], concurrency=2).fork()
    yield from started[0].wait()
    yield from started[1].wait()
    assert not (yield from started[2].is_done())
    yield from releases[0].succeed(None)
    yield from started[2].wait()
    yield from releases[1].succeed(None)
    yield from releases[2].succeed(None)
    assert (yield from fiber.join()) == (0, 1, 2)
    assert calls == [1, 1, 1]
