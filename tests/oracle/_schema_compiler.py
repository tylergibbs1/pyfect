"""Shared helpers for the schema compiler ports (Effect's
``SchemaCompiler*``, ``SchemaJITCompiler*`` and ``SchemaAOTCompiler*``
tests)."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping

import pytest

from pyfect.schema.compiler import _registry
from pyfect.schema.jit_compiler import compiler as jit


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    """Each test starts with an empty registry and the interpreter, as each
    Effect test file runs in a fresh module graph."""
    _registry.reset()
    yield
    _registry.reset()


@pytest.fixture
def jit_installed(fresh_registry: None) -> None:
    """``import "effect/schema/SchemaJITCompiler/enable"``: compile every AST
    resolved from now on."""
    _registry.install(jit)


class Getters(Mapping[str, object]):
    """A mapping read like Effect's getter properties: ``reads[key]`` counts
    each read of ``key``; a value that is a ``Getter`` is called on every read
    (so it may raise or change). Membership does not read."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self.entries = dict(values)
        self.reads: dict[str, int] = dict.fromkeys(self.entries, 0)

    def __getitem__(self, key: str) -> object:
        if key not in self.entries:
            raise KeyError(key)
        self.reads[key] += 1
        value = self.entries[key]
        return value() if isinstance(value, Getter) else value

    def __contains__(self, key: object) -> bool:
        return key in self.entries

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


class Getter:
    """A computed value of ``Getters``."""

    def __init__(self, read: Callable[[], object]) -> None:
        self.read = read

    def __call__(self) -> object:
        return self.read()
