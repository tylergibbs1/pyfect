"""Ports of Effect's ``Effectable.test.ts`` and the ``Effectable.Class``
titles of ``Effect.test.ts``.

``Effectable.Mixin(Box)`` is multiple inheritance in Python:
``class EffectBox(effectable.Class[int], Box)`` (docs/PARITY.md section 4).

Omitted, with the reason:

- "shadows base prototype methods without modifying them": it checks
  ``toJSON`` / ``toString``, the JavaScript printing protocol.
- "inserts the Effect prototype between the subclass and original class":
  it walks JavaScript prototypes; the MRO check in "preserves the original
  constructor and instance members" is the Python form.
"""

from typing import Never

import pytest

import pyfect as fx
from pyfect import effectable, testing
from pyfect.exit import fail as exit_fail


class Box:
    def __init__(self, value: int) -> None:
        self.value = value

    def double(self) -> int:
        return self.value * 2


class EffectBox(effectable.Class[int], Box):
    def as_effect(self) -> fx.Effect[int]:
        return fx.succeed(self.value)


class Multiplier(fx.Tag[int], key="Multiplier"):
    pass


# Effect.test.ts: Effectable.Class


@testing.effect
def test_runs_using_as_effect():
    """runs using asEffect"""

    class Answer(effectable.Class[int]):
        def as_effect(self) -> fx.Effect[int]:
            return fx.succeed(42)

    assert (yield from Answer()) == 42


@testing.effect
def test_evaluates_as_effect_on_every_execution():
    """evaluates asEffect on every execution"""

    class Answer(effectable.Class[int]):
        value = 1

        def as_effect(self) -> fx.Effect[int]:
            return fx.succeed(self.value)

    answer = Answer()
    assert (yield from answer) == 1
    answer.value = 2
    assert (yield from answer) == 2


# Effectable.test.ts: Mixin


@testing.effect
def test_evaluates_as_effect():
    """evaluates asEffect"""
    assert (yield from EffectBox(1)) == 1


@testing.effect
def test_propagates_failures():
    """propagates failures"""

    class FailingBox(effectable.Class[Never, int], Box):
        def as_effect(self) -> fx.Effect[Never, int]:
            return fx.fail(self.value)

    assert (yield from FailingBox(1).exit()) == exit_fail(1)


@testing.effect
def test_uses_provided_services():
    """uses provided services"""

    class ServiceBox(effectable.Class[int, Never, Multiplier], Box):
        def as_effect(self) -> fx.Effect[int, Never, Multiplier]:
            return Multiplier().map(lambda multiplier: self.value * multiplier)

    value = yield from ServiceBox(2).pipe(fx.provide_service(Multiplier, 3))
    assert value == 6


def test_preserves_the_original_constructor_and_instance_members() -> None:
    """preserves the original constructor and instance members"""
    box = EffectBox(2)
    assert isinstance(box, EffectBox)
    assert isinstance(box, Box)
    assert type(box) is EffectBox
    assert box.value == 2
    assert box.double() == 4
    assert EffectBox.__mro__[-2] is Box


def test_makes_instances_behave_as_effects() -> None:
    """makes instances behave as Effects"""
    box = EffectBox(3)
    assert isinstance(box, fx.Effect)
    assert box.pipe(lambda b: b.value) == 3
    assert fx.run_sync(box.map(lambda n: n + 1)) == 4


def test_does_not_modify_the_original_class_prototype() -> None:
    """does not modify the original class prototype"""
    assert not isinstance(Box(1), fx.Effect)
    assert "as_effect" not in vars(Box)


# pyfect: a raising ``as_effect`` is a defect where the effect runs


def test_a_raising_as_effect_is_a_defect() -> None:
    class Broken(effectable.Class[int]):
        def as_effect(self) -> fx.Effect[int]:
            raise ValueError("boom")

    broken = Broken()
    ex = fx.run_sync_exit(broken)
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.find_defect(), ValueError)


def test_class_without_as_effect_cannot_be_instantiated() -> None:
    class Missing(effectable.Class[int]):
        pass

    with pytest.raises(TypeError):
        Missing()  # pyright: ignore[reportAbstractUsage]
