"""Ports of Effect's ``Layer.test.ts``.

Each test's docstring is the Effect test title. ``Layer.build`` is the
``build()`` method, ``Layer.buildWithMemoMap`` is ``build_with_memo_map``,
``Scope.make()`` is ``CloseableScope()``, ``forkChild`` is ``fork`` and
``forkDetach`` is ``fork_daemon``. ``Layer.provide([a, b])`` is
``provide(merge(a, b))``.

Effect types a recovered layer as building ``ROut & ROut2``, which pyright
can't spell: the ``catch`` ports widen a layer to build nothing.

Omitted, with the reason:

- "allows passing partial service in dual form": Python has one form,
  ``mock(tag, **members)``.
- The ``Stream`` / ``Channel`` halves of the mock tests: no Stream yet (M6).
- "withSpan forwards captureStackTrace to the layer stack frame",
  "withSpan supports data-first usage and runs the onEnd finalizer",
  "withParentSpan supports data-last usage with external spans": no tracer
  yet (M5).
"""
# pyright: reportPrivateUsage=false

from typing import Never

import pyfect as fx
from pyfect import layer, schedule, testing
from pyfect.context import TagLike

ACQUIRE1, ACQUIRE2, ACQUIRE3 = "Acquiring Module 1", "Acquiring Module 2", "Acquiring Module 3"
RELEASE1, RELEASE2, RELEASE3 = "Releasing Module 1", "Releasing Module 2", "Releasing Module 3"


class Service1:
    def one(self) -> fx.Effect[int]:
        return fx.succeed(1)


class Service2:
    def two(self) -> fx.Effect[int]:
        return fx.succeed(2)


class Service3:
    def three(self) -> fx.Effect[int]:
        return fx.succeed(3)


class Service1Tag(fx.Tag[Service1], key="Service1"): ...


class Service2Tag(fx.Tag[Service2], key="Service2"): ...


class Service3Tag(fx.Tag[Service3], key="Service3"): ...


def _make[S, T](tag: TagLike[S, T], make: type[S], n: int, log: list[str]) -> layer.Layer[T]:
    def acquire() -> S:
        log.append(f"Acquiring Module {n}")
        return make()

    return layer.effect(
        tag,
        fx.acquire_release(
            fx.sync(acquire), lambda _s, _e: fx.sync(lambda: log.append(f"Releasing Module {n}"))
        ),
    )


def make_layer1(log: list[str]) -> layer.Layer[Service1Tag]:
    return _make(Service1Tag, Service1, 1, log)


def make_layer2(log: list[str]) -> layer.Layer[Service2Tag]:
    return _make(Service2Tag, Service2, 2, log)


def make_layer3(log: list[str]) -> layer.Layer[Service3Tag]:
    return _make(Service3Tag, Service3, 3, log)


def _builds_nothing[E](built: layer.Layer[Never, E]) -> layer.Layer[Never, E]:
    """Widens a layer's services to none: Effect types a recovered layer as
    building both layers' services' intersection, which pyright can't spell."""
    return built


def _released_once_each(log: list[str], *pairs: tuple[str, str]) -> None:
    for acquire, release in pairs:
        if acquire in log:
            assert release in log


@testing.effect
def test_layers_can_be_acquired_in_parallel():
    """layers can be acquired in parallel"""

    class BoolTag(fx.Tag[bool], key="boolean"): ...

    latch = fx.Latch()
    layer1: layer.Layer[Never] = layer.effect_context(fx.never)
    layer2 = layer.effect_context(
        fx.acquire_release(
            latch.open().map(lambda b: fx.Context.make(BoolTag, b)), lambda _c, _e: fx.void
        )
    )
    env = layer.merge(layer1, layer2).build()
    fiber = yield from fx.scoped(env).fork_daemon()
    yield from latch.wait()
    result = yield from fiber.interrupt()
    assert result is None


@testing.effect
def test_sharing_with_merge():
    """sharing with merge"""
    log: list[str] = []
    l1 = make_layer1(log)
    yield from fx.scoped(layer.merge(l1, l1).build())
    assert log == [ACQUIRE1, RELEASE1]


