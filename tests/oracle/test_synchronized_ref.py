"""Ports of Effect's ``SynchronizedRef.test.ts`` and
``SynchronizedRef.modifySomeEffect.test.ts``.

Each test's docstring is the Effect test title. Effect's module functions
are methods (``SynchronizedRef.getAndUpdateEffect(ref, f)`` is
``ref.get_and_update_effect(f)``). ``Effect.succeedSome(x)`` /
``Effect.succeedNone`` are ``fx.succeed(fx.Some(x))`` / ``fx.succeed(None)``.

Adapted, with the reason:

- "supports callback-only currying", "preserves the value for Option.none":
  methods have no curried form; the ports call ``modify_some_effect`` on the
  ref.
"""

from typing import Literal

import pyfect as fx
from pyfect import testing
from pyfect.option import Option

type State = Literal["Active", "Changed", "Closed"]

CURRENT = "value"
UPDATE = "new value"
FAILURE = "failure"


def _active_ref() -> fx.Effect[fx.SynchronizedRef[State]]:
    return fx.SynchronizedRef.make("Active")


def _some(state: State) -> fx.Effect[Option[State]]:
    return fx.succeed(fx.Some(state))


_none: fx.Effect[Option[State]] = fx.succeed(None)


@testing.effect
def test_get():
    """get"""
    result = yield from fx.SynchronizedRef.make(CURRENT).flat_map(lambda ref: ref.get())
    assert result == CURRENT


@testing.effect
def test_get_and_update_effect_happy_path():
    """getAndUpdateEffect - happy path"""
    ref = yield from fx.SynchronizedRef.make(CURRENT)
    assert (yield from ref.get_and_update_effect(lambda _: fx.succeed(UPDATE))) == CURRENT
    assert (yield from ref.get()) == UPDATE


@testing.effect
def test_get_and_update_effect_with_failure():
    """getAndUpdateEffect - with failure"""
    ref = yield from fx.SynchronizedRef.make(CURRENT)
    ex = yield from ref.get_and_update_effect(lambda _: fx.fail(FAILURE)).exit()
    testing.assert_exit_failure(ex, fx.cause.fail(FAILURE))
    assert (yield from ref.get()) == CURRENT


@testing.effect
def test_get_and_update_some_effect_happy_path():
    """getAndUpdateSomeEffect - happy path"""
    ref = yield from _active_ref()
    result = yield from ref.get_and_update_some_effect(
        lambda state: _some("Changed") if state == "Closed" else _none
    )
    assert result == "Active"
    assert (yield from ref.get()) == "Active"


@testing.effect
def test_get_and_update_some_effect_twice():
    """getAndUpdateSomeEffect - twice"""

    def second(state: State) -> fx.Effect[Option[State]]:
        match state:
            case "Closed":
                return _some("Active")
            case "Changed":
                return _some("Closed")
            case "Active":
                return _none

    ref = yield from _active_ref()
    first = yield from ref.get_and_update_some_effect(
        lambda state: _some("Changed") if state == "Active" else _none
    )
    assert first == "Active"
    assert (yield from ref.get_and_update_some_effect(second)) == "Changed"
    assert (yield from ref.get()) == "Closed"


@testing.effect
def test_get_and_update_some_effect_with_failure():
    """getAndUpdateSomeEffect - with failure"""

    def fail_when_active(state: State) -> fx.Effect[Option[State], str]:
        return fx.fail(FAILURE) if state == "Active" else _none

    ref = yield from _active_ref()
    ex = yield from ref.get_and_update_some_effect(fail_when_active).exit()
    testing.assert_exit_failure(ex, fx.cause.fail(FAILURE))


@testing.effect
def test_get_and_update_some_effect_interrupt_parent_fiber_and_update():
    """getAndUpdateSomeEffect - interrupt parent fiber and update"""
    deferred = yield from fx.Deferred[fx.SynchronizedRef[State]].make()
    latch = yield from fx.Deferred[None].make()
    fiber = yield from deferred.complete(_active_ref()).and_then(latch.wait()).fork()
    ref = yield from deferred.wait()
    yield from fiber.interrupt()
    assert (yield from ref.update_and_get_effect(lambda _: fx.succeed("Closed"))) == "Closed"


@testing.effect
def test_get_and_update_some_updates_the_backing_ref():
    """getAndUpdateSome updates the backing ref"""
    ref = yield from fx.SynchronizedRef.make(1)
    assert (yield from ref.get_and_update_some(lambda n: fx.Some(n + 1))) == 1
    assert (yield from ref.get()) == 2


@testing.effect
def test_supports_callback_only_currying():
    """supports callback-only currying"""
    ref = yield from fx.SynchronizedRef.make(1)
    result = yield from ref.modify_some_effect(
        lambda value: fx.succeed(("updated", fx.Some(value + 1)))
    )
    assert result == "updated"
    assert (yield from ref.get()) == 2


@testing.effect
def test_preserves_the_value_for_option_none():
    """preserves the value for Option.none"""

    def unchanged(_: int) -> fx.Effect[tuple[str, Option[int]]]:
        return fx.succeed(("unchanged", None))

    ref = yield from fx.SynchronizedRef.make(1)
    assert (yield from ref.modify_some_effect(unchanged)) == "unchanged"
    assert (yield from ref.get()) == 1
