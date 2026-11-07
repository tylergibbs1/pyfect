"""What a user reads in a traceback or a repr names public pyfect modules:
every exception a public module exports has a public ``__module__`` that
exports it (``pyfect._public.publish``), and a missing service lists the
services the program provided, not the runtime's own."""

import builtins
import importlib
import inspect
import sys
import types
from typing import Any

import pytest
from _pyfect_modules import INSTALLS_ON_IMPORT, module_names

import pyfect as fx
from pyfect._public import is_private


def _public_modules() -> list[str]:
    walked = (name for name in module_names() if name not in INSTALLS_ON_IMPORT)
    return ["pyfect", *(name for name in walked if not is_private(name))]


def _exported_exceptions() -> dict[str, type[BaseException]]:
    found: dict[str, type[BaseException]] = {}
    for name in _public_modules():
        try:
            module = importlib.import_module(name)
        except ImportError:  # behind an extra that is not installed
            continue
        for attr in getattr(module, "__all__", ()):
            value: Any = getattr(module, attr, None)
            if isinstance(value, type) and issubclass(value, BaseException):
                found[f"{name}.{attr}"] = value
    return found


def test_every_exported_exception_names_a_public_module_that_exports_it():
    wrong: list[str] = []
    for where, cls in _exported_exceptions().items():
        home = importlib.import_module(cls.__module__)
        if is_private(cls.__module__) or getattr(home, cls.__name__, None) is not cls:
            wrong.append(f"{where}: {cls.__module__}.{cls.__qualname__}")
    assert wrong == []


def test_a_missing_service_lists_only_the_services_the_program_provided():
    class Db(fx.Tag[str]): ...

    class Cache(fx.Tag[int]): ...

    program: Any = Db().pipe(fx.provide_service(Cache, 1))
    with pytest.raises(fx.MissingServiceError) as caught:
        fx.run_blocking(program)
    assert str(caught.value) == (f"Service {Db.key} was not provided (available: {Cache.key})")


def test_a_missing_service_with_nothing_provided_says_none():
    class Db(fx.Tag[str]): ...

    program: Any = Db()
    with pytest.raises(fx.MissingServiceError, match=r"\(available: none\)$"):
        fx.run_blocking(program)


def test_a_schema_error_repr_is_its_message_not_the_schema_ast():
    from pyfect import schema as S

    match S.decode_unknown_result(S.Int)(30.5):
        case fx.Err(error=error):
            assert repr(error) == f"SchemaError({error.message!r})"
            assert len(repr(error)) < 200
        case other:
            pytest.fail(f"expected a SchemaError, got {other!r}")


def _public_definitions(module: types.ModuleType) -> list[str]:
    namespace: dict[str, object] = vars(module)
    return [
        name
        for name, value in namespace.items()
        if not name.startswith("_")
        and getattr(value, "__module__", None) == module.__name__
        and (inspect.isfunction(value) or inspect.isclass(value))
    ]


def test_every_public_module_lists_its_public_definitions_in_all():
    unlisted: list[str] = []
    for name in _public_modules():
        if name == "pyfect.testing.plugin":  # pytest hooks
            continue
        try:
            module = importlib.import_module(name)
        except ImportError:  # behind an extra that is not installed
            continue
        exported = getattr(module, "__all__", None)
        if exported is None:
            unlisted.append(f"{name} has no __all__")
            continue
        unlisted.extend(f"{name}.{d}" for d in _public_definitions(module) if d not in exported)
        unlisted.extend(f"{name}.{e} (listed, missing)" for e in exported if not hasattr(module, e))
    assert unlisted == []


@pytest.mark.parametrize("base", [fx.Tag, fx.Reference], ids=["Tag", "Reference"])
def test_calling_the_tag_base_class_itself_is_a_type_error(base: Any):
    with pytest.raises(TypeError, match="subclass it"):
        base()


# Effect's own names that start with ``unsafe`` (``unsafePreserveChecks``,
# ``Tool.unsafeSecureJsonParse``, ``Persistence.unsafeTtlToExpires``); every
# other unsafe API is Effect's ``xUnsafe``, spelled ``x_unsafe``.
_EFFECT_PREFIX_NAMES = {
    "unsafe_preserve_checks",
    "unsafe_secure_json_parse",
    "unsafe_ttl_to_expires",
}


