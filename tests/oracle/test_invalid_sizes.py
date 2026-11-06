"""What Effect does with a concurrency, a count or a capacity below the valid
range: none is an error at construction. Every expected value was printed by
Effect 4.0.6 under Node, for the same call."""

from typing import Any, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import schedule
from pyfect import schema as S
from pyfect.option import Some
from pyfect.sql.sqlite import SqliteClient, SqliteClientConfig, layer


def _run(effect: Any) -> Any:
    """``None`` when it does not finish: it waits forever."""
    done: Any = fx.run_sync(fx.scoped(effect).timeout_option(0.2))
    return None if done is None else done.value


# --------------------------------------------------------------------- concurrency


@pytest.mark.parametrize("concurrency", [0, -1])
def test_a_limit_below_one_runs_one_at_a_time(concurrency: int) -> None:
    state = {"active": 0, "most": 0}
    seen: list[int] = []

    @fx.fn
    def each(n: int):
        state["active"] += 1
        state["most"] = max(state["most"], state["active"])
        yield from fx.yield_now()
        state["active"] -= 1
        seen.append(n)
        return n

    assert _run(fx.for_each([1, 2, 3], each, concurrency=concurrency)) == [1, 2, 3]
    assert seen == [1, 2, 3]
    assert state["most"] == 1


@pytest.mark.parametrize("concurrency", [0, -1])
def test_all_and_empty_for_each_take_a_limit_below_one(concurrency: int) -> None:
    assert _run(fx.all(fx.succeed(1), fx.succeed(2), concurrency=concurrency)) == (1, 2)
    assert _run(fx.for_each([], fx.succeed, concurrency=concurrency)) == []


class _Pair(TypedDict):
    a: str
    b: str


@pytest.mark.parametrize("concurrency", [0, -1])
def test_parsing_takes_a_limit_below_one(concurrency: int) -> None:
    decode = S.decode_unknown_effect(S.Struct(_Pair))
    assert _run(decode({"a": "x", "b": "y"}, concurrency=concurrency)) == {"a": "x", "b": "y"}
    array = S.decode_unknown_effect(S.Array(S.String))
    assert _run(array(("x", "y"), concurrency=concurrency)) == ("x", "y")
    assert S.decode_unknown_sync(S.Struct(_Pair))(
        {"a": "x", "b": "y"}, concurrency=concurrency
    ) == {"a": "x", "b": "y"}


# -------------------------------------------------------------------------- counts


def _counted() -> tuple[list[int], fx.Effect[int]]:
    runs = [0]

    def run() -> int:
        runs[0] += 1
        return runs[0]

    return runs, fx.sync(run)


@pytest.mark.parametrize("n", [0, -1, -5])
def test_recurs_and_up_to_below_one_never_recur(n: int) -> None:
    for policy in (schedule.recurs(n), schedule.forever.up_to(times=n)):
        runs, effect = _counted()
        assert _run(effect.repeat(policy)) == 0
        assert runs == [1]

        runs, effect = _counted()
        failing = effect.flat_map(lambda _: fx.fail("x"))
        assert isinstance(_run(failing.retry(policy).exit()), fx.Failure)
        assert runs == [1]


@pytest.mark.parametrize("n", [0, -1, -5])
def test_repeat_and_retry_times_below_one_run_once(n: int) -> None:
    runs, effect = _counted()
    assert _run(effect.repeat(times=n)) == 1
    assert runs == [1]

    runs, effect = _counted()
    failing = effect.flat_map(lambda _: fx.fail("x"))
    assert isinstance(_run(failing.retry(times=n).exit()), fx.Failure)
    assert runs == [1]


# ---------------------------------------------------------------------- capacities


