"""The OpenAPI 3.1 document of an ``HttpApi`` (Effect's ``OpenApi``).

``from_api(api)`` describes every endpoint not excluded: its parameters,
request body and responses, with the schemas' JSON Schemas under
``components.schemas``. The annotations below (on the API, a group or an
endpoint) fill in the document's text::

    api = HttpApi.make("api").annotate(openapi.Title, "Users API")
"""

import copy
import re
from collections.abc import Callable, Mapping
from typing import Any, Never, TypedDict, Unpack
from weakref import WeakKeyDictionary

from pyfect.context import Context, Reference, Tag, TagLike
from pyfect.http.method import has_body
from pyfect.http_api import _path
from pyfect.http_api import schema as api_schema
from pyfect.http_api._openapi_responses import response_bodies, stream_media_type
from pyfect.http_api._openapi_schemas import SchemaOps
from pyfect.http_api.api import AdditionalSchemas, AnyApi, ReflectedEndpoint, reflect
from pyfect.http_api.endpoint import AnyEndpoint, BufferedPayload, payload_schemas
from pyfect.http_api.group import AnyGroup
from pyfect.http_api.security import ApiKey, Basic, Http, HttpApiSecurity
from pyfect.json_schema import VALID_OPEN_API_COMPONENTS_SCHEMAS_KEY_REGEXP
from pyfect.schema import ReferencePolicy, Top, ast

type Json = dict[str, Any]

_PATH_PARAM = re.compile(r"\{[^}]+\}")


class Identifier(Tag[str], key="effect/http-api/OpenApi/Identifier"):
    """An endpoint's ``operationId``."""


class Title(Tag[str], key="effect/http-api/OpenApi/Title"):
    """The API's title, or a group's tag name."""


class Version(Tag[str], key="effect/http-api/OpenApi/Version"):
    pass


class Description(Tag[str], key="effect/http-api/OpenApi/Description"):
    pass


class License(Tag[Mapping[str, Any]], key="effect/http-api/OpenApi/License"):
    """``{"name": ..., "url": ...}``."""


class ExternalDocs(Tag[Mapping[str, Any]], key="effect/http-api/OpenApi/ExternalDocs"):
    """``{"url": ..., "description": ...}``."""


class Servers(Tag[tuple[Mapping[str, Any], ...]], key="effect/http-api/OpenApi/Servers"):
    """``({"url": ..., "description": ...}, ...)``."""


class Format(Tag[str], key="effect/http-api/OpenApi/Format"):
    """A bearer security's ``bearerFormat``."""


class Summary(Tag[str], key="effect/http-api/OpenApi/Summary"):
    pass


class Deprecated(Tag[bool], key="effect/http-api/OpenApi/Deprecated"):
    pass


class Override(Tag[Mapping[str, Any]], key="effect/http-api/OpenApi/Override"):
    """Keys set on the generated object, replacing what was there."""


class Exclude(Reference[bool], key="effect/http-api/OpenApi/Exclude"):
    """Leave the group or endpoint out of the document."""

    @classmethod
    def default(cls) -> bool:
        return False


class Transform(Tag[Callable[[Json], Json]], key="effect/http-api/OpenApi/Transform"):
    """A function of the generated object (the document, a tag or an
    operation) giving the one to use."""


class AnnotationOptions(TypedDict, total=False):
    identifier: str
    title: str
    version: str
    description: str
    license: Mapping[str, Any]
    summary: str
    deprecated: bool
    external_docs: Mapping[str, Any]
    servers: tuple[Mapping[str, Any], ...]
    format: str
    override: Mapping[str, Any]
    exclude: bool
    transform: Callable[[Json], Json]


_ANNOTATION_TAGS: Mapping[str, Any] = {
    "identifier": Identifier,
    "title": Title,
    "version": Version,
    "description": Description,
    "license": License,
    "summary": Summary,
    "deprecated": Deprecated,
    "external_docs": ExternalDocs,
    "servers": Servers,
    "format": Format,
    "override": Override,
    "exclude": Exclude,
    "transform": Transform,
}


def annotations(**options: Unpack[AnnotationOptions]) -> Context[Never]:
    """The annotations of ``options`` (for ``annotate_merge``)."""
    result: Context[Any] = Context.empty()
    for key, value in options.items():
        result = result.add(_ANNOTATION_TAGS[key], value)
    return result


class FromApiOptions(TypedDict, total=False):
    include_annotation_key: Callable[[str], bool]
    """Admits other annotations with JSON values into the schemas."""
    reference_policy: ReferencePolicy
    """Decides which schemas become components (``None``: inline)."""


type _OptionsKey = tuple[Callable[[str], bool] | None, ReferencePolicy | None]

_cache: WeakKeyDictionary[AnyApi, dict[_OptionsKey, Json]] = WeakKeyDictionary()


