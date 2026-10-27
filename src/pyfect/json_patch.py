"""JSON Patch (RFC 6902) restricted to ``add``, ``remove`` and ``replace``
(Effect's ``JsonPatch``): ``get`` computes a patch between two JSON values,
``apply`` runs one without mutating its input::

    patch = json_patch.get({"a": 1}, {"a": 2, "b": [1]})
    # [{"op": "replace", "path": "/a", "value": 2}, {"op": "add", "path": "/b", "value": [1]}]
    json_patch.apply(patch, {"a": 1})  # {"a": 2, "b": [1]}

Arrays are lists or tuples and objects string-keyed mappings on the way in;
``apply`` builds new lists and dicts along the path it changes and keeps
every other value as it is. An operation that cannot be applied raises
``ValueError`` with Effect's message.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Literal, NotRequired, TypedDict, cast

from pyfect._js import js_sort_key
from pyfect._json_value import JsonValue
from pyfect.json_pointer import escape_token, unescape_token


class AddOperation(TypedDict):
    op: Literal["add"]
    path: str
    value: JsonValue
    description: NotRequired[str]


class RemoveOperation(TypedDict):
    op: Literal["remove"]
    path: str
    description: NotRequired[str]


class ReplaceOperation(TypedDict):
    op: Literal["replace"]
    path: str
    value: JsonValue
    description: NotRequired[str]


type JsonPatchOperation = AddOperation | RemoveOperation | ReplaceOperation
type JsonPatch = Sequence[JsonPatchOperation]

type _Array = Sequence[JsonValue]
type _Object = Mapping[str, JsonValue]


def _is_array(value: object) -> bool:
    return isinstance(value, list | tuple)


def _is_object(value: object) -> bool:
    return isinstance(value, Mapping)


def _same(a: JsonValue, b: JsonValue) -> bool:
    """JavaScript's ``Object.is`` on JSON values: the same container, or
    leaves of one JSON type with one value (``True`` is not ``1``, ``-0.0``
    is not ``0``)."""
    if a is b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b and math.copysign(1, a) == math.copysign(1, b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False


def get(old_value: JsonValue, new_value: JsonValue) -> list[JsonPatchOperation]:
    """The operations turning ``old_value`` into ``new_value``: array
    elements compared by index (removals from the end first, then
    additions), object keys in JavaScript's sorted order, anything else a ``replace``."""
    patches: list[JsonPatchOperation] = []
    _get_loop(old_value, new_value, "", patches)
    return patches


def _get_loop(
    old_value: JsonValue, new_value: JsonValue, path: str, patches: list[JsonPatchOperation]
) -> None:
    if _same(old_value, new_value):
        return
    if _is_array(old_value) and _is_array(new_value):
        old = cast("_Array", old_value)
        new = cast("_Array", new_value)
        for i in range(min(len(old), len(new))):
            _get_loop(old[i], new[i], f"{path}/{i}", patches)
        patches.extend(
            RemoveOperation(op="remove", path=f"{path}/{i}")
            for i in range(len(old) - 1, len(new) - 1, -1)
        )
        patches.extend(
            AddOperation(op="add", path=f"{path}/{i}", value=new[i])
            for i in range(len(old), len(new))
        )
        return
    if _is_object(old_value) and _is_object(new_value):
        old_object = cast("_Object", old_value)
        new_object = cast("_Object", new_value)
        for key in sorted({*old_object, *new_object}, key=js_sort_key):
            key_path = f"{path}/{escape_token(key)}"
            if key in old_object and key in new_object:
                _get_loop(old_object[key], new_object[key], key_path, patches)
            elif key in new_object:
                patches.append(AddOperation(op="add", path=key_path, value=new_object[key]))
            else:
                patches.append(RemoveOperation(op="remove", path=key_path))
        return
    patches.append(ReplaceOperation(op="replace", path=path, value=new_value))


def apply(patch: JsonPatch, old_value: JsonValue) -> JsonValue:
    """``old_value`` with each operation applied in order. An empty patch
    returns ``old_value`` itself."""
    doc = old_value
    for operation in patch:
        doc = _apply_operation(doc, operation)
    return doc