@testing.effect
def test_preserves_a_failure_when_a_shared_layer_build_is_interrupted():
    """preserves a failure when a shared layer build is interrupted"""

    class Shared(fx.Tag[int], key="Shared"): ...

    class Dying(fx.Tag[int], key="Dying"): ...

    class Runtime(fx.Tag[bool], key="Runtime"): ...

    for kind in ("die", "fail"):
        shared_started = fx.Latch()
        outer_started = fx.Latch()
        shared = layer.effect(Shared, shared_started.open().and_then(fx.never))
        failure: fx.Effect[Never, str] = (
            fx.die(RuntimeError("layer defect")) if kind == "die" else fx.fail("layer failure")
        )
        dying = layer.effect(
            Dying,
            fx.all(shared_started.wait(), outer_started.wait())
            .and_then(fx.yield_now())
            .and_then(failure),
        )
        runtime = layer.effect(Runtime, fx.all(Shared(), Dying()).as_(True)).pipe(
            fx.provide(layer.merge(shared, dying))
        )
        outer_shared = layer.from_build(
            lambda memo, scope, shared=shared, ss=shared_started, os=outer_started: (
                ss.wait().and_then(os.open()).and_then(shared.build_with_memo_map(memo, scope))
            )
        )
        ex = yield from fx.scoped(layer.merge(runtime, outer_shared).build()).exit()
        assert isinstance(ex, fx.Failure)
        assert ex.cause.has_dies if kind == "die" else ex.cause.has_fails


@testing.effect
def test_sharing_itself_with_merge():
    """sharing itself with merge"""
    service1 = Service1()
    l1 = layer.succeed(Service1Tag, service1)
    env = layer.merge(l1, l1, l1).build()
    result = yield from env.map(lambda ctx: ctx.get(Service1Tag))
    assert result is service1


@testing.effect
def test_suspend_is_lazy():
    """suspend is lazy"""
    evaluated = 0

    def make() -> layer.Layer[Service1Tag]:
        nonlocal evaluated
        evaluated += 1
        return layer.succeed(Service1Tag, Service1())

    l1 = layer.suspend(make)
    assert evaluated == 0
    yield from fx.scoped(l1.build())
    assert evaluated == 1
    yield from fx.scoped(l1.build())
    assert evaluated == 2


@testing.effect
def test_suspend_preserves_sharing():
    """suspend preserves sharing"""
    log: list[str] = []
    evaluated = 0

    def make() -> layer.Layer[Service1Tag]:
        nonlocal evaluated
        evaluated += 1
        return make_layer1(log)

    l1 = layer.suspend(make)
    yield from fx.scoped(layer.merge(l1, l1).build())
    assert evaluated == 1
    assert log == [ACQUIRE1, RELEASE1]


@testing.effect
def test_finalizers():
    """finalizers"""
    log: list[str] = []
    yield from fx.scoped(layer.merge(make_layer1(log), make_layer2(log)).build())
    assert set(log[:2]) == {ACQUIRE1, ACQUIRE2}
    assert set(log[2:4]) == {RELEASE1, RELEASE2}


@testing.effect
def test_catch_uses_an_alternative_layer():
    """catch - uses an alternative layer"""
    log: list[str] = []
    failing = _builds_nothing(
        layer.effect_discard(fx.fail("failed!")).pipe(layer.provide_merge(make_layer1(log)))
    )
    yield from fx.scoped(failing.catch_all(lambda _: make_layer2(log)).build())
    assert log == [ACQUIRE1, RELEASE1, ACQUIRE2, RELEASE2]


@testing.effect
def test_catch_tag_uses_an_alternative_layer():
    """catchTag - uses an alternative layer"""

    class LayerError(fx.TaggedError): ...

    log: list[str] = []
    failing = layer.effect_discard(fx.fail(LayerError())).pipe(
        layer.provide_merge(make_layer1(log))
    )
    fallback = _builds_nothing(make_layer2(log))
    yield from fx.scoped(failing.pipe(layer.catch_tag(LayerError, lambda _: fallback)).build())
    assert log == [ACQUIRE1, RELEASE1, ACQUIRE2, RELEASE2]


