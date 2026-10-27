"""Channel transforms, failure handling and lifecycle beyond
``Channel.test.ts``.

Expected values were printed by Effect's ``Channel.ts`` under Node (see
docs/PARITY.md).
"""

from typing import Any, Never

import pyfect as fx
from pyfect import channel, schedule, testing
from pyfect.result import Err, Ok, Result
from pyfect.scope import acquire_release
from pyfect.tracer import AnySpan, ExternalSpan

# --- transforms --------------------------------------------------------------------


@testing.effect
def test_scan_writes_the_initial_state_then_each_fold():
    result = yield from channel.from_iterable([1, 2, 3]).scan(0, lambda s, a: s + a).run_collect()
    assert result == [0, 1, 3, 6]


@testing.effect
def test_map_accum_writes_what_each_step_gives_and_on_halt_last():
    accumulated = channel.from_iterable([1, 2, 3]).map_accum(
        lambda: 0, lambda s, a: (s + a, [s, a]), on_halt=lambda s: [s * 100]
    )
    assert (yield from accumulated.run_collect()) == [0, 1, 1, 2, 3, 3, 600]


@testing.effect
def test_map_accum_with_an_empty_halt_ends_as_upstream():
    def step(s: int, a: int) -> tuple[int, list[int]]:
        return s + a, []

    accumulated = channel.from_iterable([1]).map_accum(lambda: 0, step, on_halt=lambda _: [])
    assert (yield from accumulated.run_collect()) == []


@testing.effect
def test_map_accum_takes_an_effect_step():
    accumulated = channel.from_iterable([1, 2]).map_accum(
        lambda: 10, lambda s, a: fx.succeed((s + a, [s + a]))
    )
    assert (yield from accumulated.run_collect()) == [11, 13]


@testing.effect
def test_filter_effect_and_filter_array():
    evens = channel.from_iterable([1, 2, 3, 4]).filter_effect(lambda n: fx.succeed(n % 2 == 0))
    assert (yield from evens.run_collect()) == [2, 4]
    chunks = channel.from_iterable([(1, 2), (3,), (4, 5)]).filter_array(lambda n: n % 2 == 0)
    assert (yield from chunks.run_collect()) == [(2,), (4,)]


@testing.effect
def test_flatten_and_drain():
    nested = channel.from_iterable([channel.from_iterable([1]), channel.from_iterable([2, 3])])
    assert (yield from nested.flatten().run_collect()) == [1, 2, 3]
    drained = channel.from_iterable([1, 2]).concat(channel.end("D")).drain()
    assert (yield from drained.run_collect()) == []
    assert (yield from drained.run_drain()) == "D"


@testing.effect
def test_or_else_if_empty():
    result = yield from channel.empty.or_else_if_empty(lambda _: channel.succeed(9)).run_collect()
    assert result == [9]


@testing.effect
def test_combine_threads_its_state_through_both_pulls():
    combined = channel.from_iterable([1, 2, 3]).combine(
        channel.from_iterable([10, 20]),
        lambda: 0,
        lambda s, left, right: left.flat_map(lambda a: right.map(lambda b: (a + b + s, s + 1))),
    )
    assert (yield from combined.run_collect()) == [11, 23]


@testing.effect
def test_pipe_to_or_fail_hides_upstream_failures_from_handlers():
    upstream: channel.Channel[str, Never, None, str, Never, None] = channel.identity()
    caught = upstream.catch_all(lambda _: channel.succeed("caught"))
    ex = yield from channel.fail("up").pipe_to_or_fail(caught).run_collect().exit()
    assert ex == fx.exit.fail("up")


# --- failures ------------------------------------------------------------------------


@testing.effect
def test_catch_cause_releases_the_failed_channels_resources_first():
    log: list[str] = []
    resource = channel.acquire_release(
        fx.sync(lambda: log.append("acquire")), lambda _, __: fx.sync(lambda: log.append("release"))
    )
    recovered = resource.concat(channel.fail("e")).catch_cause(
        lambda _: channel.from_effect(fx.sync(lambda: list(log)))
    )
    assert (yield from recovered.run_collect()) == [None, ["acquire", "release"]]


