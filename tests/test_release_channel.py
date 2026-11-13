"""Channel operators and the decoders built on channels let go of what they
handled once the run ends, without the cycle collector (see
``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from typing import Any

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect import channel, schedule, stream
from pyfect import schema as S
from pyfect.encoding import schema_binary, sse, tar
from pyfect.result import Err


def _source(value: Handled) -> channel.Channel[Handled]:
    return channel.from_iterable([value, Handled()])


def test_filter_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).filter(lambda item: item is not v).run_drain())


def test_filter_effect_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: _source(v).filter_effect(lambda item: fx.succeed(item is not v)).run_drain()
    )


def test_stream_filter_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: stream.make(v, Handled()).filter(lambda _: False).run_drain())


def test_stream_filter_effect_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: stream.make(v).filter_effect(lambda _: fx.succeed(False)).run_drain()
    )


def test_filter_map_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: _source(v).filter_map(lambda item: Err(item is v)).run_drain())


def test_filter_map_effect_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: _source(v).filter_map_effect(lambda item: fx.succeed(Err(item is v))).run_drain()
    )


def test_filter_map_array_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: (
            channel.from_iterable([(v,), (Handled(),)])
            .filter_map_array(lambda item: Err(item is v))
            .run_drain()
        )
    )


def test_filter_map_array_effect_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: (
            channel.from_iterable([(v,), (Handled(),)])
            .filter_map_array_effect(lambda item: fx.succeed(Err(item is v)))
            .run_drain()
        )
    )


def test_map_accum_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: _source(v).map_accum(lambda: v, lambda s, a: (s, (a, a))).run_drain()
    )


def test_flatten_array_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: channel.from_iterable([(v, Handled())]).flatten_array().run_drain()
    )


def test_switch_map_frees_its_workers() -> None:
    assert_freed_after_run(lambda v: stream.make(v, Handled()).switch_map(stream.make).run_drain())


def test_repeat_frees_its_runs() -> None:
    assert_freed_after_run(lambda v: _source(v).repeat(schedule.recurs(1)).run_drain())


def test_repeat_taken_early_frees_its_runs() -> None:
    assert_freed_after_run(
        lambda v: stream.make(v, Handled()).repeat(schedule.forever).take(1).run_drain()
    )


def test_sse_decode_frees_its_input() -> None:
    def build(value: Handled) -> fx.Effect[Any, Any, Any]:
        text = stream.make(value).map(lambda _: "data: a\n\n")
        return text.pipe_through_channel(sse.decode()).run_drain()

    assert_freed_after_run(build)


def test_tar_decode_frees_its_input() -> None:
    encoding = stream.make(tar.file("a", b"body")).pipe_through_channel(tar.encode())
    encoded = fx.run_blocking(encoding.run_bytes().or_die())

    def build(value: Handled) -> fx.Effect[Any, Any, Any]:
        source = stream.make(value).map(lambda _: encoded)
        entries = source.pipe_through_channel(tar.decode())
        return entries.map_effect(lambda entry: entry.body.run_drain()).run_drain()

    assert_freed_after_run(build)


def test_schema_binary_decode_frees_its_values() -> None:
    schema = S.NumberFromString
    encoding = stream.make(1.0, 2.0).pipe_through_channel(schema_binary.encode(schema))
    frames = fx.run_blocking(encoding.run_collect().or_die())

    def build(value: Handled) -> fx.Effect[Any, Any, Any]:
        source = stream.make(value).map(lambda _: frames[0])
        return source.pipe_through_channel(schema_binary.decode(schema)).run_drain()

    assert_freed_after_run(build)
