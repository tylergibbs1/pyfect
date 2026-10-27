"""The conversion kernel: walks a schema with a dialect adapter, tracks
schema resources (``$id``) and relocates ``$ref`` pointers to where their
targets end up in the converted document.

An adapter decides which keywords hold subschemas and converts them through
the ``Context`` it is given; the kernel records where each source location
lands, so that once the walk is done every reference pointing into the
source can be rewritten to point into the target.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast
from urllib.parse import quote, urldefrag, urljoin, urlsplit, urlunsplit

from pyfect._url import parse_url
from pyfect.json_pointer import format_uri_fragment, parse_uri_fragment
from pyfect.json_schema._model import (
    JsonSchema,
    as_array,
    as_object,
    creates_resource,
    is_array,
    is_object,
    map_object,
)

type Path = Sequence[str]

ROOT_URI = "https://effect.invalid/.json-schema/"

# WHATWG's fragment and path percent-encode sets, as ``quote`` safe characters.
_PRINTABLE = "".join(chr(c) for c in range(0x21, 0x7F))
_FRAGMENT_SAFE = "".join(c for c in _PRINTABLE if c not in '"<>`')
_PATH_SAFE = "".join(c for c in _FRAGMENT_SAFE if c not in "#?{}")


@dataclass(frozen=True, slots=True)
class _Url:
    href: str
    """Without its fragment."""
    hash: str
    """``"#..."``, or ``""`` for no or an empty fragment (WHATWG's ``hash``)."""


def _resolve_url(value: str, base: str) -> _Url | None:
    """``new URL(value, base)``: ``None`` when it cannot be parsed."""
    if any(ch in "\t\n\r" for ch in value):
        value = "".join(ch for ch in value if ch not in "\t\n\r")
    joined = urljoin(base, value.strip(" \x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f"))
    without_fragment, fragment = urldefrag(joined)
    parts = urlsplit(without_fragment)
    href = urlunsplit(
        parts._replace(
            scheme=parts.scheme.lower(),
            netloc=_normalize_netloc(parts.scheme.lower(), parts.netloc),
            path=quote(parts.path, safe=_PATH_SAFE),
        )
    )
    if parse_url(href) is None:
        return None
    encoded = quote(fragment, safe=_FRAGMENT_SAFE)
    return _Url(href, f"#{encoded}" if encoded else "")


_DEFAULT_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443", "ftp": "21"}


def _normalize_netloc(scheme: str, netloc: str) -> str:
    """The host lowercased and a default port dropped, as WHATWG does."""
    userinfo, at, hostport = netloc.rpartition("@")
    host, port = hostport, ""
    if not hostport.endswith("]"):
        head, colon, tail = hostport.rpartition(":")
        if colon:
            host, port = head, tail
    if port == _DEFAULT_PORTS.get(scheme):
        port = ""
    return f"{userinfo}{at}{host.lower()}{':' + port if port else ''}"


def resolve_resource_uri(value: object, base: str) -> str | None:
    if not isinstance(value, str):
        return None
    url = _resolve_url(value, base)
    return None if url is None else url.href


def _relocate_reference(reference: str, target_path: Path) -> str:
    index = reference.find("#")
    if index == -1 and len(target_path) == 0:
        return reference
    uri = reference if index == -1 else reference[:index]
    return f"{uri}{format_uri_fragment(target_path)}"


def _location_key(resource: str, pointer: Path) -> str:
    return f"{resource}\x00{json.dumps(list(pointer), ensure_ascii=False)}"


@dataclass(frozen=True, slots=True)
class _ResourceScope:
    parent: _ResourceScope | None
    source_root: Path
    target_root: Path
    uri: str


class Context:
    """What an adapter converts a node's subschemas with."""

    __slots__ = ("_converter", "_scope", "_source_path", "_target_path", "is_document_root")

    def __init__(
        self, converter: Converter, source_path: Path, target_path: Path, scope: _ResourceScope
    ) -> None:
        self._converter = converter
        self._source_path = source_path
        self._target_path = target_path
        self._scope = scope
        self.is_document_root = len(source_path) == 0

    def schema(self, value: object, source_key: str, target_key: str | None = None) -> object:
        """The subschema under ``source_key``, landing under ``target_key``."""
        target = source_key if target_key is None else target_key
        return self.schema_at(value, [source_key], [target])

    def schema_at(self, value: object, source_suffix: Path, target_suffix: Path) -> object:
        return self._converter.loop(
            value,
            [*self._source_path, *source_suffix],
            [*self._target_path, *target_suffix],
            self._scope,
        )

    def schema_array(self, value: object, source_key: str, target_key: str | None = None) -> object:
        """Each subschema of the array under ``source_key``."""
        if not is_array(value):
            return value
        target = source_key if target_key is None else target_key
        return [
            self.schema_at(item, [source_key, str(index)], [target, str(index)])
            for index, item in enumerate(as_array(value))
        ]

    def schema_map(self, value: object, source_key: str, target_key: str | None = None) -> object:
        """Each subschema of the object under ``source_key``."""
        if not is_object(value):
            return value
        target = source_key if target_key is None else target_key
        return map_object(
            as_object(value),
            lambda item, key: self.schema_at(item, [source_key, key], [target, key]),
        )

    def reference(self, out: JsonSchema, value: object) -> None:
        """Set ``out["$ref"]`` to ``value``, relocated once the walk is done."""
        if isinstance(value, str):
            self._converter.references.append((out, value, self._scope.uri))
        else:
            out["$ref"] = value


type Adapter = Callable[[JsonSchema, Context], JsonSchema]


class Converter:
    """One conversion: call ``convert`` on each root, then ``finish``."""

    def __init__(
        self,
        adapter: Adapter,
        *,
        boolean_adapter: Callable[[bool], object] | None = None,
        track_ids: bool = False,
        ignore_ref_siblings: bool = False,
    ) -> None:
        self._adapter = adapter
        self._boolean_adapter = boolean_adapter
        self._track_ids = track_ids
        self._ignore_ref_siblings = ignore_ref_siblings
        self._locations: dict[str, Path] = {}
        self.references: list[tuple[JsonSchema, str, str]] = []
        self._root_uri = ROOT_URI

    def convert(self, root: object, source_path: Path = (), target_path: Path = ()) -> object:
        if len(source_path) == 0 and self._track_ids:
            identifier = self._resource_id(as_object(root)) if is_object(root) else None
            self._root_uri = resolve_resource_uri(identifier, ROOT_URI) or ROOT_URI
        return self.loop(
            root, source_path, target_path, _ResourceScope(None, (), (), self._root_uri)
        )

    def finish(self) -> None:
        """Write every pending ``$ref``, pointing into the target when its
        source location was converted."""
        for out, value, source_resource in self.references:
            reference = value
            resolved = _resolve_url(value, source_resource)
            if resolved is not None:
                pointer = parse_uri_fragment(resolved.hash)
                if pointer is not None:
                    target = self._locations.get(_location_key(resolved.href, pointer))
                    if target is not None:
                        reference = _relocate_reference(value, target)
            out["$ref"] = reference

    def loop(
        self, node: object, source_path: Path, target_path: Path, scope: _ResourceScope
    ) -> object:
        if isinstance(node, bool):
            self._record_locations(source_path, target_path, scope)
            if self._boolean_adapter is None:
                return node
            return self._boolean_adapter(node)
        if not is_object(node):
            return node
        source = cast("JsonSchema", node)
        current = scope
        identifier = self._resource_id(source)
        if len(source_path) > 0 and self._track_ids and creates_resource(identifier):
            uri = resolve_resource_uri(identifier, scope.uri)
            if uri is not None:
                current = _ResourceScope(scope, source_path, target_path, uri)
        self._record_locations(source_path, target_path, current)
        return self._adapter(source, Context(self, source_path, target_path, current))

    def _resource_id(self, schema: object) -> object:
        source = as_object(schema)
        if self._ignore_ref_siblings and isinstance(source.get("$ref"), str):
            return None
        return source.get("$id")

    def _record_locations(
        self, source_path: Path, target_path: Path, scope: _ResourceScope
    ) -> None:
        # A JSON Pointer can address an embedded schema from any containing resource.
        if scope.parent is not None:
            self._record_locations(source_path, target_path, scope.parent)
        self._locations[_location_key(scope.uri, source_path[len(scope.source_root) :])] = (
            target_path[len(scope.target_root) :]
        )


def convert_schema(
    root: JsonSchema,
    adapter: Adapter,
    *,
    track_ids: bool = False,
    ignore_ref_siblings: bool = False,
) -> JsonSchema:
    converter = Converter(adapter, track_ids=track_ids, ignore_ref_siblings=ignore_ref_siblings)
    out = converter.convert(root)
    converter.finish()
    return cast("JsonSchema", out)
