"""OpenRPC documents for RPC groups (Effect's ``OpenRpc``).

``from_rpc_group(Users, info={"title": "Users", "version": "1.0.0"})`` describes
each RPC of the group as an OpenRPC 1.3.2 method, with the JSON Schemas (Draft 7,
their shared definitions under ``components.schemas``) of what the JSON-RPC
serializer sends: the encoded payload as named (``by-name``) or positional
(``by-position``) params, the result, the errors, and for a streaming RPC the
``x-effect-stream`` extension describing its chunks. The group's and RPC's
``Summary``, ``Description``, ``Tags``, ``Examples``, ``Deprecated``,
``ExternalDocs`` and ``Errors`` annotations fill in the method (the RPC's win);
without ``Errors``, they are read from the error schemas' literal ``code`` and
``message`` fields.

An RPC whose payload is ``None`` (the default) takes no params.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, Required, TypedDict, cast

from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect._js import decode_uri_component, trim
from pyfect._json_text import quote
from pyfect.context import Context, Tag
from pyfect.json_schema import JsonSchema
from pyfect.rpc._rpc import AnyRpc, exit_schema
from pyfect.rpc.group import RpcGroup
from pyfect.rpc.schema import get_stream_schemas
from pyfect.schema import Top
from pyfect.schema import representation as R
from pyfect.schema._to_codec_json import to_codec_json_asts

type Json = Any


class OpenRPCContact(TypedDict, total=False):
    name: str
    url: str
    email: str


class OpenRPCLicense(TypedDict):
    name: str
    url: NotRequired[str]


class OpenRPCInfo(TypedDict):
    title: str
    version: str
    description: NotRequired[str]
    termsOfService: NotRequired[str]
    contact: NotRequired[OpenRPCContact]
    license: NotRequired[OpenRPCLicense]


class OpenRPCServerVariable(TypedDict):
    default: str
    enum: NotRequired[Sequence[str]]
    description: NotRequired[str]


class OpenRPCServer(TypedDict):
    name: str
    url: str
    summary: NotRequired[str]
    description: NotRequired[str]
    variables: NotRequired[Mapping[str, OpenRPCServerVariable]]


class OpenRPCExternalDocs(TypedDict):
    url: str
    description: NotRequired[str]


class OpenRPCTag(TypedDict):
    name: str
    summary: NotRequired[str]
    description: NotRequired[str]
    externalDocs: NotRequired[OpenRPCExternalDocs]


class OpenRPCExample(TypedDict):
    name: str
    value: Json
    summary: NotRequired[str]
    description: NotRequired[str]


class OpenRPCExamplePairing(TypedDict):
    name: str
    params: Sequence[OpenRPCExample]
    result: OpenRPCExample
    summary: NotRequired[str]
    description: NotRequired[str]


class OpenRPCError(TypedDict):
    code: int
    message: str
    data: NotRequired[Json]


class OpenRPCContentDescriptor(TypedDict):
    name: str
    schema: JsonSchema
    required: NotRequired[bool]
    summary: NotRequired[str]
    description: NotRequired[str]
    deprecated: NotRequired[bool]


class OpenRPCEffectStream(TypedDict):
    """How a streaming RPC's chunks are sent: as JSON-RPC responses with
    ``chunk: true``, acknowledged with ``@effect/rpc/Ack``."""

    encoding: Literal["effect-jsonrpc"]
    itemSchema: JsonSchema
    chunkSchema: JsonSchema
    errorSchema: JsonSchema
    causeSchema: JsonSchema
    ackMethod: Literal["@effect/rpc/Ack"]
    interruptMethod: Literal["@effect/rpc/Interrupt"]


type ParamStructure = Literal["by-name", "by-position", "either"]

OpenRPCMethod = TypedDict(
    "OpenRPCMethod",
    {
        "name": Required[str],
        "paramStructure": Required[ParamStructure],
        "params": Required[list[OpenRPCContentDescriptor]],
        "result": Required[OpenRPCContentDescriptor],
        "summary": str,
        "description": str,
        "tags": Sequence[OpenRPCTag],
        "examples": Sequence[OpenRPCExamplePairing],
        "deprecated": bool,
        "externalDocs": OpenRPCExternalDocs,
        "errors": Sequence[OpenRPCError],
        # The whole encoded payload, when the params alone cannot describe it.
        "x-effect-params-schema": JsonSchema,
        "x-effect-stream": OpenRPCEffectStream,
    },
    total=False,
)


class OpenRPCComponents(TypedDict):
    schemas: dict[str, JsonSchema]


class OpenRPCSpec(TypedDict):
    openrpc: Literal["1.3.2"]
    info: OpenRPCInfo
    servers: NotRequired[Sequence[OpenRPCServer]]
    methods: list[OpenRPCMethod]
    components: OpenRPCComponents


class Summary(Tag[str], key="effect/rpc/OpenRpc/Summary"):
    pass


class Description(Tag[str], key="effect/rpc/OpenRpc/Description"):
    pass


class Tags(Tag[Sequence[OpenRPCTag]], key="effect/rpc/OpenRpc/Tags"):
    pass


class Examples(Tag[Sequence[OpenRPCExamplePairing]], key="effect/rpc/OpenRpc/Examples"):
    pass


class Deprecated(Tag[bool], key="effect/rpc/OpenRpc/Deprecated"):
    pass


class ExternalDocs(Tag[OpenRPCExternalDocs], key="effect/rpc/OpenRpc/ExternalDocs"):
    pass


class Errors(Tag[Sequence[OpenRPCError]], key="effect/rpc/OpenRpc/Errors"):
    pass


_ANNOTATIONS: tuple[tuple[str, type[Tag[Any]]], ...] = (
    ("summary", Summary),
    ("description", Description),
    ("tags", Tags),
    ("examples", Examples),
    ("deprecated", Deprecated),
    ("externalDocs", ExternalDocs),
    ("errors", Errors),
)


def annotations(
    *,
    summary: str | None = None,
    description: str | None = None,
    tags: Sequence[OpenRPCTag] | None = None,
    examples: Sequence[OpenRPCExamplePairing] | None = None,
    deprecated: bool | None = None,
    external_docs: OpenRPCExternalDocs | None = None,
    errors: Sequence[OpenRPCError] | None = None,
) -> Context[Any]:
    """The given OpenRPC annotations as one context, for ``annotate_merge``."""
    given = {
        "summary": summary,
        "description": description,
        "tags": tags,
        "examples": examples,
        "deprecated": deprecated,
        "externalDocs": external_docs,
        "errors": errors,
    }
    context: Context[Any] = Context.empty()
    for key, tag in _ANNOTATIONS:
        value = given[key]
        if value is not None:
            context = context.add(tag, value)
    return context


@dataclass(slots=True)
class _Stream:
    item: int
    chunk: int
    error: int
    cause: int


@dataclass(slots=True)
class _Contract:
    rpc: AnyRpc
    payload: int
    result: int
    error_schema: Top
    stream: _Stream | None
    has_payload: bool = True
    param_structure: ParamStructure = "by-name"
    parameters: int | None = None


def from_rpc_group(
    group: type[RpcGroup[Any]],
    *,
    info: OpenRPCInfo,
    servers: Sequence[OpenRPCServer] | None = None,
) -> OpenRPCSpec:
    """The OpenRPC document of ``group``'s RPCs. Raises ``ValueError`` naming the
    method for a payload that is neither an object nor an array of params."""
    methods: list[OpenRPCMethod] = []
    components: dict[str, JsonSchema] = {}
    spec: OpenRPCSpec = {
        "openrpc": "1.3.2",
        "info": info,
        "methods": methods,
        "components": {"schemas": components},
    }
    if servers is not None:
        spec = {**spec, "servers": servers}
        spec["methods"] = methods
    rpcs = list(group.rpcs.values())
    if not rpcs:
        return spec
    nodes: list[Top] = []

    def register(schema: Top) -> int:
        nodes.append(schema)
        return len(nodes) - 1

    contracts: list[_Contract] = []
    for rpc in rpcs:

        def contract(rpc: AnyRpc = rpc) -> _Contract:
            exit_ = exit_schema(rpc)
            streams = get_stream_schemas(rpc.success_schema)
            return _Contract(
                rpc,
                register(rpc.payload_schema),
                register(exit_.value),
                exit_.error,
                None
                if streams is None
                else _Stream(
                    register(streams.success),
                    register(S.NonEmptyArray(streams.success)),
                    register(exit_.error),
                    register(S.Cause(exit_.error, exit_.defect)),
                ),
            )

        contracts.append(_with_method(rpc.tag, contract))
    json_nodes = to_codec_json_asts([node.__codec__().ast for node in nodes])
    first, *rest = (S.Bottom[Any, Any](node) for node in json_nodes)
    multi = R.to_representations((first, *rest))
    representations = list(multi.representations)
    references = multi.references
    for item in contracts:

        def project(item: _Contract = item) -> None:
            payload = _resolve(representations[item.payload], references)
            if isinstance(payload, (R.Null, R.Void, R.Undefined)):
                item.has_payload = False
            elif isinstance(payload, R.Objects):
                item.param_structure = "by-name"
                representations.append(R.Objects(property_signatures=payload.property_signatures))
                item.parameters = len(representations) - 1
            elif isinstance(payload, R.Arrays):
                item.param_structure = "by-position"
                optional = False
                for element in payload.elements:
                    if optional and not element.is_optional:
                        raise ValueError(
                            "optional positional parameters must follow required parameters"
                        )
                    optional = optional or element.is_optional
                representations.append(R.Arrays(elements=payload.elements))
                item.parameters = len(representations) - 1
            else:
                item.param_structure = _parameter_structure(payload, references, set())

        _with_method(item.rpc.tag, project)
    document = _compile(R.MultiDocument((representations[0], *representations[1:]), references))
    components.update(document.definitions)
    schemas = cast("list[JsonSchema]", document.schema["anyOf"])
    group_annotations = group.annotations
    methods.extend(
        _with_method(
            item.rpc.tag,
            lambda item=item: _method(
                item, schemas, representations, components, group_annotations
            ),
        )
        for item in contracts
    )
    return spec


def _method(
    item: _Contract,
    schemas: list[JsonSchema],
    representations: list[R.Representation],
    components: dict[str, JsonSchema],
    group_annotations: Context[Any],
) -> OpenRPCMethod:
    rpc = item.rpc
    merged = group_annotations.merge(rpc.annotations)
    params: list[OpenRPCContentDescriptor] = []
    if item.parameters is not None:
        projected = representations[item.parameters]
        root = schemas[item.parameters]
        if isinstance(projected, R.Objects):
            required = set(cast("list[str]", root.get("required", [])))
            properties = cast("dict[str, JsonSchema]", root.get("properties", {}))
            params = [
                {**_descriptor(name, schema, components), "required": name in required}
                for name, schema in properties.items()
            ]
            params.sort(key=lambda param: not param.get("required"))
        elif isinstance(projected, R.Arrays):
            items = cast("list[JsonSchema]", root.get("items", []))
            params = [
                {
                    **_descriptor(str(index), items[index], components),
                    "required": not element.is_optional,
                }
                for index, element in enumerate(projected.elements)
            ]
    method: OpenRPCMethod = {
        "name": rpc.tag,
        "paramStructure": item.param_structure,
        "params": params,
        "result": _descriptor("result", schemas[item.result], components),
    }
    for key, tag in _ANNOTATIONS:
        found = merged.get_option(tag)
        if found is not None:
            cast("dict[str, object]", method)[key] = found.value
    if "errors" not in method:
        errors = _derive_errors(item.error_schema)
        if errors:
            method["errors"] = errors
    if item.has_payload:
        method["x-effect-params-schema"] = schemas[item.payload]
    stream = item.stream
    if stream is not None:
        method["x-effect-stream"] = {
            "encoding": "effect-jsonrpc",
            "itemSchema": schemas[stream.item],
            "chunkSchema": schemas[stream.chunk],
            "errorSchema": schemas[stream.error],
            "causeSchema": schemas[stream.cause],
            "ackMethod": "@effect/rpc/Ack",
            "interruptMethod": "@effect/rpc/Interrupt",
        }
    return method


def _compile(multi: R.MultiDocument) -> JS.Document[Literal["draft-07"]]:
    # Relocate while the document is still Draft 2020-12, then lower to Draft 7.
    relocated = JS.to_multi_document_components(
        R.to_json_schema_multi_document(multi, on_excess_property="error"), target="OpenRPC"
    )
    return JS.to_document_draft_07_with_definitions_path(
        JS.Document("draft-2020-12", {"anyOf": list(relocated.schemas)}, relocated.definitions),
        ["components", "schemas"],
    )


def _with_method[A](name: str, f: Callable[[], A]) -> A:
    try:
        return f()
    except Exception as cause:
        raise ValueError(f"OpenRpc: method {quote(name)}: {cause}") from cause


def _resolve(
    representation: R.Representation,
    references: R.References,
) -> R.Representation:
    """``representation`` with references and suspensions followed."""
    seen: set[int] = set()
    while isinstance(representation, (R.Reference, R.Suspend)):
        if id(representation) in seen:
            raise ValueError("cyclic schema root cannot be resolved")
        seen.add(id(representation))
        if isinstance(representation, R.Suspend):
            representation = representation.thunk
            continue
        if representation.ref not in references:
            raise ValueError(f"unresolved schema {representation.ref}")
        representation = references[representation.ref]
    return representation


def _parameter_structure(
    node: R.Representation, references: R.References, seen: set[int]
) -> ParamStructure:
    payload = _resolve(node, references)
    if isinstance(payload, R.Objects):
        return "by-name"
    if isinstance(payload, R.Arrays):
        return "by-position"
    if isinstance(payload, R.Never):
        return "either"
    if isinstance(payload, R.Union):
        if id(payload) in seen:
            raise ValueError("cyclic payload root cannot be resolved")
        seen.add(id(payload))
        structure: ParamStructure | None = None
        for member in payload.types:
            found = _parameter_structure(member, references, seen)
            structure = found if structure is None or structure == found else "either"
        seen.discard(id(payload))
        return structure or "either"
    raise ValueError("payload must be an object or array of parameters")


_COMPONENTS = "#/components/schemas/"


def _resolve_schema(schema: JsonSchema, components: Mapping[str, JsonSchema]) -> JsonSchema | None:
    seen: set[int] = set()
    while isinstance(reference := schema.get("$ref"), str):
        if id(schema) in seen or not reference.startswith(_COMPONENTS):
            return None
        seen.add(id(schema))
        name = (
            decode_uri_component(reference[len(_COMPONENTS) :])
            .replace("~1", "/")
            .replace("~0", "~")
        )
        if name not in components:
            return None
        schema = components[name]
    return schema


def _descriptor(
    name: str, schema: JsonSchema, components: Mapping[str, JsonSchema]
) -> OpenRPCContentDescriptor:
    metadata = _resolve_schema(schema, components) or {}
    descriptor: OpenRPCContentDescriptor = {"name": name, "schema": schema}
    title, description, deprecated = (
        metadata.get("title"),
        metadata.get("description"),
        metadata.get("deprecated"),
    )
    if isinstance(title, str):
        descriptor["summary"] = title
    if isinstance(description, str):
        descriptor["description"] = description
    if isinstance(deprecated, bool):
        descriptor["deprecated"] = deprecated
    return descriptor


def _literal_values(
    node: R.Representation, references: R.References, seen: set[int]
) -> list[object] | None:
    if id(node) in seen:
        return None
    resolved = _resolve(node, references)
    values: list[object] | None
    match resolved:
        case R.Never():
            values = []
        case R.Null():
            values = [None]
        case R.Literal():
            values = [resolved.literal]
        case R.Enum():
            values = [value for _, value in resolved.enums]
        case R.Union():
            seen.add(id(node))
            values = _union_literals(resolved, references, seen)
            seen.discard(id(node))
        case _:
            values = None
    return values


def _union_literals(
    union: R.Union, references: R.References, seen: set[int]
) -> list[object] | None:
    values: list[object] = []
    for child in union.types:
        literals = _literal_values(child, references, seen)
        if literals is None:
            return None
        values.extend(literals)
    return values


def _js_number(value: object) -> float | None:
    """JavaScript's ``Number(value)`` for the literals an error code can be."""
    if isinstance(value, (bool, int, float)):
        return float(value)
    if value is None:
        return 0.0
    return _parse_js_number(trim(value)) if isinstance(value, str) else None