@testing.effect
def test_catch_cause_sees_defects():
    recovered = channel.die(RuntimeError("d")).catch_cause(lambda c: channel.succeed(c.has_dies))
    assert (yield from recovered.run_collect()) == [True]


@testing.effect
def test_tap_error_runs_on_a_typed_failure():
    seen: list[str] = []
    tapped = channel.fail("x").tap_error(lambda e: fx.sync(lambda: seen.append(e)))
    assert (yield from tapped.run_drain().exit()) == fx.exit.fail("x")
    assert seen == ["x"]


@testing.effect
def test_ignore_ends_after_the_items_written():
    ignored = channel.from_iterable([1]).concat(channel.fail("x")).ignore()
    assert (yield from ignored.run_collect()) == [1]


@testing.effect
def test_retry_fails_with_the_last_error_once_the_policy_stops():
    attempts = 0

    def attempt() -> fx.Effect[int, str]:
        nonlocal attempts
        attempts += 1
        return fx.fail(f"e{attempts}")

    retried = channel.from_effect(fx.suspend(attempt)).retry(schedule.recurs(2))
    assert (yield from retried.run_collect().exit()) == fx.exit.fail("e3")


@testing.effect
def test_retry_resets_the_policy_after_a_run_writes():
    runs = 0

    def run() -> channel.Channel[int, str]:
        nonlocal runs
        runs += 1
        return (
            channel.succeed(runs).concat(channel.fail("e")) if runs < 6 else channel.succeed(runs)
        )

    retried = channel.suspend(run).retry(schedule.recurs(1))
    assert (yield from retried.run_collect()) == [1, 2, 3, 4, 5, 6]


# --- lifecycle -----------------------------------------------------------------------


@testing.effect
def test_on_first_runs_once_on_the_first_item():
    seen: list[int] = []
    tapped = channel.from_iterable([1, 2, 3]).on_first(lambda a: fx.sync(lambda: seen.append(a)))
    assert (yield from tapped.run_collect()) == [1, 2, 3]
    assert seen == [1]


@testing.effect
def test_on_end_runs_on_the_end_only():
    seen: list[str] = []
    mark = fx.sync(lambda: seen.append("end"))
    yield from channel.fail("x").on_end(mark).run_drain().exit()
    assert seen == []
    assert (yield from channel.end(5).on_end(mark).run_drain()) == 5
    assert seen == ["end"]


