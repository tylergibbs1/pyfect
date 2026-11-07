"""Importing this module compiles every schema AST resolved afterwards
(Effect's ``SchemaJITCompiler/enable``). Import it before the first parse:
parsers that already resolved an entry keep it."""

from __future__ import annotations

from pyfect.schema.compiler._registry import install as _install
from pyfect.schema.jit_compiler import compiler

_install(compiler)
