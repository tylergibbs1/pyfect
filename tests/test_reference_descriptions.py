"""Every page of the site's API reference has a description of its own: a public module's
docstring, or the docstring of a class a public module exports.

A reference page's meta description, which search results show, is the first paragraph of
its docstring. A class without one got `API reference for X.` (568 pages), or, with type
parameters, its bare `class X[A]` line. A class made by a call (`TypedDict("X", {...})`) is
listed as a value, not given a page. The OpenAI and OpenRouter packages generated from
their specs (`scripts/gen_ai_schemas.py`) are left out: their generator owns those files.
"""

from __future__ import annotations

import ast
import dataclasses
import functools
from pathlib import Path
from types import ModuleType

import _source
from _pyfect_modules import modules
from _source import SRC

import pyfect

GENERATED = ("pyfect.ai.openai.generated", "pyfect.ai.openrouter.generated")


def _generated(name: str) -> bool:
    return any(name == g or name.startswith(f"{g}.") for g in GENERATED)


def _module_name(path: Path) -> str:
    parts = path.relative_to(SRC.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


@functools.cache
def _class_statements() -> frozenset[str]:
    """The qualified name of every class a `class` statement defines, outside generated code."""
    names: set[str] = set()

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                names.add(prefix + node.name)
                visit(node.body, f"{prefix}{node.name}.")

    for path in _source.files(SRC):
        if not _generated(_module_name(path)):
            visit(_source.tree(path).body, "")
    return frozenset(names)


def own_docstring(cls: type) -> str | None:
    """The docstring ``cls``'s own source gives it. A dataclass or named tuple without one
    still has a ``__doc__``: its signature, ``Point(x: int, y: int)``. A ``__doc__`` that
    is a descriptor (``BindingDoc``) gives the class's own on the class."""
    doc: object = cls.__dict__.get("__doc__")
    if not isinstance(doc, str) and hasattr(doc, "__get__"):
        doc = getattr(cls, "__doc__", None)
    if not isinstance(doc, str) or not doc.strip():
        return None
    is_record = dataclasses.is_dataclass(cls) or hasattr(cls, "_fields")
    if is_record and "\n" not in doc and doc.startswith(f"{cls.__name__}("):
        return None
    return doc


def _exported_classes(module: ModuleType) -> list[tuple[str, type]]:
    names = getattr(module, "__all__", None)
    if names is None:
        names = [
            n
            for n, v in vars(module).items()
            if not n.startswith("_") and getattr(v, "__module__", None) == module.__name__
        ]
    return [
        (f"{module.__name__}.{name}", value)
        for name in names
        if isinstance(value := getattr(module, name, None), type)
        and value.__module__.startswith("pyfect")
    ]


def _public_classes() -> dict[type, str]:
    """Each class a public module exports, with the first public path that exports it."""
    found: dict[type, str] = {}
    for module in [pyfect, *modules(public=True, skip_missing_extras=True)]:
        if _generated(module.__name__):
            continue
        for path, cls in _exported_classes(module):
            if not _generated(cls.__module__) and cls.__qualname__ in _class_statements():
                found.setdefault(cls, path)
    return found


def test_every_public_module_has_a_docstring():
    missing: list[str] = []
    for path in _source.files(SRC):
        name = _module_name(path)
        if any(part.startswith("_") for part in name.split(".")) or _generated(name):
            continue
        if ast.get_docstring(_source.tree(path)) is None:
            missing.append(name)
    assert missing == []


def test_every_public_class_has_a_docstring():
    missing = sorted(path for cls, path in _public_classes().items() if own_docstring(cls) is None)
    assert missing == []


def test_the_walk_finds_the_classes_and_sees_a_signature_is_no_docstring():
    found = _public_classes()
    assert len(found) > 2000
    assert pyfect.Some in found

    @dataclasses.dataclass
    class Point:
        x: int

    @dataclasses.dataclass
    class Documented:
        """A point."""

        x: int

    assert own_docstring(Point) is None

    @dataclasses.dataclass(init=False)
    class Built:
        def __init__(self, *args: object) -> None: ...

    assert own_docstring(Built) is None
    assert own_docstring(Documented) == "A point."
