"""``help()`` on a public layer constant shows that layer's own docstring.

``help(otel.tracer.layer)`` showed only the ``Layer`` class docstring, so what
the layer provides and needs was found only in the source (FINDINGS-turnstile
13). A layer bound at module level documents itself with the docstring below
its assignment (the one IDEs show on hover and the API reference reads), and
``Layer.__doc__`` reads that docstring back at run time. Every layer constant a
public module defines and exports has one.
"""

from __future__ import annotations

import ast
import inspect
import pydoc
from types import ModuleType

from _pyfect_modules import modules

from pyfect import layer
from pyfect.layer import Layer


def _assigned_names(module: ModuleType) -> set[str]:
    """The names ``module``'s own top level assigns."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for statement in tree.body:
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
            if isinstance(statement, ast.AnnAssign)
            else []
        )
        names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def _layer_constants() -> dict[str, Layer[object]]:
    found: dict[str, Layer[object]] = {}
    for module in modules(public=True, skip_missing_extras=True):
        exported = getattr(module, "__all__", ())
        if not exported:
            continue
        assigned = _assigned_names(module)
        for name in exported:
            value = getattr(module, name, None)
            if isinstance(value, Layer) and name in assigned:
                found[f"{module.__name__}.{name}"] = value
    return found


LAYERS = _layer_constants()


def test_the_walk_finds_the_layer_constants() -> None:
    assert "pyfect.otel.tracer.layer" in LAYERS
    assert len(LAYERS) > 100


def test_every_public_layer_constant_has_its_own_docstring() -> None:
    class_doc = inspect.getdoc(Layer)
    undocumented = [
        name for name, value in LAYERS.items() if inspect.getdoc(value) in (None, class_doc)
    ]
    assert undocumented == []


def test_help_shows_the_constants_docstring() -> None:
    from pyfect.otel import tracer

    text = pydoc.render_doc(tracer.layer)
    doc = inspect.getdoc(tracer.layer)
    assert doc is not None
    assert doc.splitlines()[0] in text
    assert "Builds the services" not in text


def test_the_class_and_unbound_layers_keep_the_class_docstring() -> None:
    class_doc = Layer.__doc__
    assert class_doc is not None
    assert class_doc.startswith("Builds the services")
    assert inspect.getdoc(layer.empty.pipe(layer.fresh)) == inspect.getdoc(Layer)
