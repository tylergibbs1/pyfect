"""Ports of Effect's ``Request.test.ts``.

Each test's docstring is the Effect test title. Requests are frozen
dataclasses subclassing ``fx.Request`` (Effect's ``Request.Class`` /
``TaggedClass`` / ``tagged``), dispatched by class where Effect reads
``_tag``. ``Resolver.make(runAll)`` is ``RequestResolver(run_all)``
(``run_all`` takes the entries; ``make_grouped``'s resolver also gets the
key), ``makeWith`` is the same constructor with keyword arguments, and
the combinators are methods. ``Request.complete(entry, exit)`` is
``entry.complete(exit)``. ``Effect.promise(setTimeout(0))`` is
``yield_now``, ``forkChild({ startImmediately })`` is
``fork(start_immediately=True)``, ``pollUnsafe`` is ``poll_unsafe``,
``Fiber.await`` is ``await_exit`` and ``Effect.requestUnsafe`` is
``batching.request_unsafe``. Where Effect polls a fiber after one
``yieldNow``, the ports yield a few times (``_settle``): pyfect resumes
fibers through the scheduler, Effect synchronously.

Adapted, with the reason:

- "batchN normalizes the maximum batch size": counts are ``int``; the
  NaN and fractional sizes are left out (pyright rejects them).
- "requests with dual syntax are executed correctly": Python has no dual
  call forms; the body (the same as Effect's) runs as is.
- "compares StructuralProto values when hashes collide": ``hash(-1) ==
  hash(-2)`` in CPython gives two requests with equal hashes.
- "persisted stores synchronous resolver failures": the resolver raises
  ``RuntimeError("backend defect")`` (a defect must be an exception), and
  the stored defect comes back as the same
  message, so the two exits are compared by their defect's text.

Omitted, with the reason:

- "preserves __proto__ as an own constructor property", "copies
  enumerable symbol properties in Class": JavaScript object model.
"""
# pyright: reportPrivateUsage=false

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import pytest

import pyfect as fx
from pyfect import batching, exit, testing
from pyfect import schema as S
from pyfect.batching import Entry
from pyfect.duration import Input as DurationInput
from pyfect.persistence import PersistenceError, persistable, persistence

# --- fixtures (Effect's module-level helpers) -----------------------------------


@dataclass
class _Count:
    count: int = 0


class Counter(fx.Tag[_Count]): ...


class Requests(fx.Tag[_Count]): ...


@dataclass
class _Interrupts:
    interrupts: int = 0


class Interrupts(fx.Reference[_Interrupts]):
    @classmethod
    def default(cls) -> _Interrupts:
        return _Interrupts()


@dataclass
class _Value:
    value: str


class RequestService(fx.Reference[_Value]):
    @classmethod
    def default(cls) -> _Value:
        return _Value("default")


USER_IDS = list(range(1, 27))
USER_NAMES = {i: chr(96 + i) for i in USER_IDS}


@dataclass(frozen=True)
class GetAllIds(fx.Request[list[int]]):
    pass


@dataclass(frozen=True)
class GetNameById(fx.Request[str, str]):
    id: int


@dataclass(frozen=True)
class GetRequestService(fx.Request[str]):
    pass


type UserRequest = GetAllIds | GetNameById


@fx.gen
def _settle():
    """Where Effect polls a fiber after one yield: pyfect resumes a fiber
    through the scheduler, a few tasks later than Effect's synchronous
    resume."""
    for _ in range(5):
        yield from fx.yield_now()


def _delay[A, E, R](eff: fx.Effect[A, E, R]) -> fx.Effect[A, E, R]:
    return fx.yield_now().and_then(eff)


def _process_request(entry: Entry[UserRequest]) -> fx.Effect[None]:
    match entry.request:
        case GetAllIds():
            return entry.complete(fx.Success(USER_IDS))
        case GetNameById(id=user_id):
            if user_id in USER_NAMES:
                return entry.complete(fx.Success(USER_NAMES[user_id]))
            return entry.complete_effect(fx.from_exit(exit.fail("Not Found")))


@dataclass
class _UserResolver:
    get_names: fx.Effect[list[str], str]
    get_ids: fx.Effect[list[int]]
    get_name_by_id: Callable[[int], fx.Effect[str, str]]


