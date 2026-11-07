"""Ports of Effect's ``SchemaAOTCompiler.test.ts``.

Python mappings: the generated module is Python (``case "decode":`` for
``case "decode":{``, ``runtime.set_compiler(`` for ``runtime.setCompiler(``,
``def dN(ast, resolve, operation)`` for ``function dN(ast,resolve,operation)``),
``Schema.UndefinedOr`` is ``S.NullOr`` and a JavaScript symbol key is
dropped. "honors enumerable excess checking directly in generated
operations" keeps its string keys: a Python mapping has no non-enumerable
or symbol keys. "preserves required, optional, and __proto__ property
presence checks": every required key is checked for presence (a Python
mapping has no prototype, so ``__proto__`` is an ordinary key). The
integration run ("runs generated decoders without dynamic code
generation") runs ``_schema_aot_runner.py`` in a subprocess that rejects
importing the source generator or a compiler and compiling any source
that is not a file.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pyfect.schema as S
from pyfect.schema import aot_compiler
from pyfect.schema import transformation as T
from pyfect.schema.aot_compiler import Target
from pyfect.schema.compiler import _registry

from . import _schema_aot_fixtures as fixtures
from ._schema_binary import Opt, struct
from ._schema_compiler import fresh_registry

__all__ = ["fresh_registry"]

_TESTS = Path(__file__).parent.parent


def _load(path: Path, source: str) -> ModuleType:
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_emits_deterministic_modules_without_installing_a_decoder():
    """emits deterministic modules without installing a decoder"""
    checks: list[None] = []

    def counted(_: object) -> bool:
        checks.append(None)
        return True

    schema = struct(value=S.String.check(S.make_filter(counted)))
    before = _registry.resolve(schema.ast)
    targets = [Target(schema.ast, ["decode"])]
    source = aot_compiler.compile(targets)
    assert aot_compiler.compile(targets) == source
    assert _registry.resolve(schema.ast) is before
    assert checks == []
    assert "from pyfect.schema.compiler import runtime" in source
    assert "exec(" not in source
    assert "jit_compiler" not in source


def test_emits_only_the_requested_operation_family():
    """emits only the requested operation family"""
    schema = struct(value=S.String)
    decode = aot_compiler.compile([Target(schema.ast, ["decode"])])
    assert 'case "decode":' in decode
    assert 'case "decode_effect":' in decode
    assert 'case "is":' not in decode
    assert 'case "make":' not in decode
    assert 'case "make_effect":' not in decode

    make = aot_compiler.compile([Target(schema.ast, ["make"])])
    assert 'case "make":' in make
    assert 'case "make_effect":' in make
    assert 'case "is":' not in make
    assert 'case "decode":' not in make


def test_allows_a_target_without_requested_operations():
    """allows a target without requested operations"""
    schema = struct(value=S.String)
    assert "runtime.set_compiler(" not in aot_compiler.compile([Target(schema.ast, [])])


def test_omits_fast_decode_operations_from_diagnostic_only_dependencies():
    """omits fast decode operations from diagnostic-only dependencies"""
    child = struct(value=S.String)
    schema = S.Array(child)
    source = aot_compiler.compile([Target(schema.ast, ["decode"])])
    assert source.count('case "decode":') == 1
    assert source.count('case "decode_effect":') == 2

    targeted = aot_compiler.compile([Target(schema.ast, ["decode"]), Target(child.ast, ["decode"])])
    assert targeted.count('case "decode":') == 2
    assert targeted.count('case "decode_effect":') == 2


def test_uses_registry_fallbacks_for_operations_that_were_not_requested(tmp_path: Path):
    """uses registry fallbacks for operations that were not requested"""
    schema = struct(value=S.String)
    generated = _load(
        tmp_path / "decode.py", aot_compiler.compile([Target(schema.ast, ["decode"])])
    )
    generated.install([schema.ast])

    entry = _registry.resolve(schema.ast)
    assert callable(entry.compiled)
    assert entry.decode is not None
    assert entry.is_ is None
    assert entry.make is None
    assert S.is_(schema)({"value": "a"}) is True
    assert S.make(schema)({"value": "a"}) == {"value": "a"}


def test_honors_enumerable_excess_checking_directly_in_generated_operations(tmp_path: Path):
    """honors enumerable excess checking directly in generated operations"""
    schema = S.StructWithRest(
        struct(fixed=Opt(S.String)),
        S.Record(S.TemplateLiteral("field-", S.Number), S.Number),
    )
    generated = _load(
        tmp_path / "decode.py", aot_compiler.compile([Target(schema.ast, ["decode", "is"])])
    )
    generated.install([schema.ast])
    entry = _registry.resolve(schema.ast)
    decode, is_ = entry.decode, entry.is_
    assert decode is not None, "Expected a compiled decoder"
    assert is_ is not None, "Expected a compiled type guard"
    strict: S.ParseOptions = {"on_excess_property": "error"}
    expected = {"field-1": 1}
    input = {**expected, "fixed": "declared"}
    for options in (_registry.DEFAULT_PARSE_OPTIONS, strict):
        assert decode(input, options) == {**expected, "fixed": "declared"}
        assert is_(input, options) is True
        assert decode({"field-1": "invalid"}, options) is _registry.INVALID
    assert decode({**expected, "extra": 1}, strict) is _registry.INVALID
    assert is_({**expected, "extra": 1}, strict) is False
    assert decode({}, strict) == {}


def test_initializes_dependency_operations_on_first_use(tmp_path: Path):
    """initializes dependency operations on first use"""
    child = S.String.pipe(S.decode_to(S.Number, T.transform(decode=float, encode=str))).annotate(
        title="lazy AOT dependency"
    )
    schema = struct(child=child)
    generated = _load(
        tmp_path / "decode.py", aot_compiler.compile([Target(schema.ast, ["decode"])])
    )
    generated.install([schema.ast])

    dependency = _registry.resolve(child.ast)
    assert not dependency.resolved("decode_effect")

    decode = S.decode_unknown_sync(schema)
    assert decode({"child": "1"}) == {"child": 1}
    assert not dependency.resolved("decode_effect")

    try:
        decode({"child": False})
    except S.SchemaError:
        pass
    else:
        raise AssertionError("expected a SchemaError")
    assert dependency.resolved("decode_effect")


def test_deduplicates_repeated_roots_and_dependencies_shared_across_roots():
    """deduplicates repeated roots and dependencies shared across roots"""
    child = struct(value=S.String)
    first = struct(child=child)
    second = S.Array(child)
    source = aot_compiler.compile([Target(first.ast, ["decode"]), Target(second.ast, ["decode"])])
    repeated = aot_compiler.compile(
        [
            Target(first.ast, ["decode"]),
            Target(second.ast, ["decode"]),
            Target(first.ast, ["decode"]),
            Target(second.ast, ["decode"]),
        ]
    )
    assert repeated == source
    assert source.count("runtime.set_compiler(") == 3


def test_reuses_identical_decoder_factories():
    """reuses identical decoder factories"""
    schema = S.Union(*(struct(tag=S.Literal(tag), value=S.Number) for tag in range(8)))
    source = aot_compiler.compile([Target(schema.ast, ["decode"])])
    assert len(re.findall(r"def d\d+\(ast, resolve, operation\)", source)) == 2


def test_preserves_required_optional_and_proto_property_presence_checks():
    """preserves required, optional, and __proto__ property presence checks"""
    schema = struct(
        required=S.NullOr(S.String),
        plain=S.String,
        optional=Opt(S.String),
        __proto__=S.String,
    )
    decode = aot_compiler.compile([Target(schema.ast, ["decode"])])
    for key in ("required", "plain", "__proto__"):
        assert re.search(rf"if '{key}' in m:\n(?:.*\n)*?\s*else: return I", decode)
    assert "if 'optional' in m:" in decode
    optional_block = decode.split("if 'optional' in m:")[1].split("if '__proto__' in m:")[0]
    assert "else: return I" not in optional_block

    guard = aot_compiler.compile([Target(schema.ast, ["is"])])
    assert re.search(r"if 'required' in m:\n(?:.*\n)*?\s*else: return False", guard)


def test_runs_generated_decoders_without_dynamic_code_generation(tmp_path: Path):
    """runs generated decoders without dynamic code generation"""
    operations: list[aot_compiler.Operation] = ["decode", "is", "make"]
    for name, schema in fixtures.schemas.items():
        (tmp_path / f"{name}.py").write_text(
            aot_compiler.compile([Target(schema.__codec__().ast, operations)])
        )
    (tmp_path / "all.py").write_text(
        aot_compiler.compile([Target(ast, operations) for ast in fixtures.roots()])
    )
    (tmp_path / "empty.py").write_text(aot_compiler.compile([]))
    assert fixtures.suspend_evaluations == [0]
    runner = Path(__file__).parent / "_schema_aot_runner.py"
    env: dict[str, Any] = {**os.environ, "PYTHONPATH": os.pathsep.join([str(_TESTS), *sys.path])}
    for mode in ("single", "multiple"):
        done = subprocess.run(
            [sys.executable, str(runner), str(tmp_path), mode],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        assert "AOT integration passed" in done.stdout