def _parse_js_number(text: str) -> float | None:
    if text == "":
        return 0.0
    if "_" in text:  # Python's digit separators are not JavaScript's
        return None
    try:
        return float(int(text, 0)) if text[:2].lower() in {"0x", "0o", "0b"} else float(text)
    except ValueError:
        return None


def _derive_errors(schema: Top) -> list[OpenRPCError]:
    # As the JSON-RPC serializer sends them: the code as a number (0 by default) and the
    # message.
    errors: dict[int, str] = {}
    document = R.to_representation(S.to_codec_json(schema))
    references = document.references
    seen: set[int] = set()
    pending = [document.representation]
    while pending:
        node = pending.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        resolved = _resolve(node, references)
        if isinstance(resolved, R.Union):
            pending.extend(reversed(resolved.types))
        elif isinstance(resolved, R.Objects):
            _object_errors(resolved, references, errors)
    return [{"code": code, "message": message} for code, message in errors.items()]


def _object_errors(node: R.Objects, references: R.References, errors: dict[int, str]) -> None:
    code = next((p for p in node.property_signatures if p.name == "code"), None)
    message = next((p for p in node.property_signatures if p.name == "message"), None)
    if message is None or message.is_optional:
        return
    messages = _literal_values(message.type, references, set())
    if messages is None or len(messages) != 1 or not isinstance(messages[0], str):
        return
    codes: list[object] | None = (
        (None if node.index_signatures else [0])
        if code is None
        else _literal_values(code.type, references, set())
    )
    for value in codes or []:
        number = _js_number(value)
        if number is not None and math.isfinite(number) and number.is_integer():
            errors.setdefault(int(number), messages[0])
    if code is not None and code.is_optional:
        errors.setdefault(0, messages[0])


__all__ = [
    "Deprecated",
    "Description",
    "Errors",
    "Examples",
    "ExternalDocs",
    "OpenRPCComponents",
    "OpenRPCContact",
    "OpenRPCContentDescriptor",
    "OpenRPCEffectStream",
    "OpenRPCError",
    "OpenRPCExample",
    "OpenRPCExamplePairing",
    "OpenRPCExternalDocs",
    "OpenRPCInfo",
    "OpenRPCLicense",
    "OpenRPCMethod",
    "OpenRPCServer",
    "OpenRPCServerVariable",
    "OpenRPCSpec",
    "OpenRPCTag",
    "ParamStructure",
    "Summary",
    "Tags",
    "annotations",
    "from_rpc_group",
]
