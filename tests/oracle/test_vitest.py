"""Ports of ``@effect/vitest``'s tests (``index``, ``timeout``,
``build-per-test``, ``isolation`` and ``nested-isolation``) to the pytest
plugin.

``it.layer(L)(it => ...)`` maps to ``layer_fixture(L)`` plus a first
parameter ``Services[...]``; a nested ``it.layer`` is one fixture of the
combined layer (``provide_merge``); a ``describe`` block whose layer is
released when the block ends is a test class with ``scope="class"``;
``buildPerTest`` is ``scope="function"``; ``excludeTestServices`` is
``live=True``.

Omitted: the ``utils`` assertion tests (pytest's ``assert``); ``skip`` /
``skipIf`` / ``runIf`` / ``describe.each`` / ``skip.each`` / ``fails``
(pytest marks, which apply to decorated tests unchanged); ``it.prop`` and
every property test (ported in ``test_vitest_prop.py``); effectful
``beforeAll`` / ``beforeEach`` hooks and their timeout tests (pytest
fixtures, and ``layer_fixture`` for effectful setup); ``describeWrapped``,
``makeMethods`` fixtures, layer concurrency and "nested sibling layers in
concurrent suites" (vitest's suite API; pytest runs tests one at a time).
"""

from collections.abc import Callable
from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect.duration import Duration
from pyfect.testing import Services


@testing.effect
def test_effect():
    """vitest/test/index.test.ts "effect"."""
    yield from fx.acquire_release(fx.sync(lambda: None), lambda _a, _e: fx.void)


@testing.live
def test_live():
    """vitest/test/index.test.ts "live"."""
    yield from fx.acquire_release(fx.sync(lambda: None), lambda _a, _e: fx.void)


@pytest.mark.parametrize("n", [1, 2, 3])
@testing.effect
def test_effect_each(n: int):
    """vitest/test/index.test.ts "effect each %s"."""
    value = yield from fx.acquire_release(fx.succeed(n), lambda _a, _e: fx.void)
    assert value == n


@pytest.mark.parametrize("n", [1, 2, 3])
@testing.live
def test_live_each(n: int):
    """vitest/test/index.test.ts "live each %s"."""
    value = yield from fx.acquire_release(fx.succeed(n), lambda _a, _e: fx.void)
    assert value == n


@pytest.mark.skip(reason="skipped anyway")
@testing.effect
def test_effect_skipped():
    """vitest/test/index.test.ts "effect skipped"."""
    yield from fx.die(RuntimeError("skipped anyway"))


# --- layer ------------------------------------------------------------------------------


class Foo(fx.Tag[str]): ...


class Bar(fx.Tag[str]): ...


class Sleeper(fx.Tag[Callable[[float], fx.Effect[None]]]): ...


FooLive = layer.succeed(Foo, "foo")
BarLive = layer.effect(Bar, Foo().map(lambda _: "bar"))
FooBarLive = BarLive.pipe(layer.provide_merge(FooLive))
SleeperLive = layer.effect(
    Sleeper, fx.Clock().map(lambda clock: lambda millis: clock.sleep(Duration(millis / 1000)))
)

foo = testing.layer_fixture(FooLive)
foo_bar = testing.layer_fixture(FooBarLive)
sleeper = testing.layer_fixture(SleeperLive)
live_sleeper = testing.layer_fixture(SleeperLive, live=True)


@testing.effect
def test_layer_adds_context(foo: Services[Foo]):
    """vitest/test/index.test.ts "layer > adds context"."""
    assert (yield from Foo()) == "foo"


@testing.effect
def test_layer_nested_adds_context(foo_bar: Services[Foo | Bar]):
    """vitest/test/index.test.ts "layer > nested > adds context"."""
    assert (yield from Foo()) == "foo"
    assert (yield from Bar()) == "bar"


@pytest.fixture
def value() -> int:
    return 1


