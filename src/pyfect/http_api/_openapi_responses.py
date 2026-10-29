"""An operation's ``responses`` (Effect's ``OpenApi`` response bodies):
for each status its description, headers and content by media type."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pyfect import schema as S
from pyfect.http_api import schema as api_schema
from pyfect.http_api._openapi_schemas import SchemaOps
from pyfect.http_api.endpoint import AnyEndpoint, error_schemas, success_schemas
from pyfect.schema import Top, ast

type Json = dict[str, Any]


@dataclass(slots=True)
class _Body:
    descriptions: list[str] = field(default_factory=list[str])
    content: dict[str, dict[str, list[Top]]] | None = None
    """Schemas by encoding tag, then content type."""
    headers: list[Top] = field(default_factory=list[Top])
    streams: dict[str, api_schema.StreamSchema] | None = None

    def describe(self, description: str | None) -> None:
        if description is not None and description not in self.descriptions:
            self.descriptions.append(description)


def response_bodies(op: Json, ops: SchemaOps, endpoint: AnyEndpoint) -> None:
    successes = _bodies(success_schemas(endpoint), api_schema.get_status_success_schema)
    _process(op, ops, successes, "Success")
    errors = _bodies(error_schemas(endpoint), api_schema.get_status_error_schema)
    _process(op, ops, errors, "Error")


def _description(node: ast.AST) -> str | None:
    annotations = node.resolve() or {}
    for key in ("description", "identifier"):
        value = annotations.get(key)
        if isinstance(value, str):
            return value
    return None


def _upgrade_headers(protocol: str) -> Top:
    return S.Bottom(
        ast.Objects(
            (
                ast.PropertySignature("connection", ast.Literal("Upgrade")),
                ast.PropertySignature("upgrade", ast.Literal(protocol)),
            )
        )
    )


def _parts(schema: Top) -> tuple[Top, Top | None]:
    """The body and headers schemas of a response schema."""
    if api_schema.is_with_headers(schema):
        return schema.schema, schema.headers
    annotation = api_schema.get_with_headers_annotation(schema.__codec__().ast)
    if annotation is not None:
        return annotation.body, annotation.headers_codec
    return schema, None


def _bodies(schemas: tuple[Top, ...], get_status: Callable[[Top], int]) -> dict[int, _Body]:
    bodies: dict[int, _Body] = {}
    for schema in schemas:
        body, headers = _parts(schema)
        status = get_status(schema)
        body_node = body.__codec__().ast
        if api_schema.is_upgrade(body):
            entry = _no_content(bodies, status, _description(body_node) or "Switching Protocols")
            entry.headers.append(_upgrade_headers(body.protocol))
            if body.headers is not None:
                entry.headers.append(body.headers)
        elif api_schema.is_stream_schema(body):
            entry = bodies.setdefault(status, _Body())
            entry.streams = {**(entry.streams or {}), body.content_type: body}
        elif api_schema.is_no_content(body_node):
            node = schema.__codec__().ast
            description = _description(node) or _description(body_node) or "<No Content>"
            _no_content(bodies, status, description)
        else:
            _add_content(bodies.setdefault(status, _Body()), schema, body)
        if headers is not None:
            bodies[status].headers.append(headers)
    return bodies


def _add_content(entry: _Body, schema: Top, body: Top) -> None:
    encoding = api_schema.get_response_encoding_schema(schema)
    entry.describe(_description(schema.__codec__().ast) or _description(body.__codec__().ast))
    if entry.content is None:
        entry.content = {}
    listed = entry.content.setdefault(encoding.tag, {}).setdefault(encoding.content_type, [])
    if all(s is not body for s in listed):
        listed.append(body)


def _no_content(bodies: dict[int, _Body], status: int, description: str) -> _Body:
    entry = bodies.get(status)
    if entry is None:
        entry = bodies[status] = _Body(descriptions=[description])
    else:
        entry.describe(description)
    return entry


def _process(op: Json, ops: SchemaOps, bodies: dict[int, _Body], default: str) -> None:
    responses: Json = op["responses"]
    for status, entry in bodies.items():
        key = str(status)
        response: Json = {
            "description": " | ".join(entry.descriptions) if entry.descriptions else default
        }
        responses[key] = response
        for headers in entry.headers:

            def apply(name: str, optional: bool, schema: Json, response: Json = response) -> None:
                response.setdefault("headers", {})[name.lower()] = {
                    "schema": schema,
                    "required": not optional,
                }

            ops.properties(
                headers.__codec__().ast, apply, select=lambda name: name.lower() != "content-type"
            )
        for tag, by_type in (entry.content or {}).items():
            for content_type, schemas in by_type.items():
                nodes = tuple(s.__codec__().ast for s in schemas)
                node = nodes[0] if len(nodes) == 1 else ast.Union(nodes)
                response.setdefault("content", {})[content_type] = {"schema": ops.schema(node, tag)}
        for content_type, stream in (entry.streams or {}).items():
            response.setdefault("content", {})[content_type] = stream_media_type(ops, stream)


def stream_media_type(ops: SchemaOps, stream: api_schema.StreamSchema) -> Json:
    if isinstance(stream, api_schema.StreamSseSchema):
        return {
            "schema": ops.schema(stream.events.__codec__().ast),
            "x-effect-stream": {
                "encoding": "sse",
                "causeSchema": ops.schema(S.Cause(stream.error, S.Defect()).__codec__().ast),
                "errorSchema": ops.schema(stream.error.__codec__().ast),
                "failureEvent": api_schema.RESERVED_STREAM_FAILURE_EVENT,
            },
        }
    if isinstance(stream, api_schema.StreamNdjsonSchema):
        # Each line is one element, so the media type documents the element schema.
        return {
            "schema": ops.schema(stream.schema.__codec__().ast),
            "x-effect-stream": {"encoding": "ndjson"},
        }
    return {
        "schema": {"type": "string", "format": "binary"},
        "x-effect-stream": {"encoding": "uint8array"},
    }


__all__ = ["response_bodies", "stream_media_type"]
