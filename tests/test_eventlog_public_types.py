"""The eventlog's public signatures say what they take and give: no bare ``Any``
(dogfood quill #2: ``when_authenticated`` was typed ``Effect[Any, Any, Any]`` and needed
an ``Identity`` pyright never saw). Erased types are ``object``; the two named existentials
``AnyEvent`` and ``AnyWrite`` stand for "an event (a write) of some payload", whose payload
the ``Event`` (the ``Write``) itself checks."""

from __future__ import annotations

import importlib
import inspect
import re
import typing
from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest

MODULES = [
    "event",
    "event_journal",
    "event_log",
    "event_log_encryption",
    "event_log_remote",
    "event_log_server",
    "event_log_server_encrypted",
    "event_log_server_unencrypted",
    "event_row",
]

_ANY = re.compile(r"\bAny\b")


def _annotations(function: Callable[..., object]) -> Iterator[tuple[str, str]]:
    # Callers see the overloads, not the implementation behind them.
    for candidate in typing.get_overloads(function) or [function]:
        try:
            signature = inspect.signature(candidate)
        except (TypeError, ValueError):
            continue
        for parameter in signature.parameters.values():
            if parameter.annotation is not inspect.Parameter.empty:
                yield parameter.name, str(parameter.annotation)
        if signature.return_annotation is not inspect.Signature.empty:
            yield "return", str(signature.return_annotation)


def _public_members(cls: type) -> Iterator[tuple[str, object]]:
    for name, value in vars(cls).items():
        if name.startswith("_") and name != "__call__":
            continue
        member: object = value
        if isinstance(member, (classmethod, staticmethod)):
            member = cast("classmethod[Any, Any, Any]", member).__func__
        if isinstance(member, property):
            member = member.fget
        yield name, member


def _any_in_public_signatures(module_name: str) -> list[str]:
    module = importlib.import_module(f"pyfect.eventlog.{module_name}")
    declared: dict[str, object] = getattr(module, "__annotations__", {})
    found: list[str] = []
    for name in module.__all__:
        value = getattr(module, name)
        if name in declared and _ANY.search(str(declared[name])):
            found.append(f"{name}: {declared[name]}")
        if getattr(value, "__module__", module.__name__) != module.__name__:
            continue  # re-exported: checked where it is defined
        if isinstance(value, typing.TypeAliasType):
            if _ANY.search(str(value.__value__)) and name not in {"AnyEvent", "AnyWrite"}:
                found.append(f"{name} = {value.__value__}")
        elif inspect.isfunction(value):
            found += [f"{name}({p}): {a}" for p, a in _annotations(value) if _ANY.search(a)]
        elif inspect.isclass(value):
            for field, annotation in getattr(value, "__annotations__", {}).items():
                if not field.startswith("_") and _ANY.search(str(annotation)):
                    found.append(f"{name}.{field}: {annotation}")
            for member, function in _public_members(value):
                if inspect.isfunction(function):
                    found += [
                        f"{name}.{member}({p}): {a}"
                        for p, a in _annotations(function)
                        if _ANY.search(a)
                    ]
    return found


@pytest.mark.parametrize("module_name", MODULES)
def test_public_signatures_have_no_bare_any(module_name: str) -> None:
    assert _any_in_public_signatures(module_name) == []


def test_the_guard_sees_any_in_a_signature() -> None:
    from pyfect.eventlog import event_log_remote

    service = event_log_remote.EventLogRemoteService
    original = service.__annotations__["when_authenticated"]
    service.__annotations__["when_authenticated"] = "Callable[[Effect[Any, Any, Any]], Any]"
    try:
        assert _any_in_public_signatures("event_log_remote") == [
            "EventLogRemoteService.when_authenticated: Callable[[Effect[Any, Any, Any]], Any]"
        ]
    finally:
        service.__annotations__["when_authenticated"] = original
