"""Channel behavior beyond ``Channel.test.ts``: the run functions, pulls,
resource order and stack safety.

Expected values where Effect has no test were printed by Effect's
``Channel.ts`` under Node (see docs/PARITY.md).
"""

from collections.abc import Callable, Generator
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import channel, pull, take, testing

DEEP = 20_000


def _resource(name: str, log: list[str]) -> channel.Channel[str, Never, str]:
    """Writes ``<name>1``, ``<name>2`` and ends with ``<name>-done`` inside
    ``acquire_use_release``, logging acquire and release."""

    def acquire() -> str:
        log.append(f"acquire {name}")
        return name

    def release(n: str, ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.sync(lambda: log.append(f"release {n} {ex!r}"))

    return channel.acquire_use_release(
        fx.sync(acquire),
        lambda n: channel.from_iterable([f"{n}1", f"{n}2"]).concat(channel.end(f"{n}-done")),
        release,
    )


# --- resources -------------------------------------------------------------------


@testing.effect
def test_concat_releases_the_first_channel_before_acquiring_the_second():
    log: list[str] = []
    result = yield from _resource("a", log).concat(_resource("b", log)).run_collect()
    assert result == ["a1", "a2", "b1", "b2"]
    assert log == [
        "acquire a",
        "release a Success(value='a-done')",
        "acquire b",
        "release b Success(value='b-done')",
    ]


@testing.effect
def test_concat_with_gets_the_leftover():
    log: list[str] = []
    result = (
        yield from _resource("a", log).concat_with(lambda d: channel.end(f"got {d}")).run_drain()
    )
    assert result == "got a-done"
    assert log == ["acquire a", "release a Success(value='a-done')"]


@testing.effect
def test_run_head_stops_the_channel_and_releases_with_the_runs_exit():
    log: list[str] = []
    head = yield from _resource("a", log).run_head()
    assert head == fx.Some("a1")
    assert log == ["acquire a", "release a Success(value=Some(value='a1'))"]


@testing.effect
def test_run_last_and_run_count():
    log: list[str] = []
    assert (yield from _resource("a", log).run_last()) == fx.Some("a2")
    assert (yield from _resource("a", log).run_count()) == 2
    assert (yield from channel.empty.run_head()) is None
    assert (yield from channel.empty.run_last()) is None


@testing.effect
def test_run_for_each_while_stops_when_f_says_false():
    log: list[str] = []

    def see(item: str) -> fx.Effect[bool]:
        log.append(f"saw {item}")
        return fx.succeed(item != "a1")

    assert (yield from _resource("a", log).run_for_each_while(see)) is None
    assert log == ["acquire a", "saw a1", "release a Success(value=None)"]


@testing.effect
def test_unwrap_keeps_the_effects_resources_until_the_run_ends():
    log: list[str] = []

    def acquire() -> channel.Channel[int]:
        log.append("acq")
        return channel.from_iterable([1, 2])

    def item(n: int) -> int:
        log.append(f"item {n}")
        return n

    made = fx.acquire_release(fx.sync(acquire), lambda _, __: fx.sync(lambda: log.append("rel")))
    result = yield from channel.unwrap(made).map(item).run_collect()
    assert result == [1, 2]
    assert log == ["acq", "item 1", "item 2", "rel"]


# --- pulls -------------------------------------------------------------------------


@testing.effect
def test_to_pull_pulls_items_then_keeps_ending():
    log: list[str] = []

    @fx.gen
    def body():
        next_item = yield from _resource("a", log).to_pull()
        return (yield from fx.for_each(range(4), lambda _: next_item.exit()))

    exits = yield from fx.scoped(body)
    ended = fx.Failure(fx.cause.fail(fx.Done("a-done")))
    assert exits == [fx.Success("a1"), fx.Success("a2"), ended, ended]
    assert log == ["acquire a", "release a Success(value='a-done')"]


@testing.effect
def test_to_pull_takes_turns_between_fibers():
    next_item = yield from channel.from_iterable(range(100)).to_pull()
    items = yield from fx.for_each(range(100), lambda _: next_item, concurrency="unbounded")
    assert sorted(items) == list(range(100))


@testing.effect
def test_to_pull_takes_turns_while_a_pull_is_suspended():
    count = [0]

    @fx.gen
    def counting():
        seen = count[0]
        yield from fx.yield_now()
        count[0] = seen + 1
        return seen

    next_item = yield from channel.from_pull(fx.succeed(counting)).to_pull()
    items = yield from fx.for_each(range(10), lambda _: next_item, concurrency="unbounded")
    assert sorted(items) == list(range(10))


class _Port(fx.Tag[int]): ...


@testing.effect
def test_to_pull_keeps_the_services_it_was_built_with():
    # Effect's toPull provides the building fiber's context to the pull.
    @fx.gen
    def body():
        next_item = (
            yield from channel.from_effect(_Port()).to_pull().pipe(fx.provide_service(_Port, 7))
        )
        return (yield from next_item)

    assert (yield from fx.scoped(body)) == 7


@testing.effect
def test_concat_closes_the_first_channels_scope_before_building_the_second():
    log: list[str] = []

    def held(name: str) -> channel.Channel[str]:
        def release(_: str, ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
            return fx.sync(lambda: log.append(f"release {name} {type(ex).__name__}"))

        return channel.acquire_release(
            fx.sync(lambda: log.append(f"acquire {name}") or name), release
        )

    assert (yield from held("a").concat(held("b")).run_collect()) == ["a", "b"]
    # Effect under Node prints the same order.
    assert log == ["acquire a", "release a Success", "acquire b", "release b Success"]


@testing.effect
def test_to_pull_scoped_keeps_resources_in_the_given_scope():
    log: list[str] = []
    scope = fx.CloseableScope()
    next_item = yield from _resource("a", log).to_pull_scoped(scope)
    assert (yield from next_item) == "a1"
    assert log == ["acquire a"]
    yield from scope.close(fx.Success(None))
    assert log == ["acquire a", "release a Success(value=None)"]


def test_take_to_pull_replays_each_kind_of_take():
    assert fx.run_sync_exit(take.to_pull((1, 2))) == fx.Success((1, 2))
    assert fx.run_sync_exit(take.to_pull(fx.exit.fail("e"))) == fx.exit.fail("e")
    assert fx.run_sync_exit(take.to_pull(fx.Success("end"))) == fx.exit.fail(fx.Done("end"))


@testing.effect
def test_from_effect_take_replays_takes():
    takes: list[take.Take[int, str]] = [(1, 2), (3,), fx.Success(None)]
    source = iter(takes)
    result = yield from channel.from_effect_take(fx.sync(lambda: next(source))).run_collect()
    assert result == [(1, 2), (3,)]


@testing.effect
def test_catch_done_recovers_only_from_the_end():
    ended: fx.Effect[int, fx.Done[str]] = fx.fail(fx.Done("left"))
    assert (yield from pull.catch_done(ended, lambda left: fx.succeed(len(left)))) == 4
    failing: fx.Effect[int, ValueError | fx.Done[str]] = fx.fail(ValueError("no"))
    ex = yield from pull.catch_done(failing, lambda _: fx.succeed(0)).exit()
    assert isinstance(ex, fx.Failure) and isinstance(ex.cause.failures[0], ValueError)


@testing.effect
def test_match_effect_routes_each_outcome():
    def describe(p: fx.Effect[int, str | fx.Done[str]]) -> fx.Effect[str]:
        return pull.match_effect(
            p,
            on_success=lambda n: fx.succeed(f"item {n}"),
            on_failure=lambda c: fx.succeed(f"failed {c.failures}"),
            on_done=lambda left: fx.succeed(f"done {left}"),
        )

    assert (yield from describe(fx.succeed(1))) == "item 1"
    assert (yield from describe(fx.fail("e"))) == "failed ('e',)"
    assert (yield from describe(fx.fail(fx.Done("x")))) == "done x"


def test_pull_predicates():
    done = fx.cause.fail(fx.Done())
    assert pull.is_done_cause(done)
    assert pull.is_done_failure(done.reasons[0])
    assert not pull.is_done_cause(fx.cause.fail("e"))
    assert pull.filter_no_done(fx.cause.fail("e")) == fx.Ok(fx.cause.fail("e"))
    assert pull.filter_no_done(done) == fx.Err(done)
    assert pull.filter_done_leftover(fx.cause.fail(fx.Done(3))) == fx.Ok(3)


# --- constructors -----------------------------------------------------------------


@testing.effect
def test_a_failing_transform_fails_the_pull():
    def transform(
        _up: pull.Pull[object], _scope: fx.CloseableScope
    ) -> fx.Effect[pull.Pull[int], str]:
        return fx.fail("build failed")

    ex = yield from channel.from_transform(transform).run_collect().exit()
    assert ex == fx.exit.fail("build failed")


def _raises() -> Never:
    raise RuntimeError("boom")


_RAISING_BUILDS: list[Callable[[], channel.Channel[Any, Any, Any, Any, Any, Any, Any]]] = [
    lambda: channel.from_iterator(_raises),
    lambda: channel.from_iterator_array(_raises),
    lambda: channel.end_sync(_raises),
    lambda: channel.fail_sync(_raises),
    lambda: channel.fail_cause_sync(_raises),
    lambda: channel.suspend(_raises),
    lambda: channel.from_transform(lambda _up, _scope: _raises()),
]


@pytest.mark.parametrize("build", _RAISING_BUILDS)
@testing.effect
def test_a_build_that_raises_gives_a_pull_that_dies(
    build: Callable[[], channel.Channel[Any, Any, Any, Any, Any, Any, Any]],
):
    # Effect under Node: toPull succeeds; each pull then dies with the defect.
    @fx.gen
    def body():
        next_item = yield from build().to_pull()
        return (yield from next_item.exit()), (yield from next_item.exit())

    first, second = yield from fx.scoped(body)
    assert isinstance(first, fx.Failure) and isinstance(first.cause.find_defect(), RuntimeError)
    assert second == first


@testing.effect
def test_from_effect_variants():
    log: list[str] = []
    assert (
        yield from channel.from_effect_drain(fx.sync(lambda: log.append("ran"))).run_collect()
    ) == []
    assert log == ["ran"]
    assert (yield from channel.from_effect_done(fx.succeed(7)).run_drain()) == 7
    ex = yield from channel.from_effect(fx.fail("x")).run_collect().exit()
    assert ex == fx.exit.fail("x")


@testing.effect
def test_failures():
    boom = RuntimeError("boom")
    assert (yield from channel.fail("e").map_done(lambda x: x).run_drain().exit()) == fx.exit.fail(
        "e"
    )
    assert (yield from channel.die(boom).run_drain().exit()) == fx.exit.die(boom)
    assert (yield from channel.fail_sync(lambda: "lazy").run_drain().exit()) == fx.exit.fail("lazy")
    failed = fx.cause.fail("c")
    assert (yield from channel.fail_cause(failed).run_drain().exit()) == fx.Failure(failed)
    assert (yield from channel.fail_cause_sync(lambda: failed).run_drain().exit()) == fx.Failure(
        failed
    )


@testing.effect
def test_map_done_effect_can_fail():
    mapped = channel.end(1).map_done_effect(lambda n: fx.fail(f"bad {n}"))
    assert (yield from mapped.run_drain().exit()) == fx.exit.fail("bad 1")


@testing.effect
def test_suspend_builds_the_channel_on_each_run():
    runs = 0

    def build() -> channel.Channel[int]:
        nonlocal runs
        runs += 1
        return channel.succeed(runs)

    suspended = channel.suspend(build)
    assert (yield from suspended.run_collect()) == [1]
    assert (yield from suspended.run_collect()) == [2]


@testing.effect
def test_pipe_to_identity_passes_everything_through():
    assert (yield from channel.succeed(1).pipe_to(channel.identity()).run_collect()) == [1]
    ex = yield from channel.fail("e").pipe_to(channel.identity()).run_drain().exit()
    assert ex == fx.exit.fail("e")


@testing.effect
def test_never_can_be_interrupted():
    fiber = yield from channel.never.run_drain().fork()
    yield from fx.yield_now()
    yield from fiber.interrupt()
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


def _numbers() -> Generator[int, None, str]:
    yield 1
    yield 2
    return "returned"


@testing.effect
def test_a_generators_return_value_is_the_end_value():
    assert (yield from channel.from_iterator(_numbers).run_drain()) == "returned"
    assert (yield from channel.from_iterable(_numbers()).run_drain()) == "returned"
    assert (yield from channel.from_iterator_array(_numbers, 1).run_drain()) == "returned"
    assert (yield from channel.from_iterable_array(_numbers(), 5).run_drain()) == "returned"


def _two() -> Generator[int, None, str]:
    yield 1
    yield 2
    return "L"


@pytest.mark.parametrize(
    ("chunk_size", "after_end"),
    # Effect under Node: an exhausted generator ends later pulls with no
    # leftover, unless its last chunk was cut short by the end.
    [(2, fx.Done()), (3, fx.Done("L"))],
)
@testing.effect
def test_pulling_a_chunked_generator_after_its_end(chunk_size: int, after_end: fx.Done[Any]):
    @fx.gen
    def body():
        next_chunk = yield from channel.from_iterator_array(_two, chunk_size).to_pull()
        return (yield from fx.for_each(range(4), lambda _: next_chunk.exit()))

    exits = yield from fx.scoped(body)
    ended = fx.Failure(fx.cause.fail(fx.Done("L")))
    assert exits == [fx.Success((1, 2)), ended, *[fx.Failure(fx.cause.fail(after_end))] * 2]


@testing.effect
def test_an_iterable_is_read_again_on_each_run():
    source = channel.from_iterable_array([1, 2, 3], 2)
    assert (yield from source.run_collect()) == [(1, 2), (3,)]
    assert (yield from source.run_collect()) == [(1, 2), (3,)]


@testing.effect
def test_an_iterator_that_raises_is_a_defect():
    boom = RuntimeError("boom")

    def broken() -> Generator[int]:
        yield 1
        raise boom

    assert (yield from channel.from_iterator(broken).run_collect().exit()) == fx.exit.die(boom)


@testing.effect
def test_run_for_each_and_folds():
    seen: list[int] = []
    source = channel.from_iterable([1, 2, 3]).concat(channel.end("end"))
    assert (yield from source.run_for_each(lambda n: fx.sync(lambda: seen.append(n)))) == "end"
    assert seen == [1, 2, 3]
    assert (yield from source.run_fold(lambda: 10, lambda acc, n: acc + n)) == 16
    folded = source.run_fold_effect(lambda: "", lambda acc, n: fx.succeed(f"{acc}{n}"))
    assert (yield from folded) == "123"


# --- stack safety and speed ---------------------------------------------------------


type _Nest = Callable[[channel.Channel[int]], channel.Channel[int]]


def _nest_map(c: channel.Channel[int]) -> channel.Channel[int]:
    return c.map(lambda n: n)


def _nest_pipe_to(c: channel.Channel[int]) -> channel.Channel[int]:
    return c.pipe_to(channel.identity())


def _nest_concat(c: channel.Channel[int]) -> channel.Channel[int]:
    return c.concat(channel.empty)


@pytest.mark.parametrize("build", [_nest_map, _nest_pipe_to, _nest_concat])
def test_deeply_nested_channels_build_on_the_fibers_stack(build: _Nest):
    """Building a pull calls each nested channel's transform; they run as
    effects, so 20,000 levels never reach Python's recursion limit."""
    nested = channel.from_iterable([1, 2])
    for _ in range(DEEP):
        nested = build(nested)
    assert fx.run_sync(nested.run_collect()) == [1, 2]


def test_a_deeply_nested_map_done_ends_on_the_fibers_stack():
    nested = channel.end(0)
    for _ in range(DEEP):
        nested = nested.map_done(lambda n: n + 1)
    assert fx.run_sync(nested.run_drain()) == DEEP


def test_a_million_items_run_through_a_pull_loop():
    source = channel.from_iterable(range(1_000_000)).map(lambda n: n + 1)
    assert fx.run_sync(source.run_fold(lambda: 0, lambda acc, n: acc + n)) == 500_000_500_000
