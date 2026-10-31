"""Queries that run again when what they read changes (Effect's
``effect/reactivity/Reactivity``), and atoms (``atom``, ``atom_registry``,
``hydration``; ``atom_rpc`` and ``atom_http_api`` over RPC and HttpApi
clients, imported on first use)."""

import importlib as _importlib
import typing as _typing
from types import ModuleType as _ModuleType

from pyfect.reactivity import async_result, atom, atom_ref, atom_registry, hydration
from pyfect.reactivity._reactivity import (
    Keys,
    Reactivity,
    ReactivityService,
    invalidate,
    layer,
    make,
    mutation,
    query,
    stream,
)

if _typing.TYPE_CHECKING:
    from pyfect.reactivity import atom_http_api, atom_rpc
else:
    # They import the rpc and http_api packages, which ``sql`` (a user of
    # Reactivity) should not pay for.
    _LAZY = ("atom_http_api", "atom_rpc")

    def __getattr__(name: str) -> _ModuleType:
        if name in _LAZY:
            return _importlib.import_module(f"pyfect.reactivity.{name}")
        raise AttributeError(f"module 'pyfect.reactivity' has no attribute {name!r}")


__all__ = [
    "Keys",
    "Reactivity",
    "ReactivityService",
    "async_result",
    "atom",
    "atom_http_api",
    "atom_ref",
    "atom_registry",
    "atom_rpc",
    "hydration",
    "invalidate",
    "layer",
    "make",
    "mutation",
    "query",
    "stream",
]
