"""msgspec structs as pyfect schemas. Needs the ``msgspec`` extra
(``pyfect-dev[msgspec]``).

``from_struct(Item)`` is a pyfect schema of the struct: it decodes JSON
values with ``msgspec.convert`` and encodes with ``msgspec.to_builtins``, so
it composes with the rest of a schema (``S.Array(from_struct(Item))``,
``S.to_codec_json``, ``config.schema``) and fails with a pyfect issue at the
path msgspec reports (msgspec stops at the first error)::

    import msgspec

    from pyfect import msgspec as M
    from pyfect import schema as S

    class Item(msgspec.Struct):
        sku: str
        qty: int

    items = S.decode_unknown_sync(S.Array(M.from_struct(Item)))([{"sku": "a", "qty": 1}])
"""

from __future__ import annotations

import re
from typing import cast

from pyfect._extras import missing_extra

try:
    import msgspec
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.msgspec", "msgspec") from error

from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema import Bottom, Json, JsonValue, ParseOptions, decode_to, instance_of
from pyfect.schema import transformation as T
from pyfect.schema.issue import InvalidValue, Issue, MissingKey, Path, Pointer

__all__ = ["from_struct"]


def from_struct[S: msgspec.Struct](
    struct: type[S], /, *, strict: bool = True
) -> Bottom[S, JsonValue]:
    """``struct`` as a pyfect schema: decodes a JSON value with
    ``msgspec.convert(value, struct, strict=strict)`` (``strict=False``
    also reads numbers and booleans from strings), encodes with
    ``msgspec.to_builtins``."""

    def decode(input: JsonValue, _options: ParseOptions) -> Exit[S, Issue]:
        try:
            return Success(msgspec.convert(input, struct, strict=strict))
        except msgspec.ValidationError as error:
            return fail_exit(_issue_of(error))

    def encode(value: S, _options: ParseOptions) -> Exit[JsonValue, Issue]:
        return Success(cast("JsonValue", msgspec.to_builtins(value)))

    target = instance_of(struct)
    return Json.pipe(decode_to(target, T.transform_effect(decode=decode, encode=encode)))


_LOCATED = re.compile(r"^(?P<message>.*) - at `\$(?P<path>[^`]*)`$", re.DOTALL)
_MISSING = re.compile(r"^Object missing required field `(?P<field>[^`]*)`$")
_SEGMENT = re.compile(r"\.(?P<key>[^.\[]+)|\[(?P<index>\d+)\]|\[(?P<quoted>\"[^\"]*\")\]")


def _issue_of(error: msgspec.ValidationError) -> Issue:
    """The pyfect issue of a msgspec validation error: its message at its
    path, ``Missing key`` for a missing field."""
    text = str(error)
    path: Path = ()
    located = _LOCATED.match(text)
    if located is not None:
        text = located["message"]
        path = _path_of(located["path"])
    missing = _MISSING.match(text)
    if missing is not None:
        return Pointer((*path, missing["field"]), MissingKey())
    leaf = InvalidValue({"message": text})
    return Pointer(path, leaf) if path else leaf


def _path_of(text: str) -> Path:
    path: list[str | int] = []
    for segment in _SEGMENT.finditer(text):
        if segment["index"] is not None:
            path.append(int(segment["index"]))
        elif segment["quoted"] is not None:
            path.append(segment["quoted"][1:-1])
        else:
            path.append(segment["key"])
    return tuple(path)
