"""Pydantic and pyfect schemas, each usable in the other. Needs the
``pydantic`` extra (``pip install 'pyfect[pydantic]'``).

A pyfect schema is a pydantic field type: annotate the field with it::

    from typing import Annotated

    from pydantic import BaseModel

    from pyfect import schema as S

    class Order(BaseModel):
        total: Annotated[float, S.FiniteFromString]

Python input is decoded with the schema (a value the schema's decoded side
already accepts is kept), JSON input with ``S.to_codec_json(schema)``;
dumping encodes the same way, and the JSON Schema is the schema's. A schema
class (``S.Class``) works as a field type directly. A failure is one
pydantic error, the pyfect message. Only schemas that need no services can
run inside pydantic.

``from_model(Model)`` goes the other way: a pyfect schema of a pydantic
model, decoding JSON values with ``Model.model_validate`` and encoding with
``model_dump(mode="json")``; pydantic's errors become a pyfect issue tree.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Never, cast

try:
    from pydantic import BaseModel, GetCoreSchemaHandler, GetJsonSchemaHandler, ValidationError
    from pydantic_core import CoreSchema, PydanticCustomError, core_schema
except ImportError as error:  # pragma: no cover - depends on the environment
    raise ImportError("pyfect.pydantic needs pydantic: pip install 'pyfect[pydantic]'") from error

from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.result import Err, Ok, Result
from pyfect.schema import (
    Bottom,
    Codec,
    Json,
    JsonValue,
    ParseOptions,
    SchemaError,
    decode_to,
    decode_unknown_result,
    encode_unknown_result,
    instance_of,
    to_codec_json,
    to_json_schema_document,
)
from pyfect.schema import ast as schema_ast
from pyfect.schema import transformation as T
from pyfect.schema.issue import Composite, InvalidValue, Issue, MissingKey, Pointer

__all__ = ["core_schema_of", "from_model", "json_schema_of"]

type _Codec = Codec[Any, Any, Never, Never]


def core_schema_of(schema: _Codec, /) -> CoreSchema:
    """The pydantic core schema validating and serializing with ``schema``
    (what ``__get_pydantic_core_schema__`` of a pyfect schema returns)."""
    json_codec = to_codec_json(schema)
    typed = schema.__codec__()

    def decode_python(input: object) -> object:
        decoded = decode_unknown_result(schema)(input)
        if isinstance(decoded, Ok):
            return decoded.value
        match schema_ast.run_now(typed.ast.to_type().parse(input, {})):
            case Success(value):
                return value
            case Failure():
                return _raise(decoded.error)

    def decode_json(input: object) -> object:
        return _unwrap(decode_unknown_result(json_codec)(input))

    def serialize(value: object, info: core_schema.SerializationInfo) -> object:
        codec = json_codec if info.mode_is_json() else schema
        return _unwrap(encode_unknown_result(codec)(value))

    return core_schema.json_or_python_schema(
        json_schema=core_schema.no_info_plain_validator_function(decode_json),
        python_schema=core_schema.no_info_plain_validator_function(decode_python),
        serialization=core_schema.plain_serializer_function_ser_schema(serialize, info_arg=True),
    )


def json_schema_of(schema: _Codec, /) -> dict[str, Any]:
    """``schema``'s JSON Schema for pydantic, with its definitions inlined
    (pydantic keeps its own ``$defs``); a recursive reference is left
    unconstrained."""
    document = to_json_schema_document(schema)
    return cast("dict[str, Any]", _inline(document.schema, document.definitions, ()))


def _inline(node: object, definitions: Mapping[str, object], seen: tuple[str, ...]) -> object:
    if isinstance(node, list):
        return [_inline(value, definitions, seen) for value in cast("list[object]", node)]
    if not isinstance(node, dict):
        return node
    fields = cast("dict[str, object]", node)
    out = {key: _inline(value, definitions, seen) for key, value in fields.items() if key != "$ref"}
    ref = fields.get("$ref")
    if not (isinstance(ref, str) and ref.startswith(_DEFS)):
        return out if ref is None else {**out, "$ref": ref}
    name = ref.removeprefix(_DEFS)
    if name in seen:
        return out
    target = cast("dict[str, object]", _inline(definitions[name], definitions, (*seen, name)))
    return {**target, **out}


_DEFS = "#/$defs/"


def get_pydantic_core_schema(
    schema: _Codec, _source: object, _handler: GetCoreSchemaHandler
) -> CoreSchema:
    return core_schema_of(schema)


def get_pydantic_json_schema(
    schema: _Codec, _core: CoreSchema, _handler: GetJsonSchemaHandler
) -> dict[str, Any]:
    return json_schema_of(schema)


def _unwrap(result: Result[object, SchemaError]) -> object:
    match result:
        case Ok(value):
            return value
        case Err(error):
            return _raise(error)


def _raise(error: SchemaError) -> Never:
    raise PydanticCustomError("pyfect_schema", "{message}", {"message": str(error)})


def from_model[M: BaseModel](model: type[M], /) -> Bottom[M, JsonValue]:
    """``model`` as a pyfect schema: decodes a JSON value with
    ``model.model_validate``, encodes with ``model_dump(mode="json")``.
    Each pydantic error is an issue at its location (``Missing key`` for a
    missing field)."""
    target = instance_of(model)
    node = target.ast

    def decode(input: JsonValue, _options: ParseOptions) -> Exit[M, Issue]:
        try:
            return Success(model.model_validate(input))
        except ValidationError as error:
            return fail_exit(_issue_of(error, node))

    def encode(value: M, _options: ParseOptions) -> Exit[JsonValue, Issue]:
        return Success(cast("JsonValue", value.model_dump(mode="json")))

    return Json.pipe(decode_to(target, T.transform_effect(decode=decode, encode=encode)))


def _issue_of(error: ValidationError, node: schema_ast.AST) -> Issue:
    issues: list[Issue] = []
    for detail in error.errors(include_url=False):
        leaf: Issue = (
            MissingKey()
            if detail["type"] == "missing"
            else InvalidValue({"message": detail["msg"]})
        )
        location = tuple(detail["loc"])
        issues.append(Pointer(location, leaf) if location else leaf)
    if len(issues) == 1:
        return issues[0]
    first, *rest = issues
    return Composite(node, (first, *rest))
