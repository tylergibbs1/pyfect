"""Behavior of the structural combinators beyond the Effect test ports in
``tests/oracle/test_effect_combinators.py``."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.exit import fail as exit_fail


def test_replicate_effect_collects_each_run() -> None:
    runs: list[int] = []
    eff = fx.sync(lambda: runs.append(len(runs)) or len(runs)).replicate_effect(3)
    assert testing.run_test(eff) == [1, 2, 3]
    assert testing.run_test(fx.succeed(1).replicate_effect(0)) == []


def test_replicate_effect_discard_and_concurrency() -> None:
    @fx.gen
    def program():
        fiber = yield from fx.sleep(1).replicate_effect(4, concurrency=2, discard=True).fork()
        yield from testing.adjust(1)
        first = fiber.poll_unsafe()
        yield from testing.adjust(1)
        return first, (yield from fiber.join())

    assert testing.run_test(program) == (None, None)


def test_all_discard_keeps_no_values_and_still_fails() -> None:
    assert testing.run_test(fx.all(fx.succeed(1), fx.succeed("a"), discard=True)) is None
    eff = fx.all(fx.succeed(1), fx.fail("boom"), discard=True).exit()
    assert testing.run_test(eff) == exit_fail("boom")


def test_all_result_mode_with_discard_runs_everything_and_never_fails() -> None:
    ran: list[int] = []
    eff = fx.all(
        fx.fail("boom"), fx.sync(lambda: ran.append(2)), mode="result", discard=True
    ).exit()
    assert testing.run_test(eff) == fx.exit.succeed(None)
    assert ran == [2]


def test_all_result_mode_lets_defects_through() -> None:
    defect = RuntimeError("defect")
    ex = testing.run_test_exit(fx.all(fx.succeed(1), fx.die(defect), mode="result"))
    assert isinstance(ex, fx.Failure)
    assert ex.cause.defects == (defect,)


def test_all_dict_reads_the_mapping_when_it_runs() -> None:
    effects: dict[str, fx.Effect[int]] = {"a": fx.succeed(1)}
    eff = fx.all_dict(effects)
    effects["b"] = fx.succeed(2)
    assert testing.run_test(eff) == {"a": 1, "b": 2}


def test_validate_fails_with_every_error_in_order() -> None:
    eff = (
        fx.validate([1, 2, 3, 4], lambda n: fx.fail(n) if n > 1 else fx.succeed(n)).flip().or_die()
    )
    assert testing.run_test(eff) == (2, 3, 4)


def test_race_all_first_needs_an_effect() -> None:
    with pytest.raises(ValueError, match="at least one"):
        fx.race_all_first()


def test_race_all_first_success_interrupts_the_rest() -> None:
    @fx.gen
    def program():
        fiber = yield from fx.race_all_first(fx.sleep(2).as_(2), fx.sleep(1).as_(1)).fork()
        yield from testing.adjust(1)
        return (yield from fiber.join())

    assert testing.run_test(program) == 1


def test_timeout_option_succeeds_with_some() -> None:
    assert testing.run_test(fx.succeed(None).timeout_option(1)) == fx.Some(None)


def test_cached_run_uses_the_context_of_the_caller_that_starts_it() -> None:
    class Name(fx.Tag[str]): ...

    @fx.gen
    def program():
        cached = yield from Name().cached()
        first = yield from cached.pipe(fx.provide_service(Name, "first"))
        second = yield from cached.pipe(fx.provide_service(Name, "second"))
        return first, second

    assert testing.run_test(program) == ("first", "first")


def test_cached_with_a_fixed_ttl_reruns_after_it_expires() -> None:
    runs = 0

    def bump() -> int:
        nonlocal runs
        runs += 1
        return runs

    @fx.gen
    def program():
        cached = yield from fx.sync(bump).cached_with_ttl(1)
        seen = [(yield from cached), (yield from cached)]
        yield from testing.adjust(1)
        seen.append((yield from cached))
        return seen

    assert testing.run_test(program) == [1, 1, 2]


def test_invalidate_drops_the_cached_exit() -> None:
    runs = 0

    def bump() -> int:
        nonlocal runs
        runs += 1
        return runs

    @fx.gen
    def program():
        cached, invalidate = yield from fx.sync(bump).cached_invalidate_with_ttl(3600)
        first = yield from cached
        yield from invalidate
        return first, (yield from cached)

    assert testing.run_test(program) == (1, 2)


def test_interruptible_mask_restore_keeps_the_region_uninterruptible() -> None:
    """Inside an uninterruptible caller, ``restore`` runs uninterruptibly."""
    interruptible: list[bool] = []

    def probe() -> fx.Effect[None]:
        return fx.current_fiber().map(lambda f: interruptible.append(f._interruptible))  # pyright: ignore[reportPrivateUsage]

    eff = fx.interruptible_mask(lambda restore: probe().and_then(restore(probe())))
    testing.run_test(eff.uninterruptible())
    testing.run_test(eff)
    assert interruptible == [True, False, True, True]


def _tracked() -> tuple[list[Any], Any]:
    seen: list[Any] = []

    @contextmanager
    def resource():
        try:
            yield "r"
        except BaseException as exc:
            seen.append(exc)
            raise
        else:
            seen.append("clean")

    return seen, resource


def test_acquire_context_exits_cleanly_on_success() -> None:
    seen, resource = _tracked()
    eff = fx.scoped(fx.acquire_context(fx.sync(resource)).map(str.upper))
    assert testing.run_test(eff) == "R"
    assert seen == ["clean"]


def test_acquire_context_passes_the_failure_to_exit() -> None:
    seen, resource = _tracked()
    error = ValueError("boom")
    eff = fx.scoped(fx.acquire_context(fx.sync(resource)).and_then(fx.fail(error)))
    assert testing.run_test_exit(eff) == exit_fail(error)
    assert seen == [error]


def test_acquire_context_sees_interruption() -> None:
    seen, resource = _tracked()

    @fx.gen
    def program():
        fiber = yield from fx.scoped(
            fx.acquire_context(fx.sync(resource)).and_then(fx.never)
        ).fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()

    testing.run_test(program)
    assert len(seen) == 1
    assert isinstance(seen[0], fx.Interrupted)


def test_acquire_context_typed_acquire_errors_skip_the_manager() -> None:
    seen, resource = _tracked()
    eff = fx.scoped(fx.acquire_context(fx.fail("no").and_then(fx.sync(resource))))
    assert testing.run_test_exit(eff) == exit_fail("no")
    assert seen == []


def test_a_run_reading_its_own_cache_does_not_keep_itself_alive() -> None:
    interrupted: list[int] = []
    holder: list[fx.Effect[int]] = []

    @fx.gen
    def program():
        source = fx.suspend(lambda: holder[0]).on_interrupt(fx.sync(lambda: interrupted.append(1)))
        cached = yield from source.cached()
        holder.append(cached)
        caller = yield from cached.fork()
        yield from fx.yield_now()
        yield from fx.yield_now()
        yield from caller.interrupt()
        return list(interrupted)

    assert testing.run_test(program) == [1]


def test_a_caller_interrupted_before_the_source_runs_does_not_strand_the_next() -> None:
    """pyfect's counterpart of Effect's "never strands a second caller when
    the owner yields before registering cleanup" (which sweeps a custom
    scheduler's yield points)."""
    computed = 0

    def compute() -> int:
        nonlocal computed
        computed += 1
        return computed

    @fx.gen
    def program():
        cached = yield from fx.sync(compute).cached()
        owner = yield from cached.fork()
        yield from owner.interrupt()
        owner_exit = yield from owner.await_exit()
        computed_before = computed
        # A stranded waiter would stall run_test (StalledError).
        waiter = yield from cached.fork()
        return owner_exit, computed_before, (yield from waiter.await_exit())

    owner_exit, computed_before, waiter_exit = testing.run_test(program)
    assert isinstance(owner_exit, fx.Failure) and owner_exit.cause.has_interrupts
    assert computed_before == 0
    assert waiter_exit == fx.Success(1)


def _one_two_three() -> Iterator[int]:
    yield from (1, 2, 3)


def test_reduce_reads_a_one_shot_iterable_once_so_every_run_sees_it() -> None:
    """Effect's ``reduce`` copies the iterable when it is called (checked
    under Node: two runs over one generator both give 6)."""
    reduced = fx.reduce(_one_two_three(), lambda: 0, lambda acc, n: fx.succeed(acc + n))
    assert testing.run_test(reduced) == 6
    assert testing.run_test(reduced) == 6


def test_find_first_reads_the_iterable_each_run() -> None:
    """Effect's ``findFirst`` iterates when it runs, so a shared generator
    continues where the last run stopped (under Node: ``Some(2)``, then
    ``Some(3)``)."""
    found = fx.find_first(_one_two_three(), lambda n: fx.succeed(n > 1))
    assert testing.run_test(found) == fx.Some(2)
    assert testing.run_test(found) == fx.Some(3)
