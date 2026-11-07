"""Ports of Effect's ``SchemaCompilerStartup.test.ts``.

Python mapping: ``await import("effect/schema/SchemaJITCompiler/enable")``
imports ``pyfect.schema.jit_compiler.install`` (reloaded when an earlier test
imported it, as each Effect test file has its own module graph).
"""

from __future__ import annotations

import importlib
import sys

from pyfect import schema as S
from pyfect.schema.compiler import _registry

from ._schema_binary import struct
from ._schema_compiler import fresh_registry

__all__ = ["fresh_registry"]


def test_allows_late_global_activation_without_replacing_a_maker_s_interpreted_entry():
    """allows late global activation without replacing a maker's interpreted entry"""
    schema = struct(a=S.String)
    assert S.make(schema)({"a": "a"}) == {"a": "a"}
    before = _registry.resolve(schema.ast)
    assert before.compiled is None
    unused = struct(a=S.Number)
    make = S.make(unused)
    name = "pyfect.schema.jit_compiler.install"
    if name in sys.modules:
        importlib.reload(sys.modules[name])
    else:
        importlib.import_module(name)
    assert _registry.resolve(schema.ast) is before
    assert S.decode_unknown_sync(schema)({"a": "a"}) == {"a": "a"}
    assert make({"a": 1}) == {"a": 1}
    assert _registry.resolve(unused.ast).compiled is not None
