"""Configs and ZIP encoding let go of what they handled once the run ends,
without the cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

import gc
from collections.abc import Generator
from typing import Any

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect import config, stream
from pyfect import config_provider as cp
from pyfect import schema as S
from pyfect.config import ConfigError
from pyfect.config_provider import Path
from pyfect.encoding import zip as zip_


def _holding(value: Handled, node: cp.Node | None = None) -> cp.ConfigProvider:
    """A provider that keeps ``value``: ``node`` at the root, ``"1"`` elsewhere."""

    def load(path: Path) -> fx.Effect[cp.Node | None]:
        _ = value
        return fx.succeed(node if not path else cp.Value("1"))

    return cp.make(load)


def test_gen_frees_its_provider() -> None:
    @config.gen
    def read() -> Generator[fx.Effect[Any, ConfigError], Any, str]:
        first = yield from config.string("A")
        second = yield from config.string("B")
        return first + second

    assert_freed_after_run(lambda v: read.parse(_holding(v)))


def test_list_of_frees_its_element() -> None:
    assert_freed_after_run(
        lambda v: config.list_of(config.integer().map(lambda n: n if v else 0)).parse(
            cp.from_unknown([1, 2])
        )
    )


def test_schema_record_frees_its_provider() -> None:
    record = config.schema(S.Record(S.String, S.Number))
    assert_freed_after_run(lambda v: record.parse(_holding(v, cp.Record(frozenset({"a", "b"})))))


def test_schema_array_frees_its_provider() -> None:
    array = config.schema(S.Array(S.Number))
    assert_freed_after_run(lambda v: array.parse(_holding(v, cp.Array(2))))


class _Content(bytes):
    """Entry content that notes when it is freed (``bytes`` takes no weakref)."""

    freed: list[bool]

    def __del__(self) -> None:
        self.freed.append(True)


def test_encode_frees_deflated_content() -> None:
    gc.collect()
    gc.disable()
    try:
        freed: list[bool] = []
        content = _Content(bytes(range(256)) * 1024)
        content.freed = freed
        program = (
            stream.make(zip_.file("a.bin", content, method="Deflate"))
            .pipe_through_channel(zip_.encode())
            .run_drain()
            .or_die()
        )
        del content
        fx.run_blocking(program)
        del program
        assert freed, "the run still holds the content it deflated"
    finally:
        gc.enable()
