"""Find pyfect's public classes whose instances hold state their effects change.

A class counts when, in it or a pyfect base class, a method that is not a constructor assigns to
``self.<field>`` (or an item of it), or calls a mutating method (``append``, ``pop``, ...) on
one, and some method returns an ``Effect``. That is what a shared-state primitive looks like;
``SHARED_ELSEWHERE`` lists those whose state their effects change through other code.
"""

from __future__ import annotations

import ast
import functools
import inspect
import textwrap
from typing import cast

from _pyfect_modules import modules

_MUTATORS = frozenset(
    {
        "add",
        "append",
        "appendleft",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "popitem",
        "popleft",
        "remove",
        "setdefault",
        "update",
    }
)
_CONSTRUCTORS = frozenset(
    {
        "__init__",
        "__post_init__",
        "__new__",
        "__init_subclass__",
        "__set_name__",
        "__class_getitem__",
    }
)


def public_classes() -> dict[str, type]:
    """Every class a public pyfect module exports, by its full name (exceptions are values)."""
    found: dict[str, type] = {}
    for module in modules(public=True, skip_missing_extras=True):
        for name in getattr(module, "__all__", ()):
            obj: object = getattr(module, name, None)
            if (
                isinstance(obj, type)
                and obj.__module__.startswith("pyfect")
                and not issubclass(obj, BaseException)
            ):
                cls = cast(type[object], obj)
                found[full_name(cls)] = cls
    return found


def full_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def has_effectful_mutable_state(cls: type) -> bool:
    own = [base for base in cls.__mro__ if base.__module__.startswith("pyfect")]
    shapes = [_shape(base) for base in own]
    return any(mutates for mutates, _ in shapes) and any(effectful for _, effectful in shapes)


@functools.cache
def _shape(cls: type) -> tuple[bool, bool]:
    """Whether ``cls``'s own methods change ``self``'s fields, and whether one returns an
    ``Effect``."""
    try:
        node = ast.parse(textwrap.dedent(inspect.getsource(cls))).body[0]
    except (OSError, TypeError):
        return False, False
    assert isinstance(node, ast.ClassDef)
    mutates = effectful = False
    for method in node.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        if method.returns is not None and "Effect" in ast.unparse(method.returns):
            effectful = True
        if method.name not in _CONSTRUCTORS:
            mutates = mutates or any(_changes_self(n) for n in ast.walk(method))
    return mutates, effectful


def _changes_self(node: ast.AST) -> bool:
    match node:
        case ast.Assign(targets=targets) | ast.Delete(targets=targets):
            return any(_on_self(e) for t in targets for e in _elements(t))
        case ast.AugAssign(target=target) | ast.AnnAssign(target=target):
            return _on_self(target)
        case ast.Call(func=ast.Attribute(attr=attr, value=value)):
            return attr in _MUTATORS and _on_self(value)
        case _:
            return False


def _elements(target: ast.expr) -> list[ast.expr]:
    return list(target.elts) if isinstance(target, ast.Tuple | ast.List) else [target]


def _on_self(node: ast.expr) -> bool:
    while isinstance(node, ast.Subscript | ast.Attribute):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            return True
        node = node.value
    return False
