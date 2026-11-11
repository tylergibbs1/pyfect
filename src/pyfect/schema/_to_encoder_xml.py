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
    lines: list[str] = []
    seen: set[int] = set()

    def push(depth: int, text: str) -> None:
        lines.append(options.indent * depth + text if options.pretty else text)

    def container(
        tag: str, attrs: str, depth: int, node: object, children: Sequence[tuple[str, object, str]]
    ) -> None:
        if id(node) in seen:
            raise ValueError("Cycle detected while serializing to XML.")
        if not children:
            push(depth, f"<{tag}{attrs}/>")
            return
        seen.add(id(node))
        push(depth, f"<{tag}{attrs}>")
        for child_name, child, original in children:
            recur(child_name, child, depth + 1, original)
        push(depth, f"</{tag}>")
        seen.discard(id(node))

    def recur(name: str, node: object, depth: int, original: str | None) -> None:
        tag, attrs = _tag_info(name, original)
        match node:
            case None:
                push(depth, f"<{tag}{attrs}/>")
            case str():
                push(depth, f"<{tag}{attrs}>{_escape_text(node)}</{tag}>")
            case Mapping():
                entries = cast("Mapping[str, object]", node)
                keys = sorted(entries) if options.sort_keys else list(entries)
                children = [(_safe_name(key), entries[key], key) for key in keys]
                container(tag, attrs, depth, entries, children)
            case list() | tuple():
                items = cast("Sequence[object]", node)
                item = options.array_item_name
                container(tag, attrs, depth, items, [(item, value, item) for value in items])
            case _:
                push(depth, f"<{tag}{attrs}>{_escape_text(_format(node))}</{tag}>")

    recur(root_name, tree, 0, None)
    return ("\n" if options.pretty else "").join(lines)


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
