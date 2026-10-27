"""Effect-valued arguments are validated when a combinator is called.

``fx.never.on_interrupt(lambda: ...)`` used to build fine, and the lambda
only surfaced as a defect inside the finalizer, where nothing reported it:
the finalizer silently did nothing. Every public callable with an
``Effect`` parameter now rejects anything else at once, with a
``TypeError`` naming the parameter. The guard test below walks the public
API, so a new combinator that forgets ``require_effect`` fails here.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import pkgutil
import re
import types
import typing
from collections.abc import Callable, Iterator
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing


def test_on_interrupt_rejects_a_lambda_when_called():
    with pytest.raises(TypeError, match=r"finalizer must be an Effect, got function"):
        fx.never.on_interrupt(lambda: None)  # pyright: ignore[reportArgumentType]


def test_the_error_suggests_wrapping_a_function():
    with pytest.raises(TypeError, match=r"fx\.sync\(f\)"):
        fx.void.ensuring(print)  # pyright: ignore[reportArgumentType]


def test_a_non_callable_gets_no_suggestion():
    with pytest.raises(TypeError, match=r"that must be an Effect, got int: 5$"):
        fx.void.zip(5)  # pyright: ignore[reportArgumentType]


def test_var_positional_effects_name_the_bad_index():
    with pytest.raises(TypeError, match=r"effects\[1\] must be an Effect"):
        fx.all(fx.void, None)  # pyright: ignore[reportCallIssue, reportArgumentType]


def test_transpose_option_rejects_a_non_effect_in_its_some():
    with pytest.raises(TypeError, match=r"^option\.value must be an Effect"):
        fx.transpose_option(fx.Some(lambda: None))  # pyright: ignore[reportArgumentType]


@testing.effect
def test_on_interrupt_with_an_effect_still_runs_on_interrupt():
    log: list[str] = []
    fiber = yield from fx.never.on_interrupt(fx.sync(lambda: log.append("ran"))).fork()
    yield from fx.yield_now()
    yield from fiber.interrupt()
    assert log == ["ran"]


# --- guard: every public Effect parameter is validated ---------------------------


def _public_modules() -> list[types.ModuleType]:
    submodules = [
        importlib.import_module(f"pyfect.{info.name}")
        for info in pkgutil.iter_modules(fx.__path__)
        if not info.name.startswith("_")
    ]
    return [fx, testing, *submodules]


def _is_public_module(name: str) -> bool:
    return not any(part.startswith("_") for part in name.split("."))


def _reachable() -> tuple[list[Callable[..., Any]], list[type]]:
    """The functions and classes a public module exposes. A function counts
    if it lives in a public module or an ``__all__`` exports it; a class
    counts wherever it lives, since public APIs return instances of private
    classes too (a fiber set runner's captured runtime)."""
    modules = _public_modules()
    exported = {id(getattr(m, n)) for m in modules for n in getattr(m, "__all__", ())}
    objects = {
        id(obj): obj
        for module in modules
        for name, obj in vars(module).items()
        if not name.startswith("_") and getattr(obj, "__module__", "").startswith("pyfect")
    }.values()
    functions = [
        obj
        for obj in objects
        if inspect.isfunction(obj) and (_is_public_module(obj.__module__) or id(obj) in exported)
    ]
    return functions, [obj for obj in objects if inspect.isclass(obj)]


def _methods(cls: type) -> Iterator[tuple[str, Callable[..., Any]]]:
    """Public methods defined on ``cls`` or its pyfect bases, as callables
    (class and static methods bound to ``cls``)."""
    for klass in cls.__mro__:
        if not klass.__module__.startswith("pyfect"):
            continue
        for name, member in vars(klass).items():
            raw = getattr(member, "__func__", member)
            if not name.startswith("_") and inspect.isfunction(raw):
                bound = getattr(cls, name) if raw is not member else raw
                yield f"{klass.__module__}.{klass.__qualname__}.{name}", bound


def _public_callables() -> Iterator[tuple[str, Callable[..., Any]]]:
    functions, classes = _reachable()
    for fn in functions:
        yield f"{fn.__module__}.{fn.__qualname__}", fn
    seen: set[str] = set()
    for cls in classes:
        for qualname, fn in _methods(cls):
            if qualname not in seen:
                seen.add(qualname)
                yield qualname, fn


_EFFECT = re.compile(r"(?:_core\.)?Effect(?:\[.*\])?")


def _is_effect_annotation(annotation: object) -> bool:
    """``Effect[...]`` itself, or a union with it at the top level (not an
    effect nested in a ``Callable`` or a collection)."""
    text = annotation if isinstance(annotation, str) else str(annotation)
    depth, current = 0, ""
    top: list[str] = []
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "|" and depth == 0:
            top.append(current.strip())
            current = ""
        else:
            current += ch
    top.append(current.strip())
    return any(_EFFECT.fullmatch(part) for part in top)


def _effect_parameters(fn: Callable[..., Any]) -> list[str]:
    signatures = [inspect.signature(getattr(o, "__func__", o)) for o in typing.get_overloads(fn)]
    signatures.append(inspect.signature(fn))
    names = {
        name
        for sig in signatures
        for name, p in sig.parameters.items()
        if name != "self" and _is_effect_annotation(p.annotation)
    }
    impl = inspect.signature(fn).parameters
    return [name for name in impl if name in names]


def _cases() -> list[tuple[str, Callable[..., Any], str]]:
    return [
        (qualname, fn, param)
        for qualname, fn in _public_callables()
        for param in _effect_parameters(fn)
    ]


_CASES = _cases()


def _not_an_effect() -> None:
    """What the M2 bug passed: a function where an effect was expected."""


def test_the_guard_finds_the_combinators_it_is_meant_to_check():
    names = {(q.rsplit(".", 1)[-1], p) for q, _, p in _CASES}
    assert ("on_interrupt", "finalizer") in names
    assert ("acquire_release", "acquire") in names
    assert ("run_sync", "eff") in names
    assert ("all", "effects") in names
    assert len(_CASES) > 50


@pytest.mark.parametrize(
    ("fn", "param"),
    [(fn, param) for _, fn, param in _CASES],
    ids=[f"{q}:{p}" for q, _, p in _CASES],
)
def test_a_non_effect_argument_is_rejected_when_called(fn: Callable[..., Any], param: str):
    args: list[object] = []
    kwargs: dict[str, object] = {}
    for name, p in inspect.signature(fn).parameters.items():
        effect_typed = name in _effect_parameters(fn)
        value: object = _not_an_effect if name == param else fx.void if effect_typed else object()
        if p.kind is p.VAR_POSITIONAL:
            args.extend([fx.void, value] if effect_typed else [])
        elif p.kind is p.VAR_KEYWORD or (p.default is not p.empty and name != param):
            continue
        elif p.kind is p.KEYWORD_ONLY:
            kwargs[name] = value
        else:
            args.append(value)
    expected = (
        f"{param}[1]"
        if inspect.signature(fn).parameters[param].kind is (inspect.Parameter.VAR_POSITIONAL)
        else param
    )
    with pytest.raises(TypeError, match=rf"^{re.escape(expected)} must be an Effect"):
        result = fn(*args, **kwargs)
        if inspect.iscoroutine(result):  # an async run function checks when awaited
            asyncio.run(result)