@fx.gen
def make_user_resolver():
    counter = yield from Counter()
    requests = yield from Requests()

    @fx.fn
    def run_all(entries: Sequence[Entry[UserRequest]]):
        counter.count += 1
        requests.count += len(entries)
        for entry in entries:
            yield from _delay(_process_request(entry))

    resolver = fx.RequestResolver[UserRequest](run_all).batch_n(15)
    get_ids = fx.request(GetAllIds(), resolver)

    def get_name_by_id(user_id: int) -> fx.Effect[str, str]:
        return fx.request(GetNameById(user_id), resolver)

    def bump(i: _Interrupts) -> fx.Effect[None]:
        i.interrupts += 1
        return fx.void

    get_names = get_ids.flat_map(
        lambda ids: fx.for_each(ids, get_name_by_id, concurrency="unbounded")
    ).on_interrupt(Interrupts().flat_map(bump))
    return _UserResolver(get_names, get_ids, get_name_by_id)


@fx.gen
def make_user_resolver_tagged():
    counter = yield from Counter()
    requests = yield from Requests()

    @fx.fn
    def all_ids(reqs: Sequence[Entry[Any]]):
        counter.count += 1
        requests.count += len(reqs)
        yield from fx.void
        return [USER_IDS for _ in reqs]

    @fx.fn
    def names(reqs: Sequence[Entry[Any]]):
        counter.count += 1
        requests.count += len(reqs)
        found: list[str] = []
        for req in reqs:
            if req.request.id not in USER_NAMES:
                return (yield from fx.fail("Not Found"))
            found.append(USER_NAMES[req.request.id])
        return found

    resolver = fx.RequestResolver.from_effect_tagged(
        {GetAllIds: all_ids, GetNameById: names}
    ).batch_n(15)
    all_names = fx.request(GetAllIds(), resolver).flat_map(
        lambda ids: fx.for_each(
            ids, lambda i: fx.request(GetNameById(i), resolver), concurrency="unbounded"
        )
    )
    return all_names


def provide_env(eff: fx.Effect[None, str, Counter | Requests]) -> fx.Effect[None, str]:
    return eff.pipe(fx.provide_service_effect(Counter, fx.sync(_Count))).pipe(
        fx.provide_service_effect(Requests, fx.sync(_Count))
    )


# --- Request ----------------------------------------------------------------------


def test_compares_structural_values_when_hashes_collide():
    """compares StructuralProto values when hashes collide"""

    @dataclass(frozen=True)
    class Req(fx.Request[str]):
        id: int

    a, b = Req(-1), Req(-2)
    assert hash(a) == hash(b)
    assert a != b


@testing.effect
def test_requests_are_executed_correctly():
    """requests are executed correctly"""

    @fx.gen
    def body():
        resolver = yield from make_user_resolver
        names = yield from resolver.get_names
        counter = yield from Counter()
        requests = yield from Requests()
        assert counter.count == 3
        assert requests.count == len(USER_IDS) + 1
        assert names == [USER_NAMES[i] for i in USER_IDS]

    return provide_env(body)


@testing.effect
def test_requests_with_dual_syntax_are_executed_correctly():
    """requests with dual syntax are executed correctly"""

    @fx.gen
    def body():
        names = yield from (yield from make_user_resolver).get_names
        counter = yield from Counter()
        requests = yield from Requests()
        assert counter.count == 3
        assert requests.count == len(USER_IDS) + 1
        assert names == [USER_NAMES[i] for i in USER_IDS]

    return provide_env(body)


@testing.effect
def test_requests_are_executed_correctly_with_from_effect_tagged():
    """requests are executed correctly with fromEffectTagged"""

    @fx.gen
    def body():
        all_names = yield from make_user_resolver_tagged
        names = yield from all_names
        count = yield from Counter()
        assert count.count == 3
        assert len(names) > 2
        assert names == [USER_NAMES[i] for i in USER_IDS]

    return provide_env(body)


@testing.effect
def test_from_effect_tagged_preserves_typed_errors():
    """fromEffectTagged preserves typed errors"""
    resolver = fx.RequestResolver.from_effect_tagged({GetNameById: lambda _: fx.fail("missing")})
    error = yield from fx.request(GetNameById(1), resolver).flip()
    assert error == "missing"


