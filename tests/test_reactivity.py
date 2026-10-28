"""Reactivity: invalidating keys reruns registered handlers and queries."""

import pyfect as fx
from pyfect import reactivity, testing


def test_invalidate_runs_handlers_for_matching_keys_only():
    service = reactivity.ReactivityService()
    calls: list[str] = []
    unregister = service.register_unsafe(["users"], lambda: calls.append("users"))
    service.register_unsafe(["posts:1"], lambda: calls.append("post 1"))

    service.invalidate_unsafe(["users"])
    service.invalidate_unsafe(["comments"])
    service.invalidate_unsafe({"posts": [1]})
    unregister()
    service.invalidate_unsafe(["users"])

    assert calls == ["users", "post 1"]


def test_record_keys_also_invalidate_the_whole_table():
    """As in Effect: ``{"posts": [2]}`` hashes ``"posts"`` too."""
    service = reactivity.ReactivityService()
    calls: list[str] = []
    service.register_unsafe({"posts": [1]}, lambda: calls.append("post 1"))

    service.invalidate_unsafe({"posts": [2]})

    assert calls == ["post 1"]


@testing.effect
def test_with_batch_invalidates_once_at_the_end():
    service = reactivity.ReactivityService()
    calls: list[str] = []
    service.register_unsafe(["users"], lambda: calls.append("users"))

    def body():
        yield from service.invalidate(["users"])
        yield from service.invalidate(["users"])
        assert calls == []

    yield from service.with_batch(fx.gen(body))
    assert calls == ["users"]


@testing.effect
def test_mutation_invalidates_after_success_only():
    service = reactivity.ReactivityService()
    calls: list[str] = []
    service.register_unsafe(["users"], lambda: calls.append("users"))

    yield from service.mutation(["users"], fx.fail("boom")).exit()
    assert calls == []
    yield from service.mutation(["users"], fx.void)
    assert calls == ["users"]


@testing.effect
def test_query_reruns_when_its_keys_are_invalidated():
    service = reactivity.ReactivityService()
    counter = [0]

    def read() -> int:
        counter[0] += 1
        return counter[0]

    results = yield from service.query(["users"], fx.sync(read))
    assert (yield from results.take()) == 1
    yield from service.invalidate(["users"])
    assert (yield from results.take()) == 2


@testing.effect
def test_a_query_invalidated_while_running_runs_once_more_after():
    service = reactivity.ReactivityService()
    runs = [0]
    gate = fx.Deferred[None]()

    def read() -> fx.Effect[int]:
        runs[0] += 1
        run = runs[0]
        return gate.wait().as_(run) if run == 1 else fx.succeed(run)

    results = yield from service.query(["users"], fx.suspend(read))
    yield from fx.yield_now()
    yield from service.invalidate(["users"])
    yield from service.invalidate(["users"])
    yield from gate.succeed(None)

    assert (yield from results.take()) == 1
    assert (yield from results.take()) == 2
    yield from fx.yield_now()
    assert runs[0] == 2