def test_unsafe_names_use_effects_suffix():
    import ast
    from pathlib import Path

    source = Path(fx.__file__).parent
    found: set[str] = set()
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            match node:
                case ast.FunctionDef(name=name) | ast.ClassDef(name=name) | ast.arg(arg=name):
                    pass
                case ast.Name(id=name, ctx=ast.Store()) | ast.Attribute(attr=name):
                    pass
                case _:
                    continue
            if name.startswith("unsafe_") and name not in _EFFECT_PREFIX_NAMES:
                found.add(f"{path.relative_to(source)}: {name}")
    assert sorted(found) == []


class _Unresolved:
    def __class_getitem__(cls, _item: object) -> type["_Unresolved"]:
        return cls


class _Annotations(dict[str, object]):
    """Names an annotation string sees: the function's type parameters and module
    globals; a name that exists only under ``TYPE_CHECKING`` becomes a class of its
    own (not an exception), so the rest of the annotation still evaluates."""

    def __init__(self, fn: Any) -> None:
        super().__init__({t.__name__: t for t in getattr(fn, "__type_params__", ())})
        self.globals: dict[str, Any] = fn.__globals__

    def __missing__(self, name: str) -> object:
        if name in self.globals:
            return self.globals[name]
        if hasattr(builtins, name):
            return getattr(builtins, name)
        if name.startswith("__"):  # a frame lookup (pytest's __tracebackhide__)
            raise KeyError(name)
        return type(name, (_Unresolved,), {})


def _return_annotation(fn: Any) -> object:
    if sys.version_info >= (3, 14):
        import annotationlib

        annotations = annotationlib.get_annotations(fn, format=annotationlib.Format.STRING)
    else:
        annotations = inspect.get_annotations(fn)
    returned = annotations.get("return")
    return (
        eval(returned, fn.__globals__, _Annotations(fn)) if isinstance(returned, str) else returned
    )


def _failure_types(fn: Any) -> set[type[BaseException]]:
    """The exception classes in the error channel of ``fn``'s ``Effect`` return
    annotation (each overload's), unions flattened; TypeVars are skipped."""
    import typing

    from pyfect._core import Effect

    def flatten(t: object) -> list[object]:
        if typing.get_origin(t) in (typing.Union, types.UnionType):
            return [leaf for arg in typing.get_args(t) for leaf in flatten(arg)]
        return [t]

    found: set[type[BaseException]] = set()
    for signature in typing.get_overloads(fn) or [fn]:
        returned = _return_annotation(getattr(signature, "__func__", signature))
        if typing.get_origin(returned) is not Effect or len(typing.get_args(returned)) < 2:
            continue
        found.update(
            leaf
            for leaf in flatten(typing.get_args(returned)[1])
            if isinstance(leaf, type) and issubclass(leaf, BaseException)
        )
    return found


def _public_functions() -> list[tuple[str, types.ModuleType, Any]]:
    """(name, module, function) of each function a public module exports, and of
    each public method of a class it exports."""
    out: list[tuple[str, types.ModuleType, Any]] = []
    for name in _public_modules():
        try:
            module = importlib.import_module(name)
        except ImportError:  # behind an extra that is not installed
            continue
        for attr in getattr(module, "__all__", ()):
            value: Any = getattr(module, attr)
            if inspect.isfunction(value):
                out.append((f"{name}.{attr}", module, value))
            elif inspect.isclass(value) and value.__module__.startswith("pyfect."):
                for method, member in vars(value).items():
                    fn = getattr(member, "__func__", member)
                    if not method.startswith("_") and inspect.isfunction(fn):
                        out.append((f"{name}.{attr}.{method}", module, fn))
    return out


def test_every_error_a_public_function_fails_with_is_exported_by_a_public_module():
    """A user who catches it can import it from where it is documented."""
    wrong: set[str] = set()
    for where, _, fn in _public_functions():
        for error in _failure_types(fn):
            home = importlib.import_module(error.__module__)
            if error.__module__ == "builtins":
                continue
            if is_private(error.__module__) or error.__name__ not in getattr(home, "__all__", ()):
                wrong.add(f"{where}: {error.__module__}.{error.__qualname__}")
    assert sorted(wrong) == []


def test_a_module_that_has_an_error_its_functions_fail_with_exports_it():
    """``from pyfect.persistence.persisted_cache import PersistenceError`` works at
    runtime because the module imports it; it must also be in ``__all__``, or
    pyright reports a private import where the user met the error."""
    wrong: set[str] = set()
    for where, module, fn in _public_functions():
        exported = getattr(module, "__all__", ())
        for error in _failure_types(fn):
            if vars(module).get(error.__name__) is error and error.__name__ not in exported:
                wrong.add(f"{module.__name__}.{error.__name__} (met in {where})")
    assert sorted(wrong) == []
