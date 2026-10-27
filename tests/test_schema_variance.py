"""Every schema class states the variance of its type parameters.

A schema class is a frozen dataclass, and pyright infers its fields'
type parameters as invariant (``__replace__`` takes them), so a schema
needing no services would not be a schema needing some, and combinators
sharing one ``RD`` / ``RE`` (``TupleWithRest``) would reject it. Declaring
them (covariant unless a method takes a value of the type) keeps that
choice explicit; ``tests/type_checks.py`` pins the assignments.
"""

import inspect
from typing import Any, TypeVar

from pyfect import schema as S


def _parameters() -> list[tuple[str, TypeVar]]:
    """Each schema class's name with each of its type parameters."""
    classes: list[type[S.Bottom[Any, Any, Any, Any]]] = [
        o
        for o in vars(S).values()
        if inspect.isclass(o) and issubclass(o, S.Bottom) and o is not S.Bottom
    ]
    params: list[tuple[str, TypeVar]] = []
    for cls in classes:
        declared: tuple[object, ...] = getattr(cls, "__parameters__", ())
        params.extend((cls.__name__, p) for p in declared if isinstance(p, TypeVar))
    return params


def test_no_schema_class_infers_its_variance():
    inferred = [(name, p.__name__) for name, p in _parameters() if p.__infer_variance__]
    assert inferred == []


def test_schema_classes_are_covariant_in_their_services():
    services = [(name, p) for name, p in _parameters() if p.__name__.startswith(("RD", "RE"))]
    assert services
    assert [(name, p.__name__) for name, p in services if not p.__covariant__] == []
