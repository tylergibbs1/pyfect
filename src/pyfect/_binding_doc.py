"""``__doc__`` for values bound at module level, read from the docstring below
their assignment.

Python keeps a module attribute's docstring only in the source, where IDEs
and the API reference read it, so ``help(value)`` showed the docstring of
the value's class instead. ``BindingDoc`` is a class's ``__doc__``: on the
class it is the class docstring; on an instance it is the docstring of the
module-level name the instance is bound to (found by identity among the
loaded modules, read from their source only then), else the class
docstring again, which ``help()`` takes to mean the instance has none.
"""

from __future__ import annotations

import ast
import functools
import inspect
import sys


@functools.cache
def _attribute_docs(module_name: str) -> dict[str, str]:
    """The docstrings of ``module_name``'s top-level assignments, by name."""
    module = sys.modules.get(module_name)
    try:
        source = inspect.getsource(module) if module is not None else ""
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError, ValueError):
        return {}
    docs: dict[str, str] = {}
    for statement, following in zip(tree.body, tree.body[1:], strict=False):
        match statement, following:
            case (
                ast.Assign(targets=[ast.Name(id=name)]) | ast.AnnAssign(target=ast.Name(id=name)),
                ast.Expr(value=ast.Constant(value=str(doc))),
            ):
                docs[name] = inspect.cleandoc(doc)
            case _:
                pass
    return docs


def binding_doc(value: object) -> str | None:
    """The docstring below a module-level assignment of ``value``, if any."""
    for module_name, module in list(sys.modules.items()):
        names = getattr(module, "__dict__", None)
        if not isinstance(names, dict):
            continue
        bound = [name for name, bound in list(names.items()) if bound is value]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        for name in bound:  # pyright: ignore[reportUnknownVariableType]
            doc = _attribute_docs(module_name).get(name)  # pyright: ignore[reportUnknownArgumentType]
            if doc is not None:
                return doc
    return None


class BindingDoc:
    """A class's ``__doc__`` (``__doc__ = BindingDoc(__doc__)`` in its body):
    instances bound to a documented module-level name show that docstring."""

    __slots__ = ("_class_doc",)

    def __init__(self, class_doc: str | None) -> None:
        self._class_doc = class_doc

    def __get__(self, instance: object, owner: type | None = None) -> str | None:
        if instance is None:
            return self._class_doc
        return binding_doc(instance) or self._class_doc
