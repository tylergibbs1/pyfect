"""Effect exports from the core-A coverage pass (docs/coverage/core-a.md)
that Effect.test.ts has no title for; Effect.ts is the spec."""

import pytest

import pyfect as fx
from pyfect.option import Some
from pyfect.result import Err, Ok, Result


class Db(fx.Tag[str]): ...


class Cache(fx.Tag[int]): ...


def test_succeed_none_and_succeed_some() -> None:
    assert fx.run_sync(fx.succeed_none) is None
    assert fx.run_sync(fx.succeed_some(1)) == Some(1)
    assert fx.run_sync(fx.succeed_some(None)) == Some(None)


def test_as_some_wraps_the_value_and_keeps_the_error() -> None:
    assert fx.run_sync(fx.succeed(1).as_some()) == Some(1)
    assert fx.run_sync_exit(fx.fail("e").as_some()) == fx.exit.fail("e")


def test_is_failure_and_is_success_read_typed_errors_only() -> None:
    assert fx.run_sync(fx.fail("e").is_failure()) is True
    assert fx.run_sync(fx.succeed(1).is_failure()) is False
    assert fx.run_sync(fx.fail("e").is_success()) is False
    assert fx.run_sync(fx.succeed(1).is_success()) is True
    boom = RuntimeError("boom")
    assert fx.run_sync_exit(fx.die(boom).is_failure()) == fx.exit.die(boom)


def test_with_fiber_and_with_fiber_succeed_see_the_running_fiber() -> None:
    def program() -> fx.Effect[tuple[int, int, int]]:
        return fx.all(
            fx.with_fiber(lambda fiber: fx.succeed(fiber.id)),
            fx.with_fiber_succeed(lambda fiber: fiber.id),
            fx.fiber_id(),
        )

    a, b, c = fx.run_sync(program())
    assert a == b == c


def test_with_fiber_succeed_turns_a_raise_into_a_defect() -> None:
    boom = RuntimeError("boom")

    def explode(_: object) -> int:
        raise boom

    assert fx.run_sync_exit(fx.with_fiber_succeed(explode)) == fx.exit.die(boom)


def even(n: int) -> Result[int, int]:
    return Ok(n) if n % 2 == 0 else Err(n)


def test_filter_map_or_else_continues_with_what_the_filter_rejects() -> None:
    def run(n: int) -> int | str:
        return fx.run_sync(fx.succeed(n).filter_map_or_else(even, lambda x: fx.succeed(f"odd {x}")))

    assert run(2) == 2
    assert run(3) == "odd 3"


def test_filter_map_or_fail_fails_with_what_the_filter_rejects() -> None:
    assert fx.run_sync_exit(fx.succeed(2).filter_map_or_fail(even, lambda x: f"odd {x}")) == (
        fx.exit.succeed(2)
    )
    assert fx.run_sync_exit(fx.succeed(3).filter_map_or_fail(even, lambda x: f"odd {x}")) == (
        fx.exit.fail("odd 3")
    )
    with pytest.raises(fx.NoSuchElementException):
        fx.run_sync(fx.succeed(3).filter_map_or_fail(even).catch_all(fx.die))


def test_update_context_changes_the_services_for_the_effect_only() -> None:
    def with_cache_two(ctx: fx.Context[Db | Cache]) -> fx.Context[Db | Cache]:
        return ctx.add(Cache, 2)

    program = fx.all(Db(), Cache()).pipe(fx.update_context(with_cache_two))
    outer = program.pipe(fx.provide_service(Db, "db")).pipe(fx.provide_service(Cache, 1))
    assert fx.run_sync(fx.all(outer, Cache().pipe(fx.provide_service(Cache, 1)))) == (("db", 2), 1)


def test_set_context_replaces_every_service() -> None:
    ctx = fx.Context.make(Db, "replaced")
    program = Db().pipe(fx.set_context(ctx))
    assert fx.run_sync(program.pipe(fx.provide_service(Db, "outer"))) == "replaced"
    # The services the context lacks are gone inside the effect.
    missing = fx.service_option(Cache).pipe(fx.set_context(ctx))
    assert fx.run_sync(missing.pipe(fx.provide_service(Cache, 1))) is None
