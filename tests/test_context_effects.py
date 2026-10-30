"""Reading and providing services from effects, and the layer constructors
that build from contexts and effects."""

import pytest

import pyfect as fx
from pyfect import layer, testing


class Port(fx.Tag[int]): ...


class Host(fx.Tag[str]): ...


@testing.effect
def test_context_gives_the_current_services():
    ctx = yield from fx.context(Port).pipe(fx.provide_service(Port, 80))
    assert ctx.get(Port) == 80


@testing.effect
def test_service_option_is_some_when_provided_and_none_otherwise():
    assert (yield from fx.service_option(Port).pipe(fx.provide_service(Port, 1))) == fx.Some(1)
    assert (yield from fx.service_option(Port)) is None


@testing.effect
def test_provide_context_provides_every_service_of_the_context():
    ctx = fx.Context.make(Port, 80).add(Host, "h")
    both = fx.all(Port(), Host())
    assert (yield from both.pipe(fx.provide_context(ctx))) == (80, "h")
    assert (yield from both.pipe(fx.provide(ctx))) == (80, "h")


@testing.effect
def test_update_service_applies_only_inside_the_effect():
    inside = (
        yield from Port().update_service(Port, lambda n: n + 1).pipe(fx.provide_service(Port, 1))
    )
    assert inside == 2


@testing.effect
def test_update_service_dies_when_the_update_raises():
    def boom(_: int) -> int:
        raise ValueError("boom")

    ex = yield from Port().update_service(Port, boom).pipe(fx.provide_service(Port, 1)).exit()
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.squash(), ValueError)


@testing.effect
def test_provide_service_effect_runs_the_acquire_each_time():
    runs: list[int] = []
    acquire = fx.sync(lambda: runs.append(1) or len(runs))
    program = Port().pipe(fx.provide_service_effect(Port, acquire))
    assert (yield from program) == 1
    assert (yield from program) == 2


@testing.effect
def test_provide_service_effect_fails_with_the_acquire_error():
    program = Port().pipe(fx.provide_service_effect(Port, fx.fail("no port")))
    assert (yield from program.flip()) == "no port"


@testing.effect
def test_scoped_with_closes_its_scope_however_the_effect_ends():
    log: list[str] = []

    def use(scope: fx.CloseableScope) -> fx.Effect[None, str]:
        return scope.add_finalizer(lambda _: fx.sync(lambda: log.append("closed"))).and_then(
            fx.fail("failed")
        )

    assert (yield from fx.scoped_with(use).flip()) == "failed"
    assert log == ["closed"]


def test_unsafe_get_of_a_missing_service_raises():
    with pytest.raises(fx.MissingServiceError, match="Port"):
        fx.Context.empty().get_unsafe(Port)


@testing.effect
def test_context_layers_build_every_service_of_their_context():
    ctx = fx.Context.make(Port, 80).add(Host, "h")
    both = fx.all(Port(), Host())
    assert (yield from both.pipe(fx.provide(layer.succeed_context(ctx)))) == (80, "h")
    assert (yield from both.pipe(fx.provide(layer.sync_context(lambda: ctx)))) == (80, "h")


@testing.effect
def test_unwrap_builds_the_layer_an_effect_makes():
    log: list[str] = []
    made = fx.acquire_release(
        fx.sync(lambda: log.append("made") or layer.succeed(Port, 80)),
        lambda _l, _e: fx.sync(lambda: log.append("released")),
    )
    assert (yield from Port().pipe(fx.provide(layer.unwrap(made)))) == 80
    assert log == ["made", "released"]


@testing.effect
def test_a_layer_update_service_changes_what_the_layer_sees():
    reads_port = layer.effect(Host, Port().map(str))
    updated = reads_port.update_service(Port, lambda n: n + 1)
    host = yield from Host().pipe(fx.provide(updated)).pipe(fx.provide_service(Port, 80))
    assert host == "81"


@testing.effect
def test_a_shared_layer_outlives_a_nested_provide_that_reuses_it():
    log: list[str] = []
    port = layer.effect(
        Port,
        fx.acquire_release(
            fx.sync(lambda: log.append("acquire") or 80),
            lambda _p, _e: fx.sync(lambda: log.append("release")),
        ),
    )

    @fx.gen
    def program():
        yield from Port().pipe(fx.provide(port))
        log.append("nested done")
        return (yield from Port())

    assert (yield from program.pipe(fx.provide(port))) == 80
    assert log == ["acquire", "nested done", "release"]
