"""The ahead-of-time compiler integration run (Effect's
``fixtures/aot-runner.ts`` with ``aot-import-guard.ts``), started by
``test_schema_aot_compiler.py`` as ``python _schema_aot_runner.py DIR MODE``.

Every fixture is decoded, guarded and constructed by the interpreter, then
the generated modules in ``DIR`` are installed (``single``: one per schema,
``multiple``: ``all.py``) and every result must be the same. Once the
interpreted results are taken, importing the source generator or a
compiler, or compiling source that is not a file, raises."""

from __future__ import annotations

import asyncio
import importlib.abc
import importlib.util
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pyfect as fx
import pyfect.schema as S
from oracle import _schema_aot_fixtures as F
from pyfect.result import Err, Ok, Result
from pyfect.schema.compiler import _registry

_FORBIDDEN = (
    "pyfect.schema.compiler._codegen",
    "pyfect.schema.jit_compiler",
    "pyfect.schema.aot_compiler",
)


class _ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object, target: object = None) -> None:
        if fullname.startswith(_FORBIDDEN):
            raise ImportError("Generated modules must not load source generation or a compiler")


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event == "compile" and len(args) >= 2:
        filename = str(args[1])
        if filename.startswith("<") and args[0] is not None:
            raise RuntimeError(f"Code generation from strings disallowed ({filename})")


def _guard() -> None:
    for name in _FORBIDDEN:
        assert name not in sys.modules, f"{name} was imported"
    sys.meta_path.insert(0, _ImportGuard())
    sys.addaudithook(_audit)


class _Counted(Mapping[str, object]):
    """``{"value": 1}`` counting reads of ``value`` (Effect's getter)."""

    def __init__(self) -> None:
        self.reads = 0

    def __getitem__(self, key: str) -> object:
        if key != "value":
            raise KeyError(key)
        self.reads += 1
        return 1

    def __contains__(self, key: object) -> bool:
        return key == "value"

    def __iter__(self) -> Iterator[str]:
        return iter(("value",))

    def __len__(self) -> int:
        return 1


_OPTIONS: list[S.ParseOptions] = [
    {},
    {"errors": "all", "report_input": True},
    {"on_excess_property": "error"},
    {"disable_checks": True},
]


def _result(result: Result[Any, Any], name: str) -> object:
    if isinstance(result, Ok):
        return ("ok", result.value)
    assert isinstance(result, Err)
    issue = result.error.issue
    # Template diagnostics build internal nodes with fresh functions.
    return ("err", repr(issue) if name.startswith("template_literal") else issue)


def _snapshot() -> dict[str, object]:
    out: dict[str, object] = {}
    for name, (schema, inputs) in F.synchronous.items():
        is_ = S.is_(schema)
        rows: list[object] = []
        for options in _OPTIONS:
            decode = S.decode_unknown_result(schema, **options)
            for input in inputs:
                F.events.clear()
                result = _result(decode(input), name)
                rows.append((result, list(F.events), is_(input)))
        out[name] = rows
    return out


def _snapshot_async() -> list[object]:
    schema, inputs = F.async_fixture
    decode = S.decode_unknown_effect(schema)
    rows: list[object] = []
    for input in inputs:
        F.events.clear()
        result = asyncio.run(fx.run_async(decode(input).result()))
        rows.append((result, list(F.events)))
    return rows


def _snapshot_construction() -> list[object]:
    rows: list[object] = []
    for schema, inputs in F.construction_cases.values():
        make = S.make_effect(schema)
        for options in F.construction_options:
            for input in inputs:
                F.construction_events.clear()
                result = fx.run_sync(make(input, **options).result())
                rows.append((result, list(F.construction_events)))
    return rows


def _import(directory: Path, name: str) -> ModuleType:
    path = directory / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"aot_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install(directory: Path, mode: str) -> None:
    struct = F.schemas["struct"].__codec__().ast
    before = _registry.resolve(struct)
    empty = _import(directory, "empty")
    assert empty.install([]) is None
    assert _registry.resolve(struct) is before

    if mode == "multiple":
        generated = _import(directory, "all")
        assert _registry.resolve(struct) is before
        assert generated.install(F.roots()) is None
    else:
        for name, schema in F.schemas.items():
            ast = schema.__codec__().ast
            previous = _registry.resolve(ast) if name == "struct" else None
            generated = _import(directory, name)
            if previous is not None:
                assert _registry.resolve(ast) is previous
            assert generated.install([ast]) is None
    assert F.suspend_evaluations == [0]


def main(directory: Path, mode: str) -> None:
    interpreted = _snapshot()
    interpreted_async = _snapshot_async()
    interpreted_construction = _snapshot_construction()
    assert F.suspend_evaluations == [0]
    _guard()
    try:
        compile("1", "<string>", "eval")
    except RuntimeError:
        pass
    else:
        raise AssertionError("the guard let source be compiled")

    _install(directory, mode)

    for name in (
        "struct",
        "array",
        "tuple",
        "tagged",
        "record",
        "transformed",
        "transformed_struct",
        "pure_transformed_struct",
        "checked_transformed_struct",
        "encoding_checked_transformed_struct",
        "asynchronous",
        "middleware",
    ):
        assert callable(_registry.resolve(F.schemas[name].__codec__().ast).compiled), name

    assert _snapshot() == interpreted
    assert _snapshot_async() == interpreted_async
    for name, schema in F.construction_schemas.items():
        assert callable(_registry.resolve(schema.__codec__().ast).compiled), name
    assert _snapshot_construction() == interpreted_construction

    _check_examples()
    sys.stdout.write("AOT integration passed\n")


def _check_examples() -> None:
    transform = S.decode_unknown_result(F.schemas["transformed"])
    F.events.clear()
    assert transform("2") == Ok(2.0)
    assert F.events == ["transform"]
    F.events.clear()
    assert isinstance(transform("-1"), Err)
    assert F.events == ["transform"]

    F.events.clear()
    assert S.decode_unknown_result(F.schemas["middleware"])("-1") == Ok(1.0)
    assert F.events == ["transform", "middleware", "recover"]

    proof = F.proof
    assert S.decode_unknown_sync(proof)({"value": "a", "extra": True}) == {"value": "a"}
    assert S.make(proof)({"value": "constructed"}) == {"value": "constructed"}
    assert isinstance(S.decode_unknown_result(proof)({"value": 1}), Err)
    assert S.is_(proof)({"value": "a"}) is True
    assert S.is_(proof)({"value": 1}) is False
    proof_array = F.schemas["proof_array"]
    assert S.decode_unknown_sync(proof_array)([{"value": "a", "extra": True}]) == ({"value": "a"},)
    assert isinstance(S.decode_unknown_result(proof_array)([{"value": 1}]), Err)
    counted = _Counted()
    assert isinstance(S.decode_unknown_result(proof_array)([counted]), Err)
    assert counted.reads == 2

    assert S.decode_unknown_sync(F.lazy)({"value": "lazy"}) == {"value": "lazy"}
    assert F.suspend_evaluations == [1]


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
