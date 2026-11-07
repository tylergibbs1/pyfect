"""Ports of Effect's ``SchemaCompilerConcurrency.test.ts``.

Python mappings: a getter property on the input is a ``Getters`` mapping;
``makeEffect(schema)(input, { parseOptions })`` is
``S.make_effect(schema)(input, **options)``.
"""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.deferred import Deferred
from pyfect.schema import jit_compiler

from ._schema_binary import struct
from ._schema_compiler import Getters, fresh_registry

__all__ = ["fresh_registry"]


@testing.effect
def test_isolates_concurrent_executions_without_replaying_the_eager_prefix():
    """isolates concurrent executions without replaying the eager prefix"""
    started = yield from Deferred[None].make()
    counts = {"ids": 0, "tails": 0}

    def next_id() -> Any:
        counts["ids"] += 1
        id = counts["ids"]
        if id == 2:
            yield from started.succeed(None)
        yield from started.wait()
        return id

    def tail() -> str:
        counts["tails"] += 1
        return "tail"

    schema = struct(
        prefix=S.String,
        id=S.Number.pipe(S.with_constructor_default(fx.gen(next_id))),
        tail=S.String.pipe(S.with_constructor_default(fx.sync(tail))),
    )
    jit_compiler.enable(schema.ast)
    input = Getters({"prefix": "prefix"})
    program = S.make_effect(schema)(input)
    assert input.reads["prefix"] == 1
    results = yield from fx.all(program, program, concurrency="unbounded")
    assert list(results) == [
        {"prefix": "prefix", "id": 1, "tail": "tail"},
        {"prefix": "prefix", "id": 2, "tail": "tail"},
    ]
    assert results[0] is not results[1]
    assert input.reads["prefix"] == 1
    assert counts == {"ids": 2, "tails": 2}


@pytest.mark.parametrize("product", ["Struct", "Tuple"])
@testing.effect
def test_preserves_bounded_concurrency_and_runs_defaults_once(product: str):
    """${product} preserves bounded concurrency and runs defaults once"""
    started = yield from fx.for_each(range(3), lambda _: Deferred[None].make())
    releases = yield from fx.for_each(range(3), lambda _: Deferred[None].make())
    calls = [0, 0, 0]

    def field(index: int) -> Any:
        def default() -> Any:
            calls[index] += 1
            yield from started[index].succeed(None)
            yield from releases[index].wait()
            return index

        return S.Number.pipe(S.with_constructor_default(fx.gen(default)))

    fields = [field(i) for i in range(3)]
    schema: Any = (
        struct(a=fields[0], b=fields[1], c=fields[2])
        if product == "Struct"
        else S.Tuple(fields[0], fields[1], fields[2])
    )
    jit_compiler.enable(schema.ast)
    fiber = yield from S.make_effect(schema)(
        {} if product == "Struct" else (), concurrency=2
    ).fork()
    yield from started[0].wait()
    yield from started[1].wait()
    assert not (yield from started[2].is_done())
    yield from releases[0].succeed(None)
    yield from started[2].wait()
    yield from releases[1].succeed(None)
    yield from releases[2].succeed(None)
    expected = {"a": 0, "b": 1, "c": 2} if product == "Struct" else (0, 1, 2)
    assert (yield from fiber.join()) == expected
    assert calls == [1, 1, 1]