@pytest.mark.parametrize("capacity", [-1, 0])
def test_a_queue_at_or_below_zero_capacity(capacity: int) -> None:
    @fx.gen
    def bounded():
        q = yield from fx.Queue[int].bounded(capacity)
        offer = yield from q.offer(1).timeout_option(0.02)
        return offer, (yield from q.size()), q.capacity

    assert _run(bounded) == (None, 0, capacity)

    @fx.gen
    def dropping():
        q = yield from fx.Queue[int].dropping(capacity)
        offer = yield from q.offer(1).timeout_option(0.02)
        return offer, (yield from q.size())

    assert _run(dropping) == (Some(False), 0)

    @fx.gen
    def sliding():
        q = yield from fx.Queue[int].sliding(capacity)
        one = yield from q.offer(1)
        two = yield from q.offer(2)
        return (
            one,
            two,
            (yield from q.size()),
            (yield from q.offer_all([3, 4])),
            (yield from q.size()),
        )

    assert _run(sliding) == (True, True, 1, [], 0)


def test_a_queue_below_zero_capacity_is_a_rendezvous() -> None:
    @fx.gen
    def program():
        q = yield from fx.Queue[int].bounded(-1)
        taker = yield from q.take().fork()
        yield from fx.yield_now()
        yield from q.offer(5)
        return (yield from taker.join())

    assert _run(program) == 5


@pytest.mark.parametrize("capacity", [-1, 0])
@pytest.mark.parametrize("kind", ["bounded", "dropping", "sliding"])
def test_a_pubsub_at_or_below_zero_capacity_dies_when_it_runs(kind: str, capacity: int) -> None:
    effect = getattr(fx.PubSub[int], kind)(capacity)
    exit = fx.run_sync_exit(effect)
    assert isinstance(exit, fx.Failure)
    defect = exit.cause.squash()
    assert str(defect) == f"Cannot construct PubSub with capacity of {capacity}"


@pytest.mark.parametrize("permits", [-1, 0])
def test_a_semaphore_without_permits_makes_takers_wait(permits: int) -> None:
    @fx.gen
    def program():
        semaphore = yield from fx.Semaphore.make(permits)
        take = yield from semaphore.take(1).timeout_option(0.02)
        run = yield from semaphore.with_permits(fx.succeed("ran"), 1).timeout_option(0.02)
        return take, run

    assert _run(program) == (None, None)


@pytest.mark.parametrize("capacity", [-1, 0])
def test_a_tx_queue_at_or_below_zero_capacity(capacity: int) -> None:
    @fx.gen
    def program():
        bounded = yield from fx.TxQueue[int].bounded(capacity)
        waits = yield from fx.tx(bounded.offer(1)).timeout_option(0.02)
        dropping = yield from fx.TxQueue[int].dropping(capacity)
        dropped = yield from fx.tx(dropping.offer(1))
        sliding = yield from fx.TxQueue[int].sliding(capacity)
        slid = yield from fx.tx(sliding.offer(1))
        return waits, dropped, slid, (yield from fx.tx(sliding.size()))

    assert _run(program) == (None, False, True, 1)


@pytest.mark.parametrize("capacity", [-1, 0])
def test_a_tx_pubsub_at_or_below_zero_capacity(capacity: int) -> None:
    @fx.gen
    def program():
        bounded = yield from fx.TxPubSub[int].bounded(capacity)
        yield from bounded.subscribe()
        waits = yield from fx.tx(bounded.publish(1)).timeout_option(0.02)
        dropping = yield from fx.TxPubSub[int].dropping(capacity)
        yield from dropping.subscribe()
        dropped = yield from fx.tx(dropping.publish(1))
        sliding = yield from fx.TxPubSub[int].sliding(capacity)
        yield from sliding.subscribe()
        return waits, dropped, (yield from fx.tx(sliding.publish(1)))

    assert _run(program) == (None, False, True)


@pytest.mark.parametrize("capacity", [-1, 0])
def test_a_cache_at_or_below_zero_capacity_keeps_nothing(capacity: int) -> None:
    @fx.gen
    def program():
        def lookup(key: int) -> fx.Effect[int]:
            return fx.succeed(key + 1)

        cache = yield from fx.Cache.make(lookup, capacity=capacity)
        return (yield from cache.get(1)), (yield from cache.get(2)), (yield from cache.size())

    assert _run(program) == (2, 3, 0)