@testing.effect
def test_catch_cause_recovers_with_a_fallback_layer_and_exposes_the_original_cause():
    """catchCause recovers with a fallback layer and exposes the original cause"""
    causes: list[fx.Cause[str]] = []

    def recover(cause: fx.Cause[str]) -> layer.Layer[Service1Tag]:
        causes.append(cause)
        return layer.succeed(Service1Tag, Service1())

    failing = layer.effect(Service1Tag, fx.fail("failed!"))
    ctx = yield from fx.scoped(failing.catch_cause(recover).build())
    assert (yield from ctx.get(Service1Tag).one()) == 1
    assert len(causes) == 1
    assert causes[0].has_fails


@testing.effect
def test_tap_executes_effect_with_success_services_and_preserves_output():
    """tap - executes effect with success services and preserves output"""
    log: list[str] = []
    env = (
        make_layer1(log)
        .tap(lambda ctx: fx.sync(lambda: log.append(f"tap:{type(ctx.get(Service1Tag)).__name__}")))
        .build()
    )
    ctx = yield from fx.scoped(env)
    assert (yield from ctx.get(Service1Tag).one()) == 1
    assert log == [ACQUIRE1, "tap:Service1", RELEASE1]


@testing.effect
def test_tap_error_executes_effect_and_preserves_original_error():
    """tapError - executes effect and preserves original error"""
    log: list[str] = []
    env = (
        layer.effect_discard(fx.fail("failed!"))
        .tap_error(lambda e: fx.sync(lambda: log.append(f"tapError:{e}")))
        .build()
    )
    error = yield from fx.scoped(env).flip()
    assert error == "failed!"
    assert log == ["tapError:failed!"]


@testing.effect
def test_tap_cause_executes_effect_and_preserves_original_cause():
    """tapCause - executes effect and preserves original cause"""
    log: list[str] = []
    env = (
        layer.effect_discard(fx.die(RuntimeError("boom")))
        .tap_cause(lambda c: fx.sync(lambda: log.append(f"tapCause:{c.has_dies}")))
        .build()
    )
    ex = yield from fx.scoped(env).exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_dies
    assert log == ["tapCause:True"]


@testing.effect
def test_fresh_with_merge():
    """fresh with merge"""
    log: list[str] = []
    l1 = make_layer1(log)
    yield from fx.scoped(layer.merge(l1, layer.fresh(l1)).build())
    assert log == [ACQUIRE1, ACQUIRE1, RELEASE1, RELEASE1]


@testing.effect
def test_fresh_with_provide():
    """fresh with provide"""
    log: list[str] = []
    l1 = make_layer1(log)
    yield from fx.scoped(layer.fresh(l1).pipe(fx.provide(l1)).build())
    assert log == [ACQUIRE1, ACQUIRE1, RELEASE1, RELEASE1]


@testing.effect
def test_with_multiple_layers():
    """with multiple layers"""
    log: list[str] = []
    l1 = make_layer1(log)
    env = layer.merge(layer.merge(l1, l1), layer.fresh(layer.merge(l1, l1)))
    yield from fx.scoped(env.build())
    assert log == [ACQUIRE1, ACQUIRE1, RELEASE1, RELEASE1]


@testing.effect
def test_with_identical_fresh_layers():
    """with identical fresh layers"""
    log: list[str] = []
    l1, l2, l3 = make_layer1(log), make_layer2(log), make_layer3(log)
    env = layer.merge(l2, layer.fresh(l3.pipe(fx.provide(l1)))).pipe(fx.provide(layer.fresh(l1)))
    yield from fx.scoped(env.build())
    assert log == [
        ACQUIRE1,
        ACQUIRE2,
        ACQUIRE1,
        ACQUIRE3,
        RELEASE3,
        RELEASE1,
        RELEASE2,
        RELEASE1,
    ]


@testing.effect
def test_interruption_with_merge():
    """interruption with merge"""
    log: list[str] = []
    env = layer.merge(make_layer1(log), make_layer2(log)).build()
    fiber = yield from fx.scoped(env).fork()
    yield from fiber.interrupt()
    _released_once_each(log, (ACQUIRE1, RELEASE1), (ACQUIRE2, RELEASE2))


@testing.effect
def test_interruption_with_provide():
    """interruption with provide"""
    log: list[str] = []
    env = make_layer2(log).pipe(fx.provide(make_layer1(log))).build()
    fiber = yield from fx.scoped(env).fork()
    yield from fiber.interrupt()
    _released_once_each(log, (ACQUIRE1, RELEASE1), (ACQUIRE2, RELEASE2))