@testing.effect
def test_layer_anonymous_layer_next_to_a_vitest_fixture_provides_its_context(
    foo: Services[Foo], value: int
):
    """vitest/test/index.test.ts "layer > anonymous layer next to a Vitest fixture > provides its
    context" (and "runs the fixture test": the fixture reaches the test)."""
    assert (yield from Foo()) == "foo"
    assert value == 1


@testing.effect
def test_layer_test_services_test_clock(sleeper: Services[Sleeper]):
    """vitest/test/index.test.ts "layer > test services > TestClock"."""
    sleep_millis = yield from Sleeper()
    fiber = yield from sleep_millis(100_000).fork()
    yield from fx.yield_now()
    yield from testing.adjust("100 seconds")
    yield from fiber.join()


@testing.effect
def test_layer_live_services_clock(live_sleeper: Services[Sleeper]):
    """vitest/test/index.test.ts "layer > live services > Clock"."""
    sleep_millis = yield from Sleeper()
    yield from sleep_millis(1)


# --- buildPerTest -----------------------------------------------------------------------


class Shared(fx.Tag[str]): ...


@dataclass(frozen=True)
class PerTestId:
    id: int


class PerTest(fx.Tag[PerTestId]): ...


shared_builds: list[None] = []
per_test_ids: list[int] = []
released_per_test_ids: list[int] = []

SharedLive = layer.effect(Shared, fx.sync(lambda: shared_builds.append(None)).as_("shared"))


def _acquire_per_test() -> PerTestId:
    per_test_ids.append(len(per_test_ids) + 1)
    return PerTestId(per_test_ids[-1])


PerTestLive = layer.effect(
    PerTest,
    Shared().and_then(
        fx.acquire_release(
            fx.sync(_acquire_per_test),
            lambda p, _e: fx.sync(lambda: released_per_test_ids.append(p.id)),
        )
    ),
)
shared = testing.layer_fixture(SharedLive)


@testing.effect
def test_build_per_test_builds_the_layer_for_the_test(shared: Services[Shared]):
    """build-per-test.test.ts "buildPerTest > shared > per test > builds the layer for the
    test"."""

    @fx.gen
    def body():
        per_test = yield from PerTest()
        assert per_test.id == 1
        assert released_per_test_ids == []

    yield from body.pipe(fx.provide(PerTestLive))


@testing.effect
def test_build_per_test_rebuilds_the_layer_once_the_previous_test_released_it(
    shared: Services[Shared],
):
    """build-per-test.test.ts "buildPerTest > shared > per test > rebuilds the layer once
    the previous test released it"."""

    @fx.gen
    def body():
        per_test = yield from PerTest()
        assert per_test.id == 2
        assert released_per_test_ids == [1]

    yield from body.pipe(fx.provide(PerTestLive))
    assert released_per_test_ids == [1, 2]
    assert len(shared_builds) == 1


@pytest.mark.parametrize("n", [3, 4])
@testing.effect
def test_build_per_test_rebuilds_the_layer_for_nested_test(shared: Services[Shared], n: int):
    """build-per-test.test.ts "buildPerTest > shared > per test > rebuilds the layer for
    nested test %s"."""
    per_test = yield from PerTest().pipe(fx.provide(PerTestLive))
    assert per_test.id == n


def test_build_per_test_after_all() -> None:
    """build-per-test.test.ts "buildPerTest" ``afterAll``: the shared layer was built
    once and every per-test layer released."""
    assert len(shared_builds) == 1
    assert released_per_test_ids == [1, 2, 3, 4]


empty = testing.layer_fixture(layer.empty, scope="function")


@pytest.mark.parametrize("n", [1, 2])
@testing.effect
def test_top_level_build_per_test_provides_new_test_services_for_test(
    empty: Services[object], n: int
):
    """build-per-test.test.ts "top-level buildPerTest > provides new test services for
    test %s"."""
    assert (yield from fx.clock.current_time_millis()) == 0
    yield from testing.adjust("1 second")


# --- isolation --------------------------------------------------------------------------