@pytest.mark.parametrize("size", [-1, 0])
def test_a_pool_of_no_items_makes_get_wait(size: int) -> None:
    @fx.gen
    def program():
        pool = yield from fx.Pool.make(fx.succeed(1), size=size)
        return (yield from pool.get().timeout_option(0.02))

    assert _run(program) is None


@pytest.mark.parametrize("concurrency", [-1, 0])
def test_a_pool_with_a_concurrency_below_one_still_hands_out_its_item(concurrency: int) -> None:
    @fx.gen
    def program():
        pool = yield from fx.Pool.make(fx.succeed(1), size=1, concurrency=concurrency)
        return (yield from pool.get().timeout_option(0.02))

    assert _run(program) == Some(1)


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [(-1, 1, Some(1)), (2, 1, Some(1)), (0, 0, None), (0, -1, None), (1, 1, Some(1))],
)
def test_a_ttl_pool_takes_any_bounds(minimum: int, maximum: int, expected: object) -> None:
    @fx.gen
    def program():
        pool = yield from fx.Pool.make_with_ttl(
            fx.succeed(1), min=minimum, max=maximum, time_to_live=1
        )
        return (yield from pool.get().timeout_option(0.02))

    assert _run(program) == expected


def _ttl_pool_run(
    minimum: int, maximum: int, concurrency: int, gets: int, *, scoped: bool = False
) -> Any:
    runs = [0]

    def acquire() -> int:
        runs[0] += 1
        return runs[0]

    @fx.gen
    def program():
        pool = yield from fx.Pool.make_with_ttl(
            fx.sync(acquire), min=minimum, max=maximum, concurrency=concurrency, time_to_live=3600
        )
        values: list[int] = []
        for _ in range(gets):
            lease = fx.scoped(pool.get()) if scoped else pool.get()
            values.append(cast("int", (yield from lease)))
        return [*values, runs[0]]

    return _run(program)


@pytest.mark.parametrize(
    ("bounds", "gets", "scoped", "expected"),
    [
        ((3, 1, 1), 1, False, [1, 1]),
        ((3, 1, 1), 2, False, None),
        ((3, 1, 1), 2, True, [1, 1, 1]),
        ((3, 1, 2), 2, False, [1, 1, 1]),
        ((5, 2, 1), 1, False, [1, 2]),
        ((5, 2, 1), 2, False, [1, 2, 2]),
        ((5, 2, 1), 2, True, [1, 1, 2]),
    ],
)
def test_a_pool_whose_min_passes_its_max_holds_max_items(
    bounds: tuple[int, int, int], gets: int, scoped: bool, expected: object
) -> None:
    """Effect's targetSize is ``min(max(minSize, target), maxSize)``: ``max`` wins."""
    assert _ttl_pool_run(*bounds, gets, scoped=scoped) == expected


@pytest.mark.parametrize(
    ("bounds", "gets", "expected"),
    [
        ((0, 1, 0), 1, None),
        ((0, 2, 0), 1, None),
        ((1, 2, 0), 0, [0]),
        ((1, 2, 0), 1, None),
        ((0, 2, -1), 1, None),
        ((1, 3, -1), 1, [1, 1]),
        ((1, 3, -1), 2, None),
    ],
)
def test_a_growing_pool_with_a_concurrency_below_one_waits(
    bounds: tuple[int, int, int], gets: int, expected: object
) -> None:
    """Effect divides the usage by the concurrency: 0 gives Infinity, or NaN
    with no usage, whose resize then never finishes."""
    assert _ttl_pool_run(*bounds, gets) == expected


@pytest.mark.parametrize("race", [fx.race_all, fx.race_all_first])
def test_a_race_of_nothing_never_finishes(race: Any) -> None:
    assert _run(race()) is None


def test_a_sqlite_client_takes_a_negative_prepare_cache_size() -> None:
    """Effect's is a ``Cache`` capacity, which keeps nothing below 1."""
    config = SqliteClientConfig(filename=":memory:", prepare_cache_size=-1)

    @fx.gen
    def query():
        sql = yield from SqliteClient()
        return (yield from sql.unsafe("select 1 as a"))

    assert list(_run(query.pipe(fx.provide(layer(config))))) == [{"a": 1}]