@testing.effect
def test_interruption_with_multiple_layers():
    """interruption with multiple layers"""
    log: list[str] = []
    l1, l2, l3 = make_layer1(log), make_layer2(log), make_layer3(log)
    env = layer.merge(l3.pipe(fx.provide(l1)), l2).pipe(fx.provide(l1)).build()
    fiber = yield from fx.scoped(env).fork()
    yield from fiber.interrupt()
    _released_once_each(log, (ACQUIRE1, RELEASE1), (ACQUIRE2, RELEASE2), (ACQUIRE3, RELEASE3))


@testing.effect
def test_finalizers_with_provide():
    """finalizers with provide"""
    log: list[str] = []
    yield from fx.scoped(make_layer2(log).pipe(fx.provide(make_layer1(log))).build())
    assert log == [ACQUIRE1, ACQUIRE2, RELEASE2, RELEASE1]


@testing.effect
def test_finalizers_with_multiple_layers_with_provide_to():
    """finalizers with multiple layers with provideTo"""
    log: list[str] = []
    env = make_layer3(log).pipe(fx.provide(make_layer2(log))).pipe(fx.provide(make_layer1(log)))
    yield from fx.scoped(env.build())
    assert log == [ACQUIRE1, ACQUIRE2, ACQUIRE3, RELEASE3, RELEASE2, RELEASE1]


@testing.effect
def test_or_die_does_not_interfere_with_sharing():
    """orDie does not interfere with sharing"""
    log: list[str] = []
    l1, l2, l3 = make_layer1(log), make_layer2(log), make_layer3(log)
    env = l3.pipe(fx.provide(l1)).pipe(fx.provide(l2)).pipe(fx.provide(l1.or_die()))
    yield from fx.scoped(env.build())
    assert log[0] == ACQUIRE1
    assert set(log[1:3]) == {ACQUIRE2, ACQUIRE3}
    assert set(log[3:5]) == {RELEASE2, RELEASE3}
    assert log[5] == RELEASE1


@testing.effect
def test_launch_keeps_the_layer_open_until_interrupted_and_then_finalizes():
    """launch keeps the layer open until interrupted and then finalizes"""
    log: list[str] = []
    fiber = yield from make_layer1(log).launch().fork()
    yield from fx.yield_now()
    assert log == [ACQUIRE1]
    yield from fiber.interrupt()
    assert log == [ACQUIRE1, RELEASE1]


class _Mocked:
    def __init__(self, one: fx.Effect[int]) -> None:
        self.one = one

    def two(self) -> fx.Effect[int]:
        return fx.succeed(2)


class MockedTag(fx.Tag[_Mocked], key="Service1"): ...


@testing.effect
def test_allows_passing_partial_service():
    """allows passing partial service"""

    @fx.gen
    def program():
        service = yield from MockedTag()
        assert (yield from service.one) == 123
        defect = yield from service.two().catch_defect(fx.fail).flip()
        assert isinstance(defect, layer.UnimplementedError)

    yield from program.pipe(fx.provide(layer.mock(MockedTag, one=fx.succeed(123))))


@testing.effect
def test_missing_mock_members_fail_as_unimplemented_effects_and_channels():
    """missing mock members fail as unimplemented effects and channels"""

    @fx.gen
    def program():
        service = yield from MockedTag()
        defect = yield from service.two().catch_defect(fx.fail).flip()
        assert type(defect).__name__ == "UnimplementedError"
        assert str(defect) == 'Service1: Unimplemented method "two"'
        as_effect = yield from service.one.catch_defect(fx.fail).flip()
        assert isinstance(as_effect, layer.UnimplementedError)

    yield from program.pipe(fx.provide(layer.mock(MockedTag)))


# --- MemoMap ------------------------------------------------------------------------


class Resource(fx.Tag[dict[str, bool]], key="Resource"): ...


class Shared(fx.Tag[int], key="Shared"): ...


def _release_counted(released: fx.Ref[int]) -> layer.Layer[Shared]:
    return layer.effect(
        Shared, fx.acquire_release(fx.succeed(1), lambda _n, _e: released.update(lambda n: n + 1))
    )