@testing.effect
def test_from_effect_tagged_preserves_defects():
    """fromEffectTagged preserves defects"""
    defect = RuntimeError("boom")
    resolver = fx.RequestResolver.from_effect_tagged({GetNameById: lambda _: fx.die(defect)})
    ex = yield from fx.request(GetNameById(1), resolver).exit()
    assert isinstance(ex, fx.Failure)
    assert len(ex.cause.reasons) == 1
    assert ex.cause.defects == (defect,)


@testing.effect
def test_from_effect_tagged_preserves_interrupts():
    """fromEffectTagged preserves interrupts"""
    resolver = fx.RequestResolver.from_effect_tagged({GetNameById: lambda _: fx.interrupt()})
    ex = yield from fx.request(GetNameById(1), resolver).exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts


def _as_array(values: list[str]) -> Iterable[str]:
    return values


def _as_iterator(values: list[str]) -> Iterable[str]:
    return iter(values)


def _as_generator(values: list[str]) -> Iterable[str]:
    def gen() -> Iterator[str]:
        yield from values

    return gen()


@pytest.mark.parametrize(
    "make",
    [_as_array, _as_iterator, _as_generator],
    ids=["array", "array iterator", "generator"],
)
@testing.effect
def test_from_effect_tagged_resolves_requests_from_results(make: Callable[[list[str]], Any]):
    """fromEffectTagged resolves requests from $name results"""
    resolver = fx.RequestResolver.from_effect_tagged(
        {GetNameById: lambda entries: fx.succeed(make([str(e.request.id) for e in entries]))}
    )
    names = yield from fx.for_each(
        [1, 2, 3], lambda i: fx.request(GetNameById(i), resolver), concurrency="unbounded"
    )
    assert names == ["1", "2", "3"]


@testing.effect
def test_requests_dont_break_interruption():
    """requests don't break interruption"""

    @fx.gen
    def body():
        resolver = yield from make_user_resolver
        fiber = yield from resolver.get_names.fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        ex = yield from fiber.await_exit()
        assert isinstance(ex, fx.Failure)
        assert ex.cause.has_interrupts_only
        assert (yield from Counter()) == _Count(0)
        assert (yield from Interrupts()) == _Interrupts(1)

    return provide_env(body).pipe(fx.provide_service(Interrupts, _Interrupts(0)))


@testing.effect
def test_requests_work_with_uninterruptible():
    """requests work with uninterruptible"""

    @fx.gen
    def body():
        resolver = yield from make_user_resolver
        fiber = yield from resolver.get_names.uninterruptible().fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        ex = yield from fiber.await_exit()
        assert isinstance(ex, fx.Failure)
        assert ex.cause.has_interrupts_only
        assert (yield from Counter()) == _Count(3)
        assert (yield from Interrupts()) == _Interrupts(0)

    return provide_env(body).pipe(fx.provide_service(Interrupts, _Interrupts(0)))


