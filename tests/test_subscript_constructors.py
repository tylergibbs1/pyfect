"""A generic class's constructors honour a subscript: ``TxHashMap[int, State].make(...)``
makes a ``TxHashMap[int, State]``, as ``TxHashMap[int, State].empty()`` does.

A ``@staticmethod`` constructor with type parameters of its own ignores the
subscript silently, and so does a ``@classmethod`` that redeclares them: pyright
infers from the arguments (``Literal['waiting']`` for ``V``). A constructor is
a ``@classmethod`` with an overload for the bare class (its ``cls`` is
``type[X[Unsubscripted, ...]]``, the class's default type argument, and infers
from the arguments) and one taking the subscript; ``tests/type_checks.py`` pins
both (research/typing/ctor_1_subscript.py).

This walks the package for constructors (a static or class method whose return
annotation names its class and that has type parameters of its own), fails on
one that ignores the subscript, and checks each is pinned in type_checks.py.
"""

import importlib
import inspect
import pkgutil
import re
import typing
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pyfect

TYPE_CHECKS = Path(__file__).parent / "type_checks.py"

# The type arguments of these come from what they are given (a tag, a layer, the
# choices), not from a value the caller could widen, so there is nothing to subscript.
EXEMPT: dict[str, str] = {
    "pyfect.context.Context.make": "the tag decides the service type",
    "pyfect.context.Context.merge_all": "the union of the contexts' services",
    "pyfect.managed_runtime.ManagedRuntime.make": "the layer decides what it provides",
    "pyfect.cli.argument.Argument.choice_with_value": "the choices decide the value type",
    "pyfect.cli.argument.Argument.literals": "the choices decide the value type",
    "pyfect.cli.argument.Argument.file_schema": "the schema decides the value type",
    "pyfect.cli.flag.Flag.choice_with_value": "the choices decide the value type",
    "pyfect.cli.flag.Flag.literals": "the choices decide the value type",
    "pyfect.cli.flag.Flag.file_schema": "the schema decides the value type",
}


def _modules() -> Iterator[ModuleType]:
    for info in pkgutil.walk_packages(pyfect.__path__, "pyfect."):
        try:
            yield importlib.import_module(info.name)
        except ImportError:  # an optional extra that isn't installed
            continue


def _generic_classes() -> Iterator[type]:
    seen: set[type] = set()
    for module in _modules():
        namespace: dict[str, object] = vars(module)
        for value in namespace.values():
            if (
                inspect.isclass(value)
                and value not in seen
                and value.__module__.startswith("pyfect")
                and not value.__name__.startswith("_")
                and getattr(value, "__parameters__", ())
            ):
                seen.add(value)
                yield value


def _overloads(func: Callable[..., Any]) -> list[Callable[..., Any]]:
    return [getattr(f, "__func__", f) for f in typing.get_overloads(func)]


def _return(f: Callable[..., Any]) -> str:
    return str(inspect.get_annotations(f).get("return", ""))


def _names_class(f: Callable[..., Any], cls: type) -> bool:
    return re.search(rf"\b{cls.__name__}\[", _return(f)) is not None


type _Method = staticmethod[..., Any] | classmethod[Any, ..., Any]


def _constructors() -> Iterator[tuple[str, type, str, _Method]]:
    for cls in _generic_classes():
        for name, attr in vars(cls).items():
            if name.startswith("_") or not isinstance(attr, staticmethod | classmethod):
                continue
            method = typing.cast(_Method, attr)
            func: Callable[..., Any] = method.__func__
            signatures = [func, *_overloads(func)]
            if any(f.__type_params__ for f in signatures) and any(
                _names_class(f, cls) for f in signatures
            ):
                yield f"{cls.__module__}.{cls.__qualname__}.{name}", cls, name, method


def _takes_subscript(f: Callable[..., Any]) -> bool:
    cls_annotation = str(inspect.get_annotations(f).get("cls", ""))
    return "Unsubscripted" not in cls_annotation


def _ignores_subscript(attr: _Method) -> str | None:
    if isinstance(attr, staticmethod):
        return "a staticmethod ignores the subscript; make it a classmethod"
    overloads = _overloads(attr.__func__)
    if not overloads:
        return "its type parameters ignore the subscript; add overloads (see the docstring)"
    if not any(_takes_subscript(f) for f in overloads):
        return "no overload takes the subscript"
    return None


def test_constructors_honour_a_subscript():
    found = list(_constructors())
    assert len(found) > 30, "the walk found too few constructors"
    wrong = {
        path: problem
        for path, _cls, _name, attr in found
        if path not in EXEMPT and (problem := _ignores_subscript(attr)) is not None
    }
    assert wrong == {}


def test_exemptions_are_constructors():
    paths = {path for path, *_ in _constructors()}
    assert set(EXEMPT) <= paths


def test_each_constructor_is_pinned_with_a_subscript():
    text = TYPE_CHECKS.read_text()
    unpinned = [
        path
        for path, cls, name, _attr in _constructors()
        if path not in EXEMPT
        and re.search(rf"assert_type\(\s*[\w.]*\b{cls.__name__}\[[^\n]*?\]\.{name}\(", text) is None
    ]
    assert unpinned == []
