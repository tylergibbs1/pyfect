"""Ports of the ``updateServiceScoped`` block of Effect's ``Effect.test.ts``.

Each test's docstring is the Effect test title. ``Effect.withFiber`` with
``fiber.setContext`` is the private ``_WithFiber`` / ``_set_context``.
"""
# pyright: reportPrivateUsage=false

from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect._core import _Sync, _WithFiber
from pyfect._fiber import Fiber


class CurrentNumber(fx.Tag[int], key="CurrentNumber"): ...


class CurrentNumberReference(fx.Reference[int], key="CurrentNumberReference"):
    @classmethod
    def default(cls) -> int:
        return 1


class CurrentValues(fx.Reference[tuple[str, ...]], key="CurrentValues"):
    @classmethod
    def default(cls) -> tuple[str, ...]:
        return ()


@testing.effect
def test_skips_restoration_when_the_provider_expires_before_scope_closure():
    """skips restoration when the provider expires before scope closure"""

    @fx.gen
    def program():
        yield from fx.update_service_scoped(CurrentNumber, lambda n: n + 1)
        return (yield from CurrentNumber())

    result = yield from fx.scoped(program.pipe(fx.provide_service(CurrentNumber, 1)))
    assert result == 2
    assert (yield from fx.service_option(CurrentNumber)) is None


@testing.effect
def test_updates_a_context_service_until_the_scope_closes():
    """updates a Context.Service until the scope closes"""

    @fx.gen
    def during():
        yield from fx.update_service_scoped(CurrentNumber, lambda n: n + 1)
        return (yield from CurrentNumber())

    @fx.gen
    def program():
        before = yield from CurrentNumber()
        inside = yield from fx.scoped(during)
        after = yield from CurrentNumber()
        return [before, inside, after]

    assert (yield from program.pipe(fx.provide_service(CurrentNumber, 1))) == [1, 2, 1]


@testing.effect
def test_updates_a_context_reference_until_the_scope_closes():
    """updates a Context.Reference until the scope closes"""

    @fx.gen
    def during():
        yield from fx.update_service_scoped(CurrentNumberReference, lambda n: n + 1)
        return (yield from CurrentNumberReference())

    before = yield from CurrentNumberReference()
    inside = yield from fx.scoped(during)
    after = yield from CurrentNumberReference()
    assert [before, inside, after] == [1, 2, 1]


@testing.effect
def test_supports_merging_the_current_value_on_reset():
    """supports merging the current value on reset"""
    scope = fx.CloseableScope()
    reset_values: list[tuple[str, ...]] = []

    def reset(
        original: tuple[str, ...], updated: tuple[str, ...], current: tuple[str, ...]
    ) -> tuple[str, ...]:
        reset_values.extend([original, updated, current])
        return (*original, *(value for value in current if value not in updated))

    def set_external(fiber: Fiber[Any, Any]) -> fx.Effect[None]:
        return _Sync(
            lambda: fiber._set_context(fiber._context.add(CurrentValues, ("scoped", "external")))
        )

    @fx.gen
    def program():
        yield from fx.update_service_scoped(
            CurrentValues, lambda values: (*values, "scoped"), reset=reset
        )
        yield from _WithFiber(set_external)
        yield from scope.close(fx.Success(None))
        return (yield from CurrentValues())

    result = yield from program.pipe(fx.provide_service(fx.Scope, scope))
    assert reset_values == [(), ("scoped",), ("scoped", "external")]
    assert result == ("external",)
