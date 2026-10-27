"""Cache and ScopedCache behavior beyond Effect's own tests: paths of
Effect's source its tests leave unpinned, and the asyncio runtime."""

import math
from typing import Never

import pyfect as fx
from pyfect import testing


class _Service(fx.Tag[int]): ...


def _length(key: str) -> fx.Effect[int]:
    return fx.succeed(len(key))


def _service(_key: str) -> fx.Effect[int, Never, _Service]:
    return _Service()


@testing.effect
def test_a_lookup_that_interrupts_itself_later_is_not_cached():
    @fx.fn
    def lookup(_key: str):
        yield from fx.sleep(1)
        yield from fx.interrupt()
        return 1

    cache = yield from fx.Cache.make(lookup, capacity=10)
    getting = yield from cache.get("a").fork(start_immediately=True)
    assert (yield from cache.has("a"))
    yield from testing.adjust(1)
    ex = yield from getting.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert not (yield from cache.has("a"))
    assert (yield from cache.size()) == 0


@testing.effect
def test_get_option_and_get_success_count_as_a_use():
    cache = yield from fx.Cache.make(_length, capacity=3)
    for key in ("a", "bb", "ccc"):
        yield from cache.get(key)
    yield from cache.get_option("a")
    yield from cache.get_success("bb")
    yield from cache.get("dddd")
    assert (yield from cache.keys()) == ["a", "bb", "dddd"]


@testing.effect
def test_set_with_a_zero_time_to_live_drops_the_key():
    def time_to_live(ex: fx.Exit[int, Never], _key: str) -> float:
        return 0 if ex == fx.Success(0) else math.inf

    cache = yield from fx.Cache.make(_length, capacity=10, time_to_live=time_to_live)
    yield from cache.set("a", 1)
    yield from cache.set("a", 0)
    assert (yield from cache.size()) == 0


@testing.effect
def test_the_callers_services_override_the_construction_services():
    def program():
        cache = yield from fx.Cache.make(_service, capacity=10)
        return (yield from cache.get("a").pipe(fx.provide_service(_Service, 2)))

    assert (yield from fx.gen(program).pipe(fx.provide_service(_Service, 1))) == 2


async def _answer() -> int:
    return 2


@testing.effect(asyncio=True)
def test_cache_shares_an_asyncio_lookup():
    lookups = [0]

    @fx.fn
    def lookup(_key: str):
        lookups[0] += 1
        yield from fx.sleep(1)
        return (yield from fx.from_async(_answer))

    cache = yield from fx.Cache.make(lookup, capacity=10)
    both = yield from fx.all(cache.get("ab"), cache.get("ab"), concurrency=2).fork()
    yield from testing.adjust(1)
    assert (yield from both.join()) == (2, 2)
    assert lookups == [1]


@testing.effect
def test_scoped_get_closes_the_expired_entry_it_replaces():
    log: list[str] = []

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        def release(_a: None, _ex: fx.Exit[object, object]) -> fx.Effect[None]:
            return fx.sync(lambda: log.append(f"released-{key}"))

        acquire = fx.sync(lambda: log.append(f"acquired-{key}"))
        return fx.acquire_release(acquire, release).as_(key)

    @fx.fn
    def program():
        cache = yield from fx.ScopedCache.make(lookup, capacity=10, time_to_live=1)
        yield from cache.get("a")
        yield from testing.adjust(2)
        yield from cache.get("a")
        return list(log)

    assert (yield from fx.scoped(program())) == ["acquired-a", "released-a", "acquired-a"]


@testing.effect
def test_scoped_invalidate_when_is_false_once_the_cache_closed_during_the_wait():
    finish = yield from fx.Latch.make()

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        return finish.wait().as_(1)

    scope = fx.CloseableScope()
    cache = yield from fx.ScopedCache.make(lookup, capacity=10).pipe(
        fx.provide_service(fx.Scope, scope)
    )
    yield from cache.get("a").fork(start_immediately=True)
    checking = yield from cache.invalidate_when("a", lambda _: True).fork(start_immediately=True)
    yield from scope.close(fx.Success(None))
    yield from finish.open()
    assert (yield from checking.await_exit()) == fx.Success(False)


@testing.effect
def test_scoped_refresh_of_a_missing_key_is_shared_like_get():
    finish = yield from fx.Latch.make()
    lookups = [0]

    def lookup(key: str) -> fx.Effect[int, Never, fx.Scope]:
        def count() -> None:
            lookups[0] += 1

        return fx.sync(count).and_then(finish.wait()).as_(len(key))

    @fx.fn
    def program():
        cache = yield from fx.ScopedCache.make(lookup, capacity=10)
        refreshing = yield from cache.refresh("ab").fork(start_immediately=True)
        getting = yield from cache.get("ab").fork(start_immediately=True)
        yield from finish.open()
        return [(yield from refreshing.join()), (yield from getting.join())]

    assert (yield from fx.scoped(program())) == [2, 2]
    assert lookups == [1]


@testing.effect
def test_scoped_readers_of_an_expired_entry_do_not_fail_with_its_finalizer():
    lookups = [0]

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        """Every resource but the last fails to release."""
        lookups[0] += 1
        if lookups[0] == 3:
            return fx.succeed(key)
        return fx.add_finalizer(lambda _: fx.die(RuntimeError("release"))).as_(key)

    @fx.fn
    def program():
        cache = yield from fx.ScopedCache.make(lookup, capacity=10, time_to_live=1)
        yield from cache.get("a")
        yield from testing.adjust(2)
        has_a = yield from cache.has("a")
        yield from cache.get("a")
        yield from testing.adjust(2)
        return [has_a, (yield from cache.get("a"))]

    assert (yield from fx.scoped(program())) == [False, "a"]
    assert lookups == [3]


@testing.effect
def test_scoped_refresh_ending_after_the_cache_closed_is_interrupted_and_released():
    finish = yield from fx.Latch.make()
    log: list[str] = []

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        n = len(log)

        def release(_a: None, _ex: fx.Exit[object, object]) -> fx.Effect[None]:
            return fx.sync(lambda: log.append(f"released-{n}"))

        acquire = fx.sync(lambda: log.append(f"acquired-{n}"))
        wait = fx.void if n == 0 else finish.wait()
        return fx.acquire_release(acquire, release).and_then(wait).as_(key)

    scope = fx.CloseableScope()
    cache = yield from fx.ScopedCache.make(lookup, capacity=10).pipe(
        fx.provide_service(fx.Scope, scope)
    )
    yield from cache.get("a")
    refreshing = yield from cache.refresh("a").fork(start_immediately=True)
    yield from scope.close(fx.Success(None))
    yield from finish.open()
    ex = yield from refreshing.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert log == ["acquired-0", "acquired-1", "released-0", "released-1"]