# A small MaxOpsBeforeYield budget makes a fiber yield before each op, so
# sweeping the budget moves an interrupt through every step of a build.
_BUDGETS = range(3, 65)


@fx.gen
def _settle():
    for _ in range(200):
        yield from fx.yield_now()


@testing.effect
def test_retrying_a_build_with_memo_map_effect_keeps_the_resource_alive_until_its_scope_closes():
    """retrying a buildWithMemoMap effect keeps the resource alive until its scope closes"""
    attempts = 0

    def make() -> fx.Effect[dict[str, bool], str, fx.Scope]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return fx.fail("transient")
        return fx.acquire_release(
            fx.succeed({"live": True}), lambda r, _e: fx.sync(lambda: r.update(live=False))
        )

    resource_layer = layer.effect(Resource, fx.suspend(make))
    owner = yield from fx.acquire_release(
        fx.sync(fx.CloseableScope), lambda scope, ex: scope.close(ex)
    )
    build = resource_layer.build_with_memo_map(layer.MemoMap(), owner)
    ctx = yield from build.retry(schedule.recurs(1))
    resource = ctx.get(Resource)
    assert resource["live"]
    yield from owner.close(fx.Success(None))
    assert not resource["live"]


@testing.effect
def test_memoizes_composed_layers_by_identity():
    """memoizes composed layers by identity"""

    class Probe(fx.Tag[str], key="Probe"): ...

    class Dep(fx.Tag[int], key="Dep"): ...

    builds = 0

    def count() -> fx.Context[Probe]:
        nonlocal builds
        builds += 1
        return fx.Context.make(Probe, "x")

    probe = layer.from_build(lambda _memo, _scope: fx.sync(count))
    dep = layer.succeed(Dep, 1)

    provided = probe.pipe(fx.provide(dep))
    yield from fx.scoped(layer.merge(provided, provided).build())
    assert builds == 1

    builds = 0
    merged = layer.merge(probe, dep)
    yield from fx.scoped(layer.merge(merged, merged).build())
    assert builds == 1

    builds = 0
    yield from fx.scoped(layer.merge(provided, layer.fresh(provided)).build())
    assert builds == 2


@testing.effect
def test_interrupting_a_build_does_not_hang_current_or_later_requesters():
    """interrupting a build does not hang current or later requesters"""
    for ops in _BUDGETS:
        memo = layer.MemoMap()
        shared = layer.effect(Shared, fx.succeed(1))
        first = yield from (
            shared.build_with_memo_map(memo, fx.CloseableScope())
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
            .fork(start_immediately=True)
        )
        waiter = yield from shared.build_with_memo_map(memo, fx.CloseableScope()).fork(
            start_immediately=True
        )
        yield from first.interrupt()
        later = yield from shared.build_with_memo_map(memo, fx.CloseableScope()).fork(
            start_immediately=True
        )
        yield from _settle
        assert waiter.unsafe_poll() is not None, f"waiter hung with {ops} ops"
        assert later.unsafe_poll() is not None, f"later requester hung with {ops} ops"


@testing.effect
def test_an_interrupted_reuse_does_not_keep_the_shared_layer_alive():
    """an interrupted reuse does not keep the shared layer alive"""
    for closed in (False, True):
        for ops in _BUDGETS:
            released = yield from fx.Ref.make(0)
            memo = layer.MemoMap()
            shared = _release_counted(released)
            scope1, scope2 = fx.CloseableScope(), fx.CloseableScope()
            yield from shared.build_with_memo_map(memo, scope1)
            if closed:
                yield from scope2.close(fx.Success(None))
            reuse = yield from (
                shared.build_with_memo_map(memo, scope2)
                .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
                .fork(start_immediately=True)
            )
            yield from reuse.interrupt()
            if not closed:
                yield from scope2.close(fx.Success(None))
            yield from scope1.close(fx.Success(None))
            assert (yield from released.get()) == 1, f"closed scope: {closed}, {ops} ops"


@testing.effect
def test_running_a_get_effect_twice_does_not_release_the_shared_layer_early():
    """running a get effect twice does not release the shared layer early"""
    released = yield from fx.Ref.make(0)
    memo = layer.MemoMap()
    shared = _release_counted(released)
    scope1, scope2 = fx.CloseableScope(), fx.CloseableScope()
    yield from shared.build_with_memo_map(memo, scope1)
    reuse = memo.get(shared, scope2)
    assert reuse is not None
    yield from reuse
    yield from reuse
    yield from scope2.close(fx.Success(None))
    assert (yield from released.get()) == 0
    yield from scope1.close(fx.Success(None))
    assert (yield from released.get()) == 1


