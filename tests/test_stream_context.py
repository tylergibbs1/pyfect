"""Stream services and spans: ``provide_service``, ``provide_service_effect``,
``provide_context``, ``provide``, ``update_context`` (curried, for
``.pipe``), and the ``update_service`` / ``with_span`` methods. Each
expected value was printed by Effect v4 under Node first."""

from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import stream, testing
from pyfect.scope import acquire_release
from pyfect.tracer import AnySpan, Ended, ExternalSpan, NativeSpan


class Counter(fx.Tag[int]):
    pass


class Greeting(fx.Tag[str]):
    pass


@testing.effect
def test_provide_service_reaches_the_stream():
    provided = stream.service(Counter).map(lambda n: n + 1).pipe(stream.provide_service(Counter, 4))
    assert (yield from provided.run_collect()) == [5]


@testing.effect
def test_provide_service_effect_runs_each_time_the_stream_runs():
    acquired = 0

    def acquire() -> int:
        nonlocal acquired
        acquired += 1
        return acquired

    provided = stream.service(Counter).pipe(
        stream.provide_service_effect(Counter, fx.sync(acquire))
    )
    assert (yield from provided.run_collect()) == [1]
    assert (yield from provided.run_collect()) == [2]
    assert acquired == 2


@testing.effect
def test_provide_service_effect_fails_the_stream_when_acquiring_fails():
    provided = stream.make(1).pipe(stream.provide_service_effect(Counter, fx.fail("nope")))
    assert (yield from provided.run_collect().exit()) == fx.exit.fail("nope")


def _counter_layer(log: list[str]) -> fx.Layer[Counter]:
    acquired = acquire_release(
        fx.sync(lambda: log.append("acquire") or 7),
        lambda _, __: fx.sync(lambda: log.append("release")),
    )
    return fx.layer.effect(Counter, acquired)


def _emit(log: list[str]) -> Callable[[int], fx.Effect[int, Never, Counter]]:
    def emit(n: int) -> fx.Effect[int, Never, Counter]:
        return Counter().map(lambda c: log.append(f"emit {n}") or n + c)

    return emit


@testing.effect
def test_provide_builds_a_layer_per_run_and_releases_it_when_the_stream_ends():
    log: list[str] = []
    provided = stream.make(1, 2).map_effect(_emit(log)).pipe(stream.provide(_counter_layer(log)))
    assert (yield from provided.run_collect()) == [8, 9]
    assert log == ["acquire", "emit 1", "emit 2", "release"]


@testing.effect
def test_provide_releases_the_layer_when_the_reader_stops_early():
    log: list[str] = []
    provided = (
        stream.from_iterable([1, 2, 3], chunk_size=1)
        .map_effect(_emit(log))
        .pipe(stream.provide(_counter_layer(log)))
    )
    assert (yield from provided.take(1).run_collect()) == [8]
    assert log == ["acquire", "emit 1", "release"]


@testing.effect
def test_provide_context_gives_every_service_of_the_context():
    provided = stream.service(Counter).pipe(stream.provide_context(fx.Context.make(Counter, 3)))
    assert (yield from provided.run_collect()) == [3]


@testing.effect
def test_provide_takes_a_context_too():
    provided = stream.service(Counter).pipe(stream.provide(fx.Context.make(Counter, 3)))
    assert (yield from provided.run_collect()) == [3]


@testing.effect
def test_update_context_builds_the_stream_with_new_services():
    def from_greeting(ctx: fx.Context[Greeting]) -> fx.Context[Counter]:
        return ctx.add(Counter, len(ctx.get_unsafe(Greeting) + " x"))

    provided = (
        stream.service(Counter)
        .pipe(stream.update_context(from_greeting))
        .pipe(stream.provide_service(Greeting, "hi"))
    )
    assert (yield from provided.run_collect()) == [4]


@testing.effect
def test_update_service_changes_the_service_for_the_stream():
    updated = stream.service(Counter).update_service(Counter, lambda n: n * 10)
    assert (yield from updated.pipe(stream.provide_service(Counter, 4)).run_collect()) == [40]


def _span_name(span: AnySpan) -> str | None:
    return None if isinstance(span, ExternalSpan) else span.name


@testing.effect
def test_with_span_is_the_current_span_while_the_stream_runs():
    named = (
        stream.make(1, 2)
        .map_effect(lambda n: fx.tracer.current_span().map(lambda s: f"{n}:{_span_name(s)}"))
        .with_span("outer")
    )
    assert (yield from named.run_collect()) == ["1:outer", "2:outer"]


@testing.effect
def test_with_span_ends_the_span_with_the_streams_exit():
    seen: list[Any] = []
    record = fx.tracer.current_span().tap(lambda s: fx.sync(lambda: seen.append(s)))
    yield from stream.from_effect(record).with_span("s", attributes={"k": "v"}).run_drain()
    yield from (
        stream.from_effect(record).concat(stream.fail("bad")).with_span("f").run_drain().exit()
    )
    ok, failed = seen
    assert isinstance(ok, NativeSpan) and isinstance(failed, NativeSpan)
    assert ok.name == "s" and ok.attributes["k"] == "v"
    assert isinstance(ok.status, Ended) and isinstance(ok.status.exit, fx.Success)
    assert isinstance(failed.status, Ended) and isinstance(failed.status.exit, fx.Failure)
