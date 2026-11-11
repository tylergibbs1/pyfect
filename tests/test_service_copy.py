"""``copy.replace`` works on every service that was a dataclass until 0.6.0.

Their operations became methods over private slots, so ``dataclasses.replace``
no longer applies; each has a ``__replace__`` built on ``_service_copy``. A
copy must keep every slot it does not change, and take what it changes.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
from typing import Any

import pytest
from test_service_docs import SERVICES

import pyfect as fx
from pyfect import stream
from pyfect._service_copy import replaced

_SERVICES: dict[str, type] = SERVICES

REPLACEABLE: dict[str, type] = {
    name: service
    for name, service in _SERVICES.items()
    if "__replace__" in vars(service) and not dataclasses.is_dataclass(service)
}


def _value_for(annotation: object) -> object:
    text = str(annotation)
    if text.startswith(("Effect[", "Acquirer")):
        return fx.succeed(object())
    if text.startswith("Stream["):
        return stream.make(object())
    return object()


def _build(service: type) -> tuple[Any, dict[str, object]]:
    values: dict[str, object] = {}
    positional: list[object] = []
    for name, parameter in list(inspect.signature(service.__init__).parameters.items())[1:]:
        value = _value_for(parameter.annotation)
        values[name] = value
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            positional.append(value)
    keywords = {
        name: value
        for name, value in values.items()
        if inspect.signature(service.__init__).parameters[name].kind
        is not inspect.Parameter.POSITIONAL_ONLY
    }
    return service(*positional, **keywords), values


def _slot_values(instance: object) -> dict[str, object]:
    out: dict[str, object] = {}
    for klass in type(instance).__mro__:
        declared = vars(klass).get("__slots__", ())
        for slot in (declared,) if isinstance(declared, str) else declared:
            out[slot] = getattr(instance, slot)
    return out


def test_every_former_dataclass_service_is_replaceable() -> None:
    assert len(REPLACEABLE) >= 36


@pytest.mark.parametrize("service", REPLACEABLE.values(), ids=list(REPLACEABLE))
def test_a_copy_keeps_every_slot(service: type) -> None:
    built, _ = _build(service)
    copied = copy.replace(built)
    assert copied is not built
    assert type(copied) is service
    original = _slot_values(built)
    assert {k: v is original[k] for k, v in _slot_values(copied).items()} == dict.fromkeys(
        original, True
    )


@pytest.mark.parametrize("service", REPLACEABLE.values(), ids=list(REPLACEABLE))
def test_a_copy_takes_each_change(service: type) -> None:
    built, values = _build(service)
    for name, value in values.items():
        changed = _value_for(inspect.signature(service.__init__).parameters[name].annotation)
        copied = copy.replace(built, **{name: changed})
        slots = _slot_values(copied)
        assert any(v is changed for v in slots.values()), name
        assert not any(v is value for v in slots.values()), name


def test_an_unknown_change_is_refused() -> None:
    service = next(iter(REPLACEABLE.values()))
    built, _ = _build(service)
    with pytest.raises(TypeError, match="no parameters"):
        replaced(built, {"no_such_parameter": 1})