@testing.effect
def test_a_get_effect_that_never_runs_does_not_keep_the_shared_layer_alive():
    """a get effect that never runs does not keep the shared layer alive"""
    released = yield from fx.Ref.make(0)
    memo = layer.MemoMap()
    shared = _release_counted(released)
    scope1, scope2 = fx.CloseableScope(), fx.CloseableScope()
    yield from shared.build_with_memo_map(memo, scope1)
    assert memo.get(shared, scope2) is not None
    yield from scope2.close(fx.Success(None))
    yield from scope1.close(fx.Success(None))
    assert (yield from released.get()) == 1


def test_does_not_memoize_a_build_before_its_effect_executes():
    """does not memoize a build before its Effect executes"""
    memo = layer.MemoMap()
    layer.effect_discard(fx.void).build_with_memo_map(memo, fx.CloseableScope())
    assert len(memo._entries) == 0


@testing.effect
def test_memoizes_suspend_across_builds():
    """memoizes suspend across builds"""
    log: list[str] = []
    evaluated = 0

    def make() -> layer.Layer[Service1Tag]:
        nonlocal evaluated
        evaluated += 1
        return make_layer1(log)

    l1 = layer.suspend(make)
    memo = layer.MemoMap()
    scope1, scope2 = fx.CloseableScope(), fx.CloseableScope()
    yield from l1.build_with_memo_map(memo, scope1)
    yield from l1.build_with_memo_map(memo, scope2)
    yield from scope2.close(fx.Success(None))
    assert evaluated == 1
    assert log == [ACQUIRE1]
    yield from scope1.close(fx.Success(None))
    assert log == [ACQUIRE1, RELEASE1]


@testing.effect
def test_memoizes_layer_across_builds():
    """memoizes layer across builds"""
    log: list[str] = []
    l1 = make_layer1(log)
    l2 = make_layer2(log).pipe(fx.provide(l1))
    memo = layer.MemoMap()
    scope1, scope2 = fx.CloseableScope(), fx.CloseableScope()
    yield from l1.build_with_memo_map(memo, scope1)
    yield from l2.build_with_memo_map(memo, scope2)
    yield from scope2.close(fx.Success(None))
    yield from l2.build_with_memo_map(memo, scope1)
    yield from scope1.close(fx.Success(None))
    assert log == [ACQUIRE1, ACQUIRE2, RELEASE2, ACQUIRE2, RELEASE2, RELEASE1]


@testing.effect
def test_layers_are_not_released_early():
    """layers are not released early"""
    log: list[str] = []
    l1 = make_layer1(log)
    l2 = make_layer2(log).pipe(fx.provide(l1))
    memo = layer.MemoMap()
    scope1, scope2 = fx.CloseableScope(), fx.CloseableScope()
    yield from l1.build_with_memo_map(memo, scope1)
    yield from l2.build_with_memo_map(memo, scope2)
    yield from scope1.close(fx.Success(None))
    yield from scope2.close(fx.Success(None))
    assert log == [ACQUIRE1, ACQUIRE2, RELEASE2, RELEASE1]


@testing.effect
def test_forked_memo_maps_reuse_parent_layers_but_isolate_child_layers():
    """forked memo maps reuse parent layers but isolate child layers"""
    log: list[str] = []
    parent = layer.MemoMap()
    child = parent.fork()
    scope1, scope2 = fx.CloseableScope(), fx.CloseableScope()
    parent_layer, child_layer = make_layer1(log), make_layer2(log)
    yield from parent_layer.build_with_memo_map(parent, scope1)
    yield from parent_layer.build_with_memo_map(child, scope2)
    yield from child_layer.build_with_memo_map(child, scope2)
    yield from child_layer.build_with_memo_map(parent, scope1)
    yield from scope2.close(fx.Success(None))
    yield from scope1.close(fx.Success(None))
    assert log == [ACQUIRE1, ACQUIRE2, ACQUIRE2, RELEASE2, RELEASE2, RELEASE1]