def from_api(api: AnyApi, **options: Unpack[FromApiOptions]) -> Json:
    """The OpenAPI document of ``api`` (a fresh copy on each call). It is
    made once per API and option functions."""
    key = (options.get("include_annotation_key"), options.get("reference_policy"))
    by_options = _cache.setdefault(api, {})
    spec = by_options.get(key)
    if spec is None:
        spec = by_options[key] = _make(api, *key)
    return copy.deepcopy(spec)


def _get[S, T](context: Context[Any], tag: TagLike[S, T], apply: Callable[[S], None]) -> None:
    found = context.get_option(tag)
    if found is not None:
        apply(found.value)


def _make(
    api: AnyApi, include: Callable[[str], bool] | None, policy: ReferencePolicy | None
) -> Json:
    spec: Json = {
        "openapi": "3.1.0",
        "info": {"title": "Api", "version": "0.0.1"},
        "paths": {},
        "components": {"schemas": {}, "securitySchemes": {}},
        "security": [],
        "tags": [],
    }
    info: Json = spec["info"]
    ops = SchemaOps()
    finalizers: list[Callable[[], None]] = []
    builder = _Operations(spec, ops, finalizers)
    _get(api.annotations, Title, lambda v: info.__setitem__("title", v))
    _get(api.annotations, Version, lambda v: info.__setitem__("version", v))
    _get(api.annotations, Description, lambda v: info.__setitem__("description", v))
    _get(api.annotations, License, lambda v: info.__setitem__("license", copy.deepcopy(v)))
    _get(api.annotations, Summary, lambda v: info.__setitem__("summary", v))
    _get(api.annotations, Servers, lambda v: spec.__setitem__("servers", copy.deepcopy(list(v))))
    reflect(api, on_group=lambda g, _a: _on_group(spec, g), on_endpoint=builder.add)
    components: Json = spec["components"]["schemas"]
    for schema in api.annotations.get_or_else(AdditionalSchemas, tuple):
        identifier = (schema.__codec__().ast.resolve() or {}).get("identifier")
        if isinstance(identifier, str):
            if identifier in components:
                raise ValueError(f"Duplicate component schema identifier: {identifier}")
            components[identifier] = ops.schema(schema.__codec__().ast)
    ops.compile(components, include, policy)
    for finalize in finalizers:
        finalize()
    for key in components:
        if not VALID_OPEN_API_COMPONENTS_SCHEMAS_KEY_REGEXP.match(key):
            raise ValueError(f"Invalid component schema key: {key}")
    _get(api.annotations, Override, lambda v: spec.update(copy.deepcopy(dict(v))))
    transform = api.annotations.get_option(Transform)
    return spec if transform is None else transform.value(spec)


def _tag_name(group: AnyGroup) -> str:
    return group.annotations.get_or_else(Title, lambda: group.identifier)


def _on_group(spec: Json, group: AnyGroup) -> None:
    if group.annotations.get(Exclude):
        return
    tag: Json = {"name": _tag_name(group)}
    _get(group.annotations, Description, lambda v: tag.__setitem__("description", v))
    _get(group.annotations, ExternalDocs, lambda v: tag.__setitem__("externalDocs", dict(v)))
    _get(group.annotations, Override, lambda v: tag.update(copy.deepcopy(dict(v))))
    transform = group.annotations.get_option(Transform)
    spec["tags"].append(tag if transform is None else transform.value(tag))