@testing.effect
def test_grouped_requests_can_be_interrupted_before_execution():
    """grouped requests can be interrupted before execution"""
    executed = [False]

    def run_all(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
        def go() -> None:
            executed[0] = True
            for entry in entries:
                entry.complete_unsafe(fx.Success(USER_NAMES[entry.request.id]))

        return fx.sync(go)

    resolver = (
        fx.RequestResolver(run_all)
        .grouped(lambda entry: entry.request.id)
        .set_delay_effect(fx.never)
    )
    fiber = yield from fx.request(GetNameById(USER_IDS[0]), resolver).fork()
    yield from fx.yield_now()
    yield from fiber.interrupt()
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts_only
    assert not executed[0]


def _alice(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
    def go() -> None:
        for entry in entries:
            entry.complete_unsafe(fx.Success("Alice"))

    return fx.sync(go)


@pytest.mark.parametrize("cached", [False, True], ids=["uncached", "cached"])
@testing.effect
def test_cancelling_a_pending_batch_does_not_poison_requests(cached: bool):
    """repro: cancelling a pending batch does not poison ${cached} requests"""
    gate = yield from fx.Deferred[None].make()
    base = fx.RequestResolver(_alice).set_delay_effect(gate.wait())
    resolver = (yield from base.with_cache(capacity=10)) if cached else base
    request = GetNameById(1)

    first = yield from fx.request(request, resolver).fork(start_immediately=True)
    yield from first.interrupt()
    nxt = yield from fx.request(request, resolver).fork(start_immediately=True)

    # Allow execution only after cancelling the first batch and retrying.
    yield from gate.succeed(None)
    yield from _settle
    ex = nxt.poll_unsafe()
    yield from nxt.interrupt()
    assert ex == fx.Success("Alice")


def _recording(
    batches: list[list[int]],
) -> Callable[[Sequence[Entry[GetNameById]]], fx.Effect[None]]:
    def run_all(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
        def go() -> None:
            batches.append([e.request.id for e in entries])
            for entry in entries:
                entry.complete_unsafe(fx.Success(str(entry.request.id)))

        return fx.sync(go)

    return run_all


@testing.effect
def test_with_cache_removes_cancelled_entries_from_a_surviving_batch():
    """withCache removes cancelled entries from a surviving batch"""
    gate = yield from fx.Deferred[None].make()
    batches: list[list[int]] = []
    resolver = yield from (
        fx.RequestResolver(_recording(batches))
        .set_delay_effect(fx.yield_now().and_then(gate.wait()))
        .with_cache(capacity=10)
    )
    first = yield from fx.request(GetNameById(1), resolver).fork(start_immediately=True)
    other = yield from fx.request(GetNameById(2), resolver).fork(start_immediately=True)
    yield from first.interrupt()
    yield from gate.succeed(None)
    yield from _settle
    assert other.poll_unsafe() == fx.Success("2")
    assert batches == [[2]]

    retry = yield from fx.request(GetNameById(1), resolver).fork(start_immediately=True)
    yield from _settle
    assert retry.poll_unsafe() == fx.Success("1")
    assert batches == [[2], [1]]


def _counting_alice(
    batches: list[int],
) -> Callable[[Sequence[Entry[GetNameById]]], fx.Effect[None]]:
    def run_all(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
        def go() -> None:
            batches.append(len(entries))
            for entry in entries:
                entry.complete_unsafe(fx.Success("Alice"))

        return fx.sync(go)

    return run_all


@pytest.mark.parametrize("cancel_first", [False, True], ids=["second", "first"])
@testing.effect
def test_with_cache_preserves_coalesced_requests_when_a_caller_cancels(cancel_first: bool):
    """withCache preserves coalesced requests when the ${first|second} caller cancels"""
    gate = yield from fx.Deferred[None].make()
    batches: list[int] = []
    resolver = yield from (
        fx.RequestResolver(_counting_alice(batches))
        .set_delay_effect(gate.wait())
        .with_cache(capacity=10)
    )
    first = yield from fx.request(GetNameById(1), resolver).fork(start_immediately=True)
    second = yield from fx.request(GetNameById(1), resolver).fork(start_immediately=True)
    cancelled, remaining = (first, second) if cancel_first else (second, first)
    yield from cancelled.interrupt()
    cancelled_exit = yield from cancelled.await_exit()
    assert isinstance(cancelled_exit, fx.Failure)
    assert cancelled_exit.cause.has_interrupts
    assert batches == []
    yield from gate.succeed(None)
    yield from _settle

    assert remaining.poll_unsafe() == fx.Success("Alice")
    assert (yield from fx.request(GetNameById(1), resolver)) == "Alice"
    assert batches == [1]


@testing.effect
def test_with_cache_completes_many_coalesced_requests_for_one_cache_entry():
    """withCache completes many coalesced requests for one cache entry"""
    gate = yield from fx.Deferred[None].make()
    batches: list[int] = []
    resolver = yield from (
        fx.RequestResolver(_counting_alice(batches))
        .set_delay_effect(gate.wait())
        .with_cache(capacity=1)
    )
    fibers = yield from fx.for_each(
        range(20_000),
        lambda _: fx.request(GetNameById(1), resolver).fork(start_immediately=True),
    )
    yield from gate.succeed(None)
    yield from _settle

    assert batches == [1]
    for fiber in fibers:
        assert fiber.poll_unsafe() == fx.Success("Alice")


@testing.effect
def test_with_cache_still_caches_completed_failures():
    """withCache still caches completed failures"""
    calls = [0]

    def run_all(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
        def go() -> None:
            calls[0] += 1
            for entry in entries:
                entry.complete_unsafe(exit.fail("Not Found"))

        return fx.sync(go)

    resolver = yield from fx.RequestResolver(run_all).with_cache(capacity=10)
    for _ in range(2):
        ex = yield from fx.request(GetNameById(1), resolver).exit()
        assert ex == exit.fail("Not Found")
    assert calls[0] == 1


@testing.effect
def test_with_cache_keeps_the_wrapped_resolvers_pre_check():
    """withCache keeps the wrapped resolver's preCheck"""
    prechecked = ["Alice"]
    batched: list[int] = []

    def pre_check(entry: Entry[GetNameById]) -> bool:
        if entry.request.id != 1:
            return True
        entry.complete_unsafe(fx.Success(prechecked[0]))
        return False

    def run_all(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
        def go() -> None:
            for entry in entries:
                batched.append(entry.request.id)
                entry.complete_unsafe(fx.Success("Bob"))

        return fx.sync(go)

    resolver = yield from fx.RequestResolver(
        run_all,
        batch_key=lambda _: "batch",
        delay=fx.yield_now(),
        collect_while=lambda _: True,
        pre_check=pre_check,
    ).with_cache(capacity=10)

    assert (yield from fx.request(GetNameById(1), resolver)) == "Alice"
    prechecked[0] = "Carol"
    assert (yield from fx.request(GetNameById(1), resolver)) == "Carol"
    assert (yield from fx.request(GetNameById(2), resolver)) == "Bob"
    assert (yield from fx.request(GetNameById(2), resolver)) == "Bob"
    assert batched == [2]


@testing.effect
def test_with_cache_delegates_pending_and_completed_requests_to_the_inner_cache():
    """withCache delegates pending and completed requests to the inner cache"""
    gate = yield from fx.Deferred[None].make()
    batches: list[int] = []
    inner = yield from (
        fx.RequestResolver(_counting_alice(batches))
        .set_delay_effect(gate.wait())
        .with_cache(capacity=10)
    )
    outer = yield from inner.with_cache(capacity=10)
    request = GetNameById(1)
    first = yield from fx.request(request, inner).fork(start_immediately=True)
    second = yield from fx.request(request, outer).fork(start_immediately=True)

    yield from gate.succeed(None)
    assert (yield from first.join()) == "Alice"
    assert (yield from second.join()) == "Alice"
    assert (yield from fx.request(request, outer)) == "Alice"
    assert len(batches) == 1


@testing.effect
def test_with_cache_does_not_cache_interrupted_resolver_results():
    """withCache does not cache interrupted resolver results"""
    calls = [0]

    def run_all(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
        def go() -> None:
            calls[0] += 1
            for entry in entries:
                entry.complete_unsafe(exit.interrupt() if calls[0] == 1 else fx.Success("Alice"))

        return fx.sync(go)

    resolver = yield from fx.RequestResolver(run_all).with_cache(capacity=10)
    ex = yield from fx.request(GetNameById(1), resolver).exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts
    assert (yield from fx.request(GetNameById(1), resolver)) == "Alice"
    assert calls[0] == 2


@testing.effect
def test_with_cache_cancellation_does_not_evict_a_replacement_entry():
    """withCache cancellation does not evict a replacement entry"""
    gate = yield from fx.Deferred[None].make()
    batches: list[list[int]] = []
    delays = [0]

    def delay() -> fx.Effect[None]:
        delays[0] += 1
        return gate.wait() if delays[0] == 1 else fx.yield_now()

    def run_all(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
        def go() -> None:
            batches.append([e.request.id for e in entries])
            for entry in entries:
                entry.complete_unsafe(fx.Success("Alice"))

        return fx.sync(go)

    resolver = yield from (
        fx.RequestResolver(run_all)
        .grouped(lambda entry: entry.request.id)
        .set_delay_effect(fx.suspend(delay))
        .with_cache(capacity=1)
    )
    first = yield from fx.request(GetNameById(1), resolver).fork(start_immediately=True)
    yield from fx.yield_now()
    # Completing another group evicts the first entry while its batch is still pending.
    yield from fx.request(GetNameById(2), resolver)
    yield from fx.yield_now()
    replacement = yield from fx.request(GetNameById(1), resolver).fork(start_immediately=True)
    yield from first.interrupt()
    coalesced = yield from fx.request(GetNameById(1), resolver).fork(start_immediately=True)
    yield from gate.succeed(None)
    yield from _settle

    assert replacement.poll_unsafe() == fx.Success("Alice")
    assert coalesced.poll_unsafe() == fx.Success("Alice")
    assert batches == [[2], [1]]


@testing.effect
def test_with_cache_allows_an_equal_retry_from_the_cancelled_delays_finalizer():
    """withCache allows an equal retry from the cancelled delay's finalizer"""
    gate = yield from fx.Deferred[None].make()
    context = yield from fx.context()
    results: list[fx.Exit[str, str]] = []
    batches: list[int] = []
    cancelled_callbacks = [0]
    finalizers = [0]
    holder: list[fx.RequestResolver[GetNameById]] = []

    def retry() -> None:
        finalizers[0] += 1
        batching.request_unsafe(
            GetNameById(1), resolver=holder[0], context=context, on_exit=results.append
        )

    resolver = yield from (
        fx.RequestResolver(_counting_alice(batches))
        .set_delay_effect(gate.wait().on_interrupt(fx.sync(retry)))
        .with_cache(capacity=10)
    )
    holder.append(resolver)

    def cancelled(_ex: fx.Exit[str, str]) -> None:
        cancelled_callbacks[0] += 1

    cancel = batching.request_unsafe(
        GetNameById(1), resolver=resolver, context=context, on_exit=cancelled
    )
    cancel()
    assert finalizers[0] == 1
    assert results == []
    cancel()
    yield from gate.succeed(None)
    yield from _settle

    assert cancelled_callbacks[0] == 0
    assert finalizers[0] == 1
    assert results == [fx.Success("Alice")]
    assert batches == [1]


@testing.effect
def test_with_cache_preserves_the_race_winner_when_the_losing_resolver_is_interrupted():
    """withCache preserves the race winner when the losing resolver is interrupted"""
    finished = yield from fx.Deferred[None].make()
    calls = [0]
    interruptions = [0]

    def answer() -> str:
        calls[0] += 1
        return "Alice"

    def interrupted() -> None:
        interruptions[0] += 1

    fast = fx.RequestResolver[GetNameById].from_effect(
        lambda _: fx.yield_now().and_then(fx.sync(answer))
    )
    slow = fx.RequestResolver[GetNameById].from_effect(
        lambda _: fx.never.on_interrupt(fx.sync(interrupted))
    )
    resolver = yield from (
        fast.race(slow)
        .around(lambda _: fx.void, lambda _entries, _b: finished.succeed(None))
        .with_cache(capacity=10)
    )

    assert (yield from fx.request(GetNameById(1), resolver)) == "Alice"
    # Wait for the losing resolver's interruption before reading the cache again.
    yield from finished.wait()
    assert interruptions[0] == 1
    assert (yield from fx.request(GetNameById(1), resolver).exit()) == fx.Success("Alice")
    assert calls[0] == 1


@dataclass(frozen=True)
class GetName(persistable.Class(success=S.String)):
    def primary_key(self) -> str:
        return "name"


@testing.effect
def test_with_cache_accepts_refreshed_results_from_stale_while_revalidate():
    """withCache accepts refreshed results from stale-while-revalidate"""

    def body():
        store = yield from (yield from persistence.Persistence()).make(store_id="names")
        yield from store.set(GetName(), fx.Success("Alice"))
        finished = yield from fx.Deferred[None].make()
        calls = [0]

        def answer(_entry: Entry[GetName]) -> str:
            calls[0] += 1
            return "Bob"

        persisted = (
            yield from fx.RequestResolver[GetName]
            .from_function(answer)
            .persisted(store_id="names", stale_while_revalidate=lambda _exit, _req: True)
        )
        resolver = yield from persisted.around(
            lambda _: fx.void, lambda _entries, _b: finished.succeed(None)
        ).with_cache(capacity=10)

        assert (yield from fx.request(GetName(), resolver)) == "Alice"
        yield from finished.wait()
        assert (yield from fx.request(GetName(), resolver)) == "Bob"
        assert calls[0] == 1

    yield from fx.gen(body).pipe(fx.provide(persistence.layer_memory))


@dataclass(frozen=True)
class GetStaleValue(persistable.Class(success=S.String, error=PersistenceError)):
    def primary_key(self) -> str:
        return "value"


def _one_second(_exit: object, _req: object) -> DurationInput:
    return "1 second"


@pytest.mark.parametrize("refresh", ["per-entry failure", "whole-batch failure", "no completions"])
@testing.effect
def test_persisted_stale_while_revalidate_persists_only_refresh_results(refresh: str):
    """persisted stale-while-revalidate persists only refresh results: ${refresh}"""

    def body():
        request = GetStaleValue()
        error = PersistenceError(message="backend failed")
        options: dict[str, Any] = {"store_id": "stale-refresh", "time_to_live": _one_second}
        store = yield from (yield from persistence.Persistence()).make(**options)
        yield from store.set(request, fx.Success("Alice"))
        finished = yield from fx.Deferred[None].make()

        def run_all(entries: Sequence[Entry[GetStaleValue]]) -> fx.Effect[None, PersistenceError]:
            match refresh:
                case "whole-batch failure":
                    return fx.fail(error)
                case "per-entry failure":

                    def complete() -> None:
                        for entry in entries:
                            entry.complete_unsafe(exit.fail(error))

                    return fx.sync(complete)
                case _:
                    return fx.void

        resolver = yield from fx.RequestResolver(run_all).persisted(
            **options, stale_while_revalidate=lambda _exit, _req: True
        )
        persisted = resolver.around(lambda _: fx.void, lambda _entries, _b: finished.succeed(None))

        yield from testing.adjust("500 millis")
        assert (yield from fx.request(request, persisted)) == "Alice"
        yield from finished.wait()
        # Past the original expiry, but within the TTL of any refreshed result.
        yield from testing.adjust("600 millis")
        expected = None if refresh == "no completions" else exit.fail(error)
        assert (yield from store.get(request)) == expected

    yield from fx.gen(body).pipe(fx.provide(persistence.layer_memory))


@dataclass(frozen=True)
class GetValue(persistable.Class(success=S.String, error=PersistenceError)):
    id: int

    def primary_key(self) -> str:
        return str(self.id)


@testing.effect
def test_persisted_propagates_failures_to_unfinished_requests():
    """persisted propagates failures to unfinished requests"""

    def body():
        request = GetValue(1)
        error = PersistenceError(message="backend failed")

        def run_all(entries: Sequence[Entry[GetValue]]) -> fx.Effect[None, PersistenceError]:
            entries[0].complete_unsafe(fx.Success("first"))
            return fx.fail(error)

        persisted = yield from fx.RequestResolver(run_all).persisted(store_id="resolver-failure")
        exits = yield from fx.for_each(
            [request, request, GetValue(2)],
            lambda req: fx.request(req, persisted).exit(),
            concurrency="unbounded",
        )
        assert exits == [fx.Success("first"), exit.fail(error), exit.fail(error)]

    yield from fx.gen(body).pipe(fx.provide(persistence.layer_memory))


@dataclass(frozen=True)
class ThrowingValue(persistable.Class(success=S.String)):
    def primary_key(self) -> str:
        return "value"


@testing.effect
def test_persisted_stores_synchronous_resolver_failures():
    """persisted stores synchronous resolver failures"""

    def body():
        calls = [0]

        def run_all(_entries: Sequence[Entry[ThrowingValue]]) -> fx.Effect[None]:
            calls[0] += 1
            raise RuntimeError("backend defect")

        persisted = yield from fx.RequestResolver(run_all).persisted(store_id="resolver-throw")
        request = ThrowingValue()
        first = yield from fx.request(request, persisted).exit()
        assert isinstance(first, fx.Failure)
        assert str(first.cause.defects[0]) == "backend defect"
        second = yield from fx.request(request, persisted).exit()
        assert isinstance(second, fx.Failure)
        assert str(second.cause.defects[0]) == "backend defect"
        assert calls[0] == 1

    yield from fx.gen(body).pipe(fx.provide(persistence.layer_memory))


@testing.effect
def test_batching_preserves_individual_and_identical_requests():
    """batching preserves individual & identical requests"""

    @fx.gen
    def body():
        resolver = yield from make_user_resolver
        yield from fx.all(
            resolver.get_name_by_id(USER_IDS[0]),
            resolver.get_name_by_id(USER_IDS[0]),
            concurrency="unbounded",
        )
        requests = yield from Requests()
        invocations = yield from Counter()
        assert requests.count == 2
        assert invocations.count == 1

    return provide_env(body)


@dataclass(frozen=True)
class _Key:
    id: int


@testing.effect
def test_grouped_requests_and_batch_n():
    """grouped requests + batchN"""
    count = [0]
    requests_count = [0]

    def run_all(entries: Sequence[Entry[GetNameById]]) -> fx.Effect[None]:
        def go() -> None:
            count[0] += 1
            requests_count[0] += len(entries)
            for entry in entries:
                entry.complete_unsafe(fx.Success(USER_NAMES[entry.request.id]))

        return fx.sync(go)

    resolver = (
        fx.RequestResolver(run_all).batch_n(5).grouped(lambda entry: _Key(entry.request.id % 2))
    )
    yield from fx.for_each(
        USER_IDS, lambda i: fx.request(GetNameById(i), resolver), concurrency="unbounded"
    )
    assert count[0] == 6
    assert requests_count[0] == 26


def resolver_request(
    resolver: fx.RequestResolver[GetNameById],
) -> Callable[[GetNameById], fx.Effect[str, str]]:
    return lambda req: fx.request(req, resolver)


@testing.effect
def test_batch_n_normalizes_the_maximum_batch_size():
    """batchN normalizes the maximum batch size"""
    sizes: list[list[int]] = []
    for n in [-1, 0, 1, 2]:
        batch_sizes: list[int] = []

        def run_all(
            entries: Sequence[Entry[GetNameById]], batch_sizes: list[int] = batch_sizes
        ) -> fx.Effect[None]:
            def go() -> None:
                batch_sizes.append(len(entries))
                for entry in entries:
                    entry.complete_unsafe(fx.Success(str(entry.request.id)))

            return fx.sync(go)

        resolver = fx.RequestResolver(run_all).batch_n(n)
        yield from fx.for_each(
            [GetNameById(i) for i in [1, 2, 3]],
            resolver_request(resolver),
            concurrency="unbounded",
        )
        sizes.append(batch_sizes)
    assert sizes == [[1, 1, 1], [1, 1, 1], [1, 1, 1], [2, 1]]


@testing.effect
def test_batch_fibers_use_request_services_for_run_all():
    """batch fibers use request services for runAll"""

    @fx.fn
    def run_all(entries: Sequence[Entry[GetRequestService]]):
        value = (yield from RequestService()).value
        for entry in entries:
            entry.complete_unsafe(fx.Success(value))

    resolver = fx.RequestResolver(run_all).batch_n(1)
    value = yield from fx.request(GetRequestService(), resolver).pipe(
        fx.provide_service(RequestService, _Value("provided"))
    )
    assert value == "provided"


@testing.effect
def test_batch_fibers_use_request_services_for_delay_effects():
    """batch fibers use request services for delay effects"""
    seen = [""]

    def run_all(entries: Sequence[Entry[GetRequestService]]) -> fx.Effect[None]:
        def go() -> None:
            for entry in entries:
                entry.complete_unsafe(fx.Success("ok"))

        return fx.sync(go)

    @fx.gen
    def read_service():
        seen[0] = (yield from RequestService()).value

    resolver = fx.RequestResolver(run_all).set_delay_effect(fx.yield_now().and_then(read_service))
    yield from fx.request(GetRequestService(), resolver).pipe(
        fx.provide_service(RequestService, _Value("provided"))
    )
    assert seen[0] == "provided"


@testing.effect
def test_set_delay_0_registers_the_request_before_running_the_batch():
    """setDelay(0) registers the request before running the batch"""
    batches: list[list[int]] = []
    resolver = (
        fx.RequestResolver[GetNameById]
        .make_grouped(
            key=lambda _entry: "all",
            resolver=lambda entries, _key: _recording(batches)(entries),
        )
        .set_delay(0)
        .batch_n(2)
    )
    yield from fx.yield_now()
    assert (yield from fx.request(GetNameById(1), resolver)) == "1"
    assert batches == [[1]]
