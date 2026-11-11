"""The streaming modules' public functions and constructors say what they do in ``help()``.

``Queue.sliding``, ``dropping`` and ``unbounded`` had no docstring, so ``help()`` showed
nothing for them (FINDINGS-sluice 16).
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterator

MODULES = (
    "pyfect.stream",
    "pyfect.channel",
    "pyfect.sink",
    "pyfect.pull",
    "pyfect.queue",
    "pyfect.pubsub",
)


def public_callables() -> Iterator[tuple[str, object]]:
    """Each public function, and each public class's constructors (class and static
    methods), by the name users reach it with."""
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        for name in module.__all__:
            value = getattr(module, name)
            if inspect.isfunction(value):
                yield f"{module_name}.{name}", value
            elif inspect.isclass(value):
                for attribute in vars(value):
                    raw = inspect.getattr_static(value, attribute)
                    if not attribute.startswith("_") and isinstance(
                        raw, (classmethod, staticmethod)
                    ):
                        yield f"{module_name}.{name}.{attribute}", getattr(value, attribute)


def test_every_public_function_and_constructor_has_its_own_docstring() -> None:
    found = list(public_callables())
    assert "pyfect.queue.Queue.sliding" in dict(found)
    assert [name for name, f in found if not getattr(f, "__doc__", None)] == []