@dataclass(frozen=True)
class StateShape:
    id: int
    todos: fx.Ref[list[str]]
    migrated: fx.Ref[bool]


class State(fx.Tag[StateShape]): ...


class Todos(fx.Tag[StateShape]): ...


next_state_id: list[None] = []
observed_state_ids: list[int] = []


@fx.gen
def _make_state():
    next_state_id.append(None)
    todos = yield from fx.Ref.make(list[str]())
    migrated = yield from fx.Ref.make(False)
    return StateShape(len(next_state_id), todos, migrated)


BaseLive = layer.effect(State, _make_state)
MigrationLive = layer.effect(Todos, State().flat_map(lambda s: s.migrated.set(True).as_(s)))
InMemoryLive = MigrationLive.pipe(layer.provide(BaseLive))

first_block = testing.layer_fixture(InMemoryLive)
second_block = testing.layer_fixture(InMemoryLive)
third_block = testing.layer_fixture(InMemoryLive)


@testing.effect
def test_isolation_first_block_mutates_isolated_state(first_block: Services[Todos]):
    """isolation.test.ts "top-level it.layer isolation > first block mutates isolated
    state"."""
    state = yield from Todos()
    observed_state_ids.append(state.id)
    yield from state.todos.update(lambda todos: [*todos, "write tests"])
    assert (yield from state.migrated.get())
    assert (yield from state.todos.get()) == ["write tests"]


@testing.effect
def test_isolation_second_block_starts_fresh(second_block: Services[Todos]):
    """isolation.test.ts "top-level it.layer isolation > second block starts fresh"."""
    state = yield from Todos()
    observed_state_ids.append(state.id)
    assert (yield from state.migrated.get())
    assert (yield from state.todos.get()) == []
    yield from state.todos.update(lambda todos: [*todos, "ship feature"])
    assert (yield from state.todos.get()) == ["ship feature"]


@testing.effect
def test_isolation_third_block_also_starts_fresh(third_block: Services[Todos]):
    """isolation.test.ts "top-level it.layer isolation > third block also starts fresh"."""
    state = yield from Todos()
    observed_state_ids.append(state.id)
    assert (yield from state.migrated.get())
    assert (yield from state.todos.get()) == []
    assert observed_state_ids == [1, 2, 3]


# --- nested-isolation -------------------------------------------------------------------


class Parent(fx.Tag[str]): ...


@dataclass(frozen=True)
class ChildShape:
    id: int


class Child(fx.Tag[ChildShape]): ...


child_ids: list[int] = []
released_child_ids: list[int] = []


def _allocate_child() -> ChildShape:
    child_ids.append(len(child_ids) + 1)
    return ChildShape(child_ids[-1])


ParentLive = layer.succeed(Parent, "parent")
ChildLive = layer.effect(
    Child,
    Parent().and_then(
        fx.acquire_release(
            fx.sync(_allocate_child),
            lambda c, _e: fx.sync(lambda: released_child_ids.append(c.id)),
        )
    ),
).pipe(layer.provide_merge(ParentLive))
sibling = testing.layer_fixture(ChildLive, scope="class")


class TestNestedSiblingLayersFirstSibling:
    @testing.effect
    def test_allocates_child(self, sibling: Services[Child | Parent]):
        """nested-isolation.test.ts "nested sibling layers > parent > first sibling >
        allocates child"."""
        child = yield from Child()
        assert child.id == 1
        assert released_child_ids == []


class TestNestedSiblingLayersSecondSibling:
    @testing.effect
    def test_allocates_a_fresh_child(self, sibling: Services[Child | Parent]):
        """nested-isolation.test.ts "nested sibling layers > parent > second sibling >
        allocates a fresh child"."""
        child = yield from Child()
        assert child.id == 2
        assert released_child_ids == [1]


def test_nested_sibling_layers_after_all() -> None:
    """nested-isolation.test.ts "nested sibling layers" ``afterAll``."""
    assert child_ids == [1, 2]
    assert released_child_ids == [1, 2]


