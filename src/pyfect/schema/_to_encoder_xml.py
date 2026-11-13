"""``to_encoder_xml``: a value as XML text, through its string tree (Effect's
``Schema.toEncoderXml``)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pyfect._core import Effect
from pyfect._js import js_number
from pyfect.schema._error import SchemaError
from pyfect.schema._parse import encode_effect
from pyfect.schema._schema import Codec
from pyfect.schema._to_codec_string_tree import to_codec_string_tree


def to_encoder_xml[T, E, RD, RE](
    codec: Codec[T, E, RD, RE],
    /,
    *,
    root_name: str | None = None,
    array_item_name: str = "item",
    pretty: bool = True,
    indent: str = "  ",
    sort_keys: bool = True,
) -> Callable[[T], Effect[str, SchemaError, RE]]:
    """A function from a value to its XML text. The root is ``root_name``, else the schema's
    identifier or title, else ``root``. A declaration with no codec is a ``ValueError``."""
    resolved = codec.__codec__().ast.resolve() or {}
    name = root_name or resolved.get("identifier") or resolved.get("title") or "root"
    options = _Options(array_item_name, pretty, indent, sort_keys)
    serialize: Callable[[T], Effect[Any, SchemaError, RE]] = encode_effect(
        to_codec_string_tree(codec)
    )
    return lambda value: serialize(value).map(lambda tree: _to_xml(str(name), tree, options))


@dataclass(frozen=True, slots=True)
class _Options:
    array_item_name: str
    pretty: bool
    indent: str
    sort_keys: bool


def _to_xml(root_name: str, tree: object, options: _Options) -> str:
    writer = _XmlWriter(options)
    writer.recur(root_name, tree, 0, None)
    return ("\n" if options.pretty else "").join(writer.lines)


class _XmlWriter:
    __slots__ = ("lines", "options", "seen")

    def __init__(self, options: _Options) -> None:
        self.options = options
        self.lines: list[str] = []
        self.seen: set[int] = set()

    def push(self, depth: int, text: str) -> None:
        options = self.options
        self.lines.append(options.indent * depth + text if options.pretty else text)

    def container(
        self,
        tag: str,
        attrs: str,
        depth: int,
        node: object,
        children: Sequence[tuple[str, object, str]],
    ) -> None:
        if id(node) in self.seen:
            raise ValueError("Cycle detected while serializing to XML.")
        if not children:
            self.push(depth, f"<{tag}{attrs}/>")
            return
        self.seen.add(id(node))
        self.push(depth, f"<{tag}{attrs}>")
        for child_name, child, original in children:
            self.recur(child_name, child, depth + 1, original)
        self.push(depth, f"</{tag}>")
        self.seen.discard(id(node))

    def recur(self, name: str, node: object, depth: int, original: str | None) -> None:
        tag, attrs = _tag_info(name, original)
        match node:
            case None:
                self.push(depth, f"<{tag}{attrs}/>")
            case str():
                self.push(depth, f"<{tag}{attrs}>{_escape_text(node)}</{tag}>")
            case Mapping():
                entries = cast("Mapping[str, object]", node)
                keys = sorted(entries) if self.options.sort_keys else list(entries)
                children = [(_safe_name(key), entries[key], key) for key in keys]
                self.container(tag, attrs, depth, entries, children)
            case list() | tuple():
                items = cast("Sequence[object]", node)
                item = self.options.array_item_name
                self.container(tag, attrs, depth, items, [(item, value, item) for value in items])
            case _:
                self.push(depth, f"<{tag}{attrs}>{_escape_text(_format(node))}</{tag}>")


def _format(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return js_number(value) if isinstance(value, (int, float)) else str(value)


def _escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attribute(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _safe_name(name: str) -> str:
    safe = name if re.match(r"[A-Za-z_]", name) else "_" + name
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", safe)
    return "_" + safe if re.match(r"xml", safe, re.IGNORECASE) else safe


def _tag_info(name: str, original: str | None) -> tuple[str, str]:
    safe = _safe_name(name)
    if safe != name or (original and original != name):
        return safe, f' data-name="{_escape_attribute(original or name)}"'
    return safe, ""
