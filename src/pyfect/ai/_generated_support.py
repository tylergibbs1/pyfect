"""What the generated provider schemas (``pyfect.ai.openai.generated``,
``pyfect.ai.openrouter.generated``) are built with. Each builder takes and
gives ``Any``: a generated schema's type is declared from
``generated_types`` (both come from the same source by the same
generator), so the type checker reads thousands of declarations instead
of solving each schema expression, and ``struct`` builds a struct from
its field schemas without reading the TypedDict's annotations (as
``S.Struct`` does, which would slow the import down)."""

from __future__ import annotations

import importlib
import re
from typing import Any, cast

from pyfect import schema as S
from pyfect.schema import ast
from pyfect.schema._struct import StructSchema


def struct(_typed_dict: object, fields: dict[str, Any], optional: tuple[str, ...] = ()) -> Any:
    """The struct of these field schemas; the keys in ``optional`` may be
    missing. The TypedDict names the struct's type for the reader."""
    schemas = {name: schema.__codec__() for name, schema in fields.items()}
    node = ast.Objects(
        tuple(
            ast.PropertySignature(name, schema.ast, optional=name in optional)
            for name, schema in schemas.items()
        ),
        (),
    )
    return cast("Any", StructSchema(node, schemas))


def union(*members: Any, mode: ast.UnionMode = "any_of") -> Any:
    return S.Union(*members, mode=mode)


def array(item: Any) -> Any:
    return S.Array(item)


def record(key: Any, value: Any) -> Any:
    return S.Record(key, value)


def struct_with_rest(schema: Any, *records: Any) -> Any:
    return S.StructWithRest(schema, *records)


def suspend(thunk: Any) -> Any:
    return cast("Any", S.suspend(thunk))


def check(schema: Any, *checks: Any) -> Any:
    return schema.check(*checks)


def literals(values: list[Any]) -> Any:
    return S.Literals(values)


def literal(value: Any) -> Any:
    return S.Literal(value)


def js_pattern(python: str, source: str) -> Any:
    """``is_pattern`` of the generator's Python translation of the
    JavaScript pattern ``source``, which messages show."""
    return S.is_pattern(re.compile(python), expected=f"a string matching the RegExp {source}")


def instance_of(cls: type, **annotations: object) -> Any:
    return cast("Any", S.instance_of(cls, **annotations))


def lazy(module: str, name: str) -> Any:
    """The schema ``name`` of ``module``, imported on first use: a
    recursive schema's struct, declared after the schemas that use it."""

    def load() -> Any:
        return getattr(importlib.import_module(module), name)

    return cast("Any", S.suspend(load))