# --- timeouts and release, observed from an outer pytest run -----------------------------

RESOURCE = """
import pyfect as fx
from pyfect import testing

events = []


def resource(name):
    def release(_a, _e):
        return fx.sync(lambda: events.append(f"{name}:release:start")).and_then(
            testing.with_live(fx.sleep(0.25))
        ).and_then(fx.sync(lambda: events.append(f"{name}:release:end")))

    return fx.acquire_release(fx.sync(lambda: events.append(f"{name}:acquired")), release)
"""


@pytest.mark.parametrize("mode", ["effect", "live"])
def test_timeout_finalizers(pytester: pytest.Pytester, mode: str) -> None:
    """timeout.test.ts "it.${mode} timeout finalizers > times out while holding a resource"
    and "... > awaits the finalizer before starting the next test"."""
    pytester.makepyfile(resource=RESOURCE)
    pytester.makepyfile(
        f"""
        import pyfect as fx
        from pyfect import testing
        from resource import events, resource

        @testing.{mode}(timeout="75 millis")
        def test_times_out_while_holding_a_resource():
            yield from resource("test")
            return (yield from fx.never)

        def test_awaits_the_finalizer_before_starting_the_next_test():
            events.append("next:start")
            assert events == [
                "test:acquired", "test:release:start", "test:release:end", "next:start"
            ]
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(["*TestTimeoutError: test timed out after 0.075s*"])


def test_timeout_finalizer_defects(pytester: pytest.Pytester) -> None:
    """timeout.test.ts "it.effect timeout finalizer defects > times out while a finalizer
    dies" and "... > reports the finalizer defect"."""
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import testing

        @testing.effect(timeout="75 millis")
        def test_times_out_while_a_finalizer_dies():
            yield from fx.add_finalizer(lambda _: fx.die(RuntimeError("finalizer failed")))
            return (yield from fx.never)
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*TestTimeoutError*", "*RuntimeError: finalizer failed*"])


def test_layer_timeout_finalizers(pytester: pytest.Pytester) -> None:
    """timeout.test.ts "it.layer timeout finalizers > times out in the last test using the
    layer" and "... > awaits both test and layer finalizers before starting the next
    test"."""
    pytester.makepyfile(resource=RESOURCE)
    pytester.makepyfile(
        test_a="""
        import pyfect as fx
        from pyfect import layer, testing
        from resource import resource

        class Held(fx.Tag[None]): ...

        held = testing.layer_fixture(layer.effect(Held, resource("layer")))

        @testing.effect(timeout="75 millis")
        def test_times_out_in_the_last_test_using_the_layer(held: testing.Services[Held]):
            yield from resource("test")
            return (yield from fx.never)
        """,
        test_b="""
        from resource import events

        def test_awaits_both_test_and_layer_finalizers_before_starting_the_next_test():
            events.append("next:start")
            assert events == [
                "layer:acquired",
                "test:acquired",
                "test:release:start",
                "test:release:end",
                "layer:release:start",
                "layer:release:end",
                "next:start",
            ]
        """,
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, failed=1)


def test_layer_release(pytester: pytest.Pytester) -> None:
    """vitest/test/index.test.ts "layer > release > adds context" and its ``afterAll`` check that
    the layer was released."""
    pytester.makepyfile(
        test_a="""
        import pyfect as fx
        from pyfect import layer, testing

        released = []

        class Scoped(fx.Tag[str]): ...

        scoped = testing.layer_fixture(
            layer.effect(
                Scoped,
                fx.acquire_release(
                    fx.succeed("scoped"), lambda _a, _e: fx.sync(lambda: released.append(True))
                ),
            )
        )

        @testing.effect
        def test_adds_context(scoped: testing.Services[Scoped]):
            assert (yield from Scoped()) == "scoped"
            assert released == []
        """,
        test_b="""
        from test_a import released

        def test_released():
            assert released == [True]
        """,
    )
    pytester.runpytest().assert_outcomes(passed=2)
