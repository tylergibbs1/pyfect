"""``to_differ_json_patch``: diff and patch a schema's values as JSON Patch over their JSON form
(Effect's ``Schema.toDifferJsonPatch``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyfect import json_patch
from pyfect.json_patch import JsonPatch
from pyfect.schema._parse import decode_sync, encode_sync
from pyfect.schema._schema import Codec
from pyfect.schema._to_codec_json import to_codec_json


@dataclass(frozen=True, slots=True)
class Differ[V, P]:
    """Effect's ``Differ``: how values of ``V`` differ, as patches of type ``P``."""

    empty: P
    diff: Callable[[V, V], P]
    combine: Callable[[P, P], P]
    patch: Callable[[V, P], V]


def to_differ_json_patch[T, E](schema: Codec[T, E, object, object], /) -> Differ[T, JsonPatch]:
    """A patch that changes nothing returns the old value itself. Patching decodes through
    ``schema``'s JSON form, so a value it refuses raises ``SchemaError``."""
    serializer: Any = to_codec_json(schema)
    get = encode_sync(serializer)
    set_ = decode_sync(serializer)

    def patch(old_value: T, patch: JsonPatch) -> T:
        value = get(old_value)
        patched = json_patch.apply(patch, value)
        return old_value if patched is value else set_(patched)

    return Differ(
        empty=[],
        diff=lambda old_value, new_value: json_patch.get(get(old_value), get(new_value)),
        combine=lambda first, second: [*first, *second],
        patch=patch,
    )