class _Operations:
    """Adds each endpoint's operation to the document."""

    def __init__(self, spec: Json, ops: SchemaOps, finalizers: list[Callable[[], None]]) -> None:
        self.spec = spec
        self.ops = ops
        self.finalizers = finalizers
        self.path_operations: set[str] = set()
        self.operation_ids: set[str] = set()

    def add(self, reflected: ReflectedEndpoint) -> None:
        if reflected.merged_annotations.get(Exclude):
            return
        group, endpoint = reflected.group, reflected.endpoint
        operation_id = endpoint.annotations.get_or_else(
            Identifier,
            lambda: (
                endpoint.identifier
                if group.top_level
                else f"{group.identifier}.{endpoint.identifier}"
            ),
        )
        op: Json = {
            "tags": [_tag_name(group)],
            "operationId": operation_id,
            "parameters": [],
            "security": [],
            "responses": {},
        }
        names = _path.param_names(endpoint.params)
        path = _path.replace_params(endpoint.path, names, lambda key, _optional: f"{{{key}}}")
        method = endpoint.method.lower()
        _get(endpoint.annotations, Description, lambda v: op.__setitem__("description", v))
        _get(endpoint.annotations, Summary, lambda v: op.__setitem__("summary", v))
        _get(endpoint.annotations, Deprecated, lambda v: op.__setitem__("deprecated", v))
        _get(endpoint.annotations, ExternalDocs, lambda v: op.__setitem__("externalDocs", dict(v)))
        for middleware in reflected.middleware:
            for name, security in (middleware.security or {}).items():
                self._security_scheme(name, security)
                op["security"].append({name: []})
        body = has_body(endpoint.method)
        if body:
            self._request_body(op, endpoint)
        self._parameters(op, endpoint.params, "path")
        if not body and len(endpoint.payload) == 1:
            entry = next(iter(endpoint.payload.values()))
            first = entry.schemas[0] if isinstance(entry, BufferedPayload) else entry.schema
            self._parameters(op, first, "query")
        self._parameters(op, endpoint.headers, "header")
        self._parameters(op, endpoint.query, "query")
        response_bodies(op, self.ops, endpoint)
        self._register(op, endpoint, path, method)

    def _register(self, op: Json, endpoint: AnyEndpoint, path: str, method: str) -> None:
        is_query = method == "query"
        key = "QUERY" if is_query else method
        normalized = f"{method} {_PATH_PARAM.sub('{}', path)}"
        if normalized in self.path_operations:
            raise ValueError(f"Duplicate OpenAPI operation for {endpoint.method} {path}")
        self.path_operations.add(normalized)
        item: Json = self.spec["paths"].setdefault(path, {})
        operations: Json = item.setdefault("x-oai-additionalOperations", {}) if is_query else item
        operations[key] = op

        def finalize() -> None:
            final = operations[key]
            _get(endpoint.annotations, Override, lambda v: final.update(copy.deepcopy(dict(v))))
            transform = endpoint.annotations.get_option(Transform)
            if transform is not None:
                final = transform.value(final)
            operation_id = final.get("operationId")
            if operation_id is not None:
                if operation_id in self.operation_ids:
                    raise ValueError(f"Duplicate OpenAPI operationId: {operation_id}")
                self.operation_ids.add(operation_id)
            operations[key] = final

        self.finalizers.append(finalize)

    def _security_scheme(self, name: str, security: HttpApiSecurity) -> None:
        scheme = _security_scheme(security)
        schemes: Json = self.spec["components"]["securitySchemes"]
        existing = schemes.get(name)
        if existing is None:
            schemes[name] = scheme
        elif _comparable(existing) != _comparable(scheme):
            raise ValueError(f"Conflicting OpenAPI security scheme: {name}")

    def _request_body(self, op: Json, endpoint: AnyEndpoint) -> None:
        by_content_type: dict[str, tuple[str, list[Top]] | api_schema.StreamSchema] = {}
        for schema in payload_schemas(endpoint):
            if api_schema.is_stream_schema(schema):
                by_content_type[schema.content_type] = schema
                continue
            if api_schema.is_no_content(schema.__codec__().ast):
                continue
            encoding = api_schema.get_payload_encoding(schema.__codec__().ast, endpoint.method)
            tag = (
                "Multipart" if isinstance(encoding, api_schema.MultipartEncoding) else encoding.tag
            )
            existing = by_content_type.get(encoding.content_type)
            if existing is None:
                by_content_type[encoding.content_type] = (tag, [schema])
            elif isinstance(existing, tuple):
                existing[1].append(schema)
        if not by_content_type:
            return
        content: Json = {}
        for content_type, entry in by_content_type.items():
            if not isinstance(entry, tuple):
                content[content_type] = stream_media_type(self.ops, entry)
                continue
            tag, schemas = entry
            content[content_type] = {"schema": self.ops.schema(_union(schemas), tag)}
        op["requestBody"] = {"content": content, "required": True}

    def _parameters(self, op: Json, schema: Top | None, location: str) -> None:
        if schema is None:
            return

        def apply(name: str, optional: bool, json: Json) -> None:
            op["parameters"].append(
                {
                    "name": name,
                    "in": location,
                    "schema": json,
                    "required": location == "path" or not optional,
                }
            )

        self.ops.properties(schema.__codec__().ast, apply)


def _union(schemas: list[Top]) -> ast.AST:
    nodes = tuple(s.__codec__().ast for s in schemas)
    return nodes[0] if len(nodes) == 1 else ast.Union(nodes)


def _security_scheme(security: HttpApiSecurity) -> Json:
    meta: Json = {}
    _get(security.annotations, Description, lambda v: meta.__setitem__("description", v))
    match security:
        case Basic():
            return {**meta, "type": "http", "scheme": "basic"}
        case Http():
            scheme: Json = {**meta, "type": "http", "scheme": security.scheme}
            _get(security.annotations, Format, lambda v: scheme.__setitem__("bearerFormat", v))
            return scheme
        case ApiKey():
            return {**meta, "type": "apiKey", "name": security.key, "in": security.in_}


def _comparable(scheme: Json) -> Json:
    if scheme["type"] == "http":
        return {**scheme, "scheme": scheme["scheme"].lower()}
    if scheme["in"] == "header":
        return {**scheme, "name": scheme["name"].lower()}
    return scheme


__all__ = [
    "AnnotationOptions",
    "Deprecated",
    "Description",
    "Exclude",
    "ExternalDocs",
    "Format",
    "FromApiOptions",
    "Identifier",
    "License",
    "Override",
    "Servers",
    "Summary",
    "Title",
    "Transform",
    "Version",
    "annotations",
    "from_api",
]