@testing.effect
def test_on_exit_runs_as_soon_as_the_channel_ends():
    seen: list[Any] = []

    def record(ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.sync(lambda: seen.append(ex))

    observed = channel.from_iterable([1, 2]).on_exit(record)
    result = yield from observed.concat(
        channel.from_effect(fx.sync(lambda: list(seen)))
    ).run_collect()
    assert result == [1, 2, [fx.Success(None)]]


@testing.effect
def test_on_start_runs_before_the_first_pull():
    seen: list[str] = []
    started = channel.from_effect(fx.sync(lambda: list(seen))).on_start(
        fx.sync(lambda: seen.append("start"))
    )
    assert (yield from started.run_collect()) == [["start"]]


@testing.effect
def test_repeat_steps_the_schedule_with_each_end():
    repeated = channel.from_iterable([1, 2]).repeat(schedule.recurs(2))
    assert (yield from repeated.run_collect()) == [1, 2, 1, 2, 1, 2]


@testing.effect
def test_each_repetition_sees_its_schedule_metadata():
    attempt = channel.from_effect(schedule.CurrentMetadata().map(lambda m: m.attempt))
    assert (yield from attempt.repeat(schedule.recurs(2)).run_collect()) == [0, 1, 2]


@testing.effect
def test_schedule_ends_with_its_output_when_it_stops():
    paced = channel.from_iterable([1, 2, 3, 4]).schedule(schedule.recurs(2))
    assert (yield from paced.run_collect()) == [1, 2]
    assert (yield from paced.run_drain()) == 2


# --- services -------------------------------------------------------------------------


class Greeting(fx.Tag[str]):
    pass


@testing.effect
def test_provide_service_reaches_the_build_and_every_pull():
    greeted = channel.from_effect(Greeting()).concat(channel.from_effect(Greeting()))
    provided = greeted.pipe(channel.provide_service(Greeting, "hi"))
    assert (yield from provided.run_collect()) == ["hi", "hi"]


@testing.effect
def test_provide_service_effect_runs_each_time_the_channel_runs():
    runs = 0

    def make() -> str:
        nonlocal runs
        runs += 1
        return f"run {runs}"

    provided = channel.from_effect(Greeting()).pipe(
        channel.provide_service_effect(Greeting, fx.sync(make))
    )
    assert (yield from provided.run_collect()) == ["run 1"]
    assert (yield from provided.run_collect()) == ["run 2"]


@testing.effect
def test_update_service_changes_the_service_for_the_channel():
    shouted = channel.from_effect(Greeting()).update_service(Greeting, str.upper)
    provided = shouted.pipe(channel.provide_service(Greeting, "hi"))
    assert (yield from provided.run_collect()) == ["HI"]


@testing.effect
def test_provide_builds_a_layer_per_run_and_releases_it_with_the_run():
    log: list[str] = []
    acquired = acquire_release(
        fx.sync(lambda: log.append("build") or "layered"),
        lambda _, __: fx.sync(lambda: log.append("release")),
    )
    layer = fx.layer.effect(Greeting, acquired)
    provided = channel.from_effect(Greeting()).pipe(channel.provide(layer))
    assert (yield from provided.run_collect()) == ["layered"]
    assert log == ["build", "release"]


@testing.effect
def test_scoped_closes_the_channels_scope_when_it_ends():
    log: list[str] = []
    finalizer = fx.add_finalizer(lambda _: fx.sync(lambda: log.append("closed")))
    resource = channel.from_effect(finalizer.as_(1)).pipe(channel.scoped)
    after = resource.concat(channel.from_effect(fx.sync(lambda: list(log))))
    assert (yield from after.run_collect()) == [1, ["closed"]]


@testing.effect
def test_with_span_is_the_parent_of_spans_made_inside():
    parent = channel.from_effect(fx.tracer.current_parent_span().map(_span_name))
    assert (yield from parent.with_span("outer").run_collect()) == ["outer"]


def _span_name(span: AnySpan) -> str | None:
    return None if isinstance(span, ExternalSpan) else span.name


# --- resources released per run ----------------------------------------------------


def _scoped_resource[O, E](
    name: str, log: list[str], inner: channel.Channel[O, E]
) -> channel.Channel[O, E]:
    """``inner`` run with a resource acquired in the channel's own scope."""

    def release(_: None, ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.sync(lambda: log.append(f"rel {name} {type(ex).__name__}"))

    acquire = fx.sync(lambda: log.append(f"acq {name}"))
    return channel.unwrap(acquire_release(acquire, release).as_(inner))


@testing.effect
def test_catch_cause_releases_the_failed_channel_before_the_handler_runs():
    log: list[str] = []
    failing = _scoped_resource("a", log, channel.fail("e"))
    handler = channel.from_effect(fx.sync(lambda: log.append("handler")))
    assert (yield from failing.catch_cause(lambda _: handler).run_collect()) == [None]
    assert log == ["acq a", "rel a Failure", "handler"]


@testing.effect
def test_repeat_and_retry_release_each_run_before_the_next():
    log: list[str] = []
    runs = 0

    def run() -> channel.Channel[int, str]:
        nonlocal runs
        runs += 1
        return _scoped_resource(f"r{runs}", log, channel.from_iterable([runs]))

    repeated = channel.suspend(run).repeat(schedule.recurs(1))
    assert (yield from repeated.run_collect()) == [1, 2]
    assert log == ["acq r1", "rel r1 Success", "acq r2", "rel r2 Success"]

    log.clear()
    runs = 0

    def flaky() -> channel.Channel[int, str]:
        nonlocal runs
        runs += 1
        inner = channel.fail("e") if runs == 1 else channel.from_iterable([runs])
        return _scoped_resource(f"r{runs}", log, inner)

    assert (yield from channel.suspend(flaky).retry(schedule.recurs(1)).run_collect()) == [2]
    assert log == ["acq r1", "rel r1 Failure", "acq r2", "rel r2 Success"]


@testing.effect
def test_switch_map_runs_a_replaced_channels_finalizers_when_it_is_replaced():
    log: list[str] = []

    def inner(n: int) -> channel.Channel[int]:
        return channel.from_iterable([n]).ensuring(fx.sync(lambda: log.append(f"fin {n}")))

    switched = channel.from_iterable([1, 2, 3]).switch_map(inner)
    outer = switched.ensuring(fx.sync(lambda: log.append("outer")))
    assert (yield from outer.run_collect()) == [3]
    assert log == ["fin 1", "fin 2", "fin 3", "outer"]


@testing.effect
def test_concurrent_map_effect_starts_nothing_after_a_failure():
    started: list[int] = []

    def f(n: int) -> fx.Effect[int, str]:
        if n == 1:
            return fx.never
        return fx.fail("f") if n == 2 else fx.sync(lambda: started.append(n)).as_(n)

    mapped = channel.from_iterable(range(1, 6)).map_effect(f, concurrency=4)
    assert (yield from mapped.run_collect().exit()) == fx.exit.fail("f")
    assert started == []


def test_ignore_with_log_logs_failures_but_not_defects() -> None:
    logged: list[object] = []
    capture = fx.Logger.make(lambda o: logged.append(o.cause))

    def run(source: channel.Channel[Never, str]) -> fx.Exit[list[Never], Never]:
        ignored = source.ignore(log=True).run_collect().exit()
        return testing.run_test(ignored.pipe(fx.provide(fx.logger.layer([capture]))))

    defect = RuntimeError("d")
    assert run(channel.die(defect)) == fx.exit.die(defect)
    assert logged == []
    assert run(channel.fail("x")) == fx.exit.succeed([])
    assert len(logged) == 1


@testing.effect
def test_callback_shuts_its_queue_down_when_the_channel_closes():
    queues: list[fx.Queue[int, fx.Done]] = []

    def register(queue: fx.Queue[int, fx.Done]) -> fx.Effect[bool]:
        queues.append(queue)
        return queue.offer(1)

    assert (yield from channel.callback(register).run_head()) == fx.Some(1)
    assert not (yield from queues[0].offer(2))


# --- filter_map and catch_filter -------------------------------------------------------


def _big_evens(n: int) -> Result[int, int]:
    return Ok(n * 10) if n >= 4 and n % 2 == 0 else Err(n)


@testing.effect
def test_filter_map_array_skips_tuples_left_empty():
    source = channel.from_iterable_array(range(1, 8), chunk_size=2)
    assert (yield from source.filter_map_array(_big_evens).run_collect()) == [(40,), (60,)]
    effectful = source.filter_map_array_effect(lambda n: fx.succeed(_big_evens(n)))
    assert (yield from effectful.run_collect()) == [(40,), (60,)]


@testing.effect
def test_filter_map_skips_many_items_without_growing_the_stack():
    kept = channel.from_iterable(range(100_000)).filter_map(
        lambda n: Ok(n) if n == 99_999 else Err(n)
    )
    assert (yield from kept.run_collect()) == [99_999]
    kept_effect = channel.from_iterable(range(100_000)).filter_map_effect(
        lambda n: fx.succeed(Ok(n) if n == 99_999 else Err(n))
    )
    assert (yield from kept_effect.run_collect()) == [99_999]


def _over_five(error: int) -> Result[int, str]:
    return Ok(error) if error > 5 else Err(f"small {error}")


@testing.effect
def test_catch_filter_fails_with_the_rest_or_hands_it_to_or_else():
    failed = channel.fail(3).catch_filter(_over_five, channel.succeed)
    assert (yield from failed.run_collect().exit()) == fx.exit.fail("small 3")
    handled = channel.fail(3).catch_filter(
        _over_five, channel.succeed, or_else=lambda rest: channel.succeed(f"else {rest}")
    )
    assert (yield from handled.run_collect()) == ["else small 3"]