def _tokenize(pointer: str) -> list[str]:
    if not pointer:
        return []
    if not pointer.startswith("/"):
        raise ValueError(f'Invalid JSON Pointer, it must start with "/": {json.dumps(pointer)}')
    return [unescape_token(token) for token in pointer.split("/")[1:]]


_ARRAY_INDEX = re.compile(r"0|[1-9][0-9]*")


def _array_index(token: str) -> int:
    if not _ARRAY_INDEX.fullmatch(token):
        raise ValueError(f'Invalid array index: "{token}"')
    return int(token)


def _not_a_container(operation: JsonPatchOperation) -> ValueError:
    return ValueError(
        f'Cannot {operation["op"]} at "{operation["path"]}" (parent not found or not a container).'
    )


def _apply_operation(doc: JsonValue, operation: JsonPatchOperation) -> JsonValue:
    path = operation["path"]
    if not path:
        if operation["op"] == "remove":
            raise ValueError("Unsupported operation at the root")
        return operation["value"]
    resolved = _resolve_parent(doc, path)
    if resolved is None:
        raise _not_a_container(operation)
    stack, parent, last_token = resolved
    if _is_array(parent):
        return _rebuild(stack, _apply_to_array(cast("_Array", parent), last_token, operation))
    if _is_object(parent):
        return _rebuild(stack, _apply_to_object(cast("_Object", parent), last_token, operation))
    raise _not_a_container(operation)


def _apply_to_array(
    parent: _Array, last_token: str, operation: JsonPatchOperation
) -> list[JsonValue]:
    if last_token == "-" and operation["op"] != "add":
        raise ValueError(f'"-" is not valid for {operation["op"]} at "{operation["path"]}".')
    index = len(parent) if last_token == "-" else _array_index(last_token)
    max_index = len(parent) if operation["op"] == "add" else len(parent) - 1
    if index > max_index:
        raise ValueError(f'Array index out of bounds at "{operation["path"]}".')
    updated = list(parent)
    if operation["op"] == "add":
        updated.insert(index, operation["value"])
    elif operation["op"] == "remove":
        del updated[index]
    else:
        updated[index] = operation["value"]
    return updated


def _apply_to_object(
    parent: _Object, last_token: str, operation: JsonPatchOperation
) -> dict[str, JsonValue]:
    if operation["op"] != "add" and last_token not in parent:
        raise ValueError(f'Property "{last_token}" does not exist at "{operation["path"]}".')
    updated = dict(parent)
    if operation["op"] == "remove":
        del updated[last_token]
    else:
        updated[last_token] = operation["value"]
    return updated


type _Stack = list[tuple[JsonValue, int | str]]


def _resolve_parent(doc: JsonValue, pointer: str) -> tuple[_Stack, JsonValue, str] | None:
    """The containers on the way to the parent of ``pointer``, the parent and
    the last token; ``None`` when a container on the way is missing."""
    tokens = _tokenize(pointer)
    stack: _Stack = []
    current = doc
    for token in tokens[:-1]:
        if _is_array(current):
            array = cast("_Array", current)
            index = _array_index(token)
            if index >= len(array):
                return None
            stack.append((current, index))
            current = array[index]
        elif _is_object(current):
            mapping = cast("_Object", current)
            if token not in mapping:
                return None
            stack.append((current, token))
            current = mapping[token]
        else:
            return None
    return stack, current, tokens[-1]


def _rebuild(stack: _Stack, new_parent: JsonValue) -> JsonValue:
    """The document with ``new_parent`` written back through ``stack``,
    copying each container on the way."""
    acc = new_parent
    for container, token in reversed(stack):
        if isinstance(token, int):
            array = list(cast("_Array", container))
            array[token] = acc
            acc = array
        else:
            mapping = dict(cast("_Object", container))
            mapping[token] = acc
            acc = mapping
    return acc


__all__ = [
    "AddOperation",
    "JsonPatch",
    "JsonPatchOperation",
    "JsonValue",
    "RemoveOperation",
    "ReplaceOperation",
    "apply",
    "get",
]
