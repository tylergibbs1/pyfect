"""``copy.replace`` for services whose operations are methods over private
slots (they were dataclasses until 0.6.0).

``replaced(service, changes)`` calls the service's constructor with each
parameter taken from ``changes`` or else from the slot that holds it: ``_name``
for an operation, ``name`` for a plain attribute. ``tests/test_service_copy.py``
builds every such service and checks that a copy keeps every slot.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any


def _slots(cls: type) -> set[str]:
    names: set[str] = set()
    for klass in cls.__mro__:
        declared = vars(klass).get("__slots__", ())
        names.update((declared,) if isinstance(declared, str) else declared)
    return names


def replaced[S](
    service: S, changes: Mapping[str, Any], *, stored: Mapping[str, str] | None = None
) -> S:
    """A copy of ``service`` with ``changes``. ``stored`` names the slot of a
    parameter that is not held in ``_name`` or ``name``."""
    cls = type(service)
    slots = _slots(cls)
    signature = inspect.signature(cls.__init__)
    unknown = set(changes) - signature.parameters.keys()
    if unknown:
        raise TypeError(f"{cls.__qualname__} has no parameters {sorted(unknown)}")
    positional: list[Any] = []
    keywords: dict[str, Any] = {}
    for name, parameter in list(signature.parameters.items())[1:]:
        if name in changes:
            value = changes[name]
        else:
            slot = (stored or {}).get(name) or next(
                (s for s in (f"_{name}", name) if s in slots), None
            )
            if slot is None:
                raise TypeError(f"{cls.__qualname__}.{name} is held in no slot")
            value = getattr(service, slot)
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            positional.append(value)
        else:
            keywords[name] = value
    return cls(*positional, **keywords)
