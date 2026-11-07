"""Ports of Effect's ``SchemaAOTCompilerBuild.test.ts``.

Python mappings: ``modules`` maps a dotted module name to a loader called
during the build (Effect's specifier to a dynamic import); a loader that
raises is a ``LoadModule`` failure whose cause is the exception (Effect's
rejection value). The generated module reaches a root through
``m0.Port.__codec__().ast.flip()`` / ``.to_type()`` (Effect's
``A.flip(m0["Port"].ast)``)."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

import pyfect as fx
import pyfect.schema as S
from pyfect import testing
from pyfect.file_system import FileSystem, NoopFileSystem, layer_noop
from pyfect.path import Path as PathTag
from pyfect.path import layer as path_layer
from pyfect.platform_error import PlatformError
from pyfect.schema.aot_compiler.build import BuildError, BuildResult, build
from pyfect.schema.compiler import _registry

from . import _schema_aot_build_fixture as schemas
from ._schema_compiler import fresh_registry

__all__ = ["fresh_registry"]

_FIXTURE = schemas.__name__


class _Disk(NoopFileSystem):
    def make_directory(self, path: str, *, recursive: bool = False, mode: int = 0o777) -> Any:
        return fx.sync(lambda: Path(path).mkdir(parents=recursive, exist_ok=True))

    def write_file_string(self, path: str, data: str, *, flag: Any = "w", mode: int = 0o666) -> Any:
        return fx.sync(lambda: Path(path).write_text(data) and None)


class _Capture(NoopFileSystem):
    def __init__(self) -> None:
        self.written = ""

    def make_directory(self, path: str, *, recursive: bool = False, mode: int = 0o777) -> Any:
        return fx.void

    def write_file_string(self, path: str, data: str, *, flag: Any = "w", mode: int = 0o666) -> Any:
        def write() -> None:
            self.written = data

        return fx.sync(write)


def _run(
    effect: fx.Effect[BuildResult, BuildError | PlatformError, FileSystem | PathTag],
    file_system: NoopFileSystem,
) -> fx.Effect[BuildResult, BuildError | PlatformError]:
    provided: Any = effect.pipe(fx.provide(layer_noop(file_system))).pipe(fx.provide(path_layer))
    return provided


@testing.effect
def test_writes_a_deterministic_self_installing_module(tmp_path: Path):
    """writes a deterministic self-installing module"""
    out_file = str(tmp_path / "generated.py")
    options: dict[str, Any] = {
        "modules": {_FIXTURE: lambda: importlib.import_module(_FIXTURE)},
        "out_file": out_file,
        "operations": ["make", "decode", "is", "encode", "decode"],
    }
    first: BuildResult = yield from _run(build(**options), _Disk())
    source = Path(out_file).read_text()
    second: BuildResult = yield from _run(build(**options), _Disk())
    assert first == BuildResult(out_file, 1, 2)
    assert second == first
    assert Path(out_file).read_text() == source
    assert "m0.Port.__codec__().ast.flip()" in source
    assert "m0.Port.__codec__().ast.to_type()" in source
    assert "ignored" not in source

    before = _registry.resolve(schemas.User.ast)
    spec = importlib.util.spec_from_file_location("generated_build", out_file)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert _registry.resolve(schemas.User.ast) is not before
    assert S.decode_unknown_sync(schemas.User)({"name": "Ada", "port": "8080"}) == {
        "name": "Ada",
        "port": 8080,
    }
    assert S.is_(schemas.User)({"name": "Ada", "port": 8080}) is True
    assert S.make(schemas.User)({"name": "Ada", "port": 8080}) == {"name": "Ada", "port": 8080}
    assert S.encode_unknown_sync(schemas.User)({"name": "Ada", "port": 8080}) == {
        "name": "Ada",
        "port": "8080",
    }


@testing.effect
def test_uses_decoding_as_the_default_operation_and_ignores_non_schema_exports():
    """uses decoding as the default operation and ignores non-Schema exports"""
    capture = _Capture()
    result: BuildResult = yield from _run(
        build(
            modules={
                _FIXTURE: lambda: importlib.import_module(_FIXTURE),
                "oracle.ignored": lambda: {"value": 1},
            },
            out_file="/generated/schema_aot.py",
        ),
        capture,
    )
    assert result == BuildResult("/generated/schema_aot.py", 1, 2)
    written = capture.written
    assert ".flip()" not in written
    assert ".to_type()" not in written
    assert "oracle.ignored" not in written
    assert 'case "is":' not in written
    assert 'case "make":' not in written
    assert 'case "make_effect":' not in written
    assert "install([m0.Port.__codec__().ast, m0.User.__codec__().ast])" in written


@testing.effect
def test_reports_module_loading_failures():
    """reports module loading failures"""
    boom = RuntimeError("boom")

    def failing() -> object:
        raise boom

    error: object = yield from _run(
        build(modules={"oracle.failing": failing}, out_file="/generated/schema_aot.py"),
        NoopFileSystem(),
    ).flip()
    assert isinstance(error, BuildError)
    assert error.kind == "LoadModule"
    assert error.module == "oracle.failing"
    assert error.cause is boom


@testing.effect
def test_reports_invalid_loaded_modules():
    """reports invalid loaded modules"""
    error: object = yield from _run(
        build(modules={"oracle.invalid": lambda: 1}, out_file="/generated/schema_aot.py"),
        NoopFileSystem(),
    ).flip()
    assert isinstance(error, BuildError)
    assert error.kind == "InvalidModule"
    assert error.module == "oracle.invalid"
    assert error.cause == 1
