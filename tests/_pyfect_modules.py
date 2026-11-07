"""pyfect's modules, for tests that walk the whole package.

Importing ``pyfect.schema.jit_compiler.install`` compiles every schema
resolved afterwards (Effect's ``SchemaJITCompiler/enable``), so a walk that
imported it left the JIT installed for every later test. ``modules()`` never
imports it; ``conftest.py`` fails any test that leaves a compiler installed.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator
from types import ModuleType

import pyfect

INSTALLS_ON_IMPORT = frozenset({"pyfect.schema.jit_compiler.install"})
"""Modules whose import changes global state; they export nothing."""


def module_names() -> list[str]:
    """Every module under ``pyfect`` (not ``pyfect`` itself), without importing them."""
    return [info.name for info in pkgutil.walk_packages(pyfect.__path__, "pyfect.")]


def modules(*, public: bool = False, skip_missing_extras: bool = False) -> Iterator[ModuleType]:
    """Each module under ``pyfect``, imported, except ``INSTALLS_ON_IMPORT``.

    ``public``: only modules with no ``_`` part. ``skip_missing_extras``:
    leave out a module whose import fails because an optional extra is not
    installed."""
    for name in module_names():
        if name in INSTALLS_ON_IMPORT:
            continue
        if public and any(part.startswith("_") for part in name.split(".")):
            continue
        try:
            yield importlib.import_module(name)
        except ImportError:
            if not skip_missing_extras:
                raise
