"""Reading a batched response back into one result per slice, and the
helpers resolvers use to compare keys and walk results."""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from pyfect import _json_text
from pyfect.graphql._types import ExecutionResult
from pyfect.graphql.client_error import GraphQLError
from pyfect.graphql.template import DocumentTemplate


def canonical_json(value: object) -> str:
    """JSON with object keys sorted, so equal JSON values give equal
    strings."""
    return _json_text.stringify(value, sort_keys=True, default=str)


def frozen(value: object) -> Hashable:
    """``value`` as a hashable stand-in that is equal for equal values:
    mappings and sequences compare by content."""
    if isinstance(value, Mapping):
        items = cast("Mapping[object, object]", value).items()
        return ("mapping", frozenset((frozen(k), frozen(v)) for k, v in items))
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(frozen(item) for item in cast("Sequence[object]", value)))
    if isinstance(value, (set, frozenset)):
        return ("set", frozenset(frozen(item) for item in cast("set[object]", value)))
    return cast("Hashable", value)


def split_slices(
    result: ExecutionResult, template: DocumentTemplate, prefixes: Sequence[str]
) -> list[ExecutionResult] | None:
    """The batched ``result`` split per prefix, with the prefix removed
    from root keys and error paths. ``None`` if an error matches no slice
    or the data is null or missing."""
    slice_errors: list[list[GraphQLError]] = [[] for _ in prefixes]
    for error in result.errors:
        path = error.get("path")
        key = path[0] if path else None
        # No prefix is a prefix of another, so at most one matches.
        index = (
            next((i for i, prefix in enumerate(prefixes) if key.startswith(prefix)), None)
            if isinstance(key, str)
            else None
        )
        if index is None or path is None or not isinstance(key, str):
            return None
        unprefixed: Any = {**error, "path": [key[len(prefixes[index]) :], *path[1:]]}
        slice_errors[index].append(unprefixed)
    data = result.data
    if not isinstance(data, Mapping):
        return None
    data = cast("Mapping[str, object]", data)
    sliced: list[ExecutionResult] = []
    for prefix, errors in zip(prefixes, slice_errors, strict=True):
        slice_data: dict[str, object] = {}
        for selection in template.selections:
            key = cast("str", selection.alias or selection.name)
            if prefix + key in data:
                slice_data[key] = data[prefix + key]
        sliced.append(replace(result, data=slice_data, errors=tuple(errors)))
    return sliced


@dataclass(frozen=True, slots=True)
class FoundList:
    """The list at a resolver's path, and whether its parent's
    ``pageInfo.hasNextPage`` says there are more."""

    items: Sequence[object]
    truncated: bool


def _field(value: object, name: str) -> object:
    return cast("Mapping[str, object]", value).get(name) if isinstance(value, Mapping) else None


def find_list(data: object, path: Sequence[str]) -> FoundList | None:
    """The list at ``path`` in ``data``, or ``None`` when a field on the
    way is null or missing."""
    parent = data
    for name in path[:-1]:
        parent = _field(parent, name)
    items = _field(parent, path[-1])
    if not isinstance(items, (list, tuple)):
        return None
    page_info = _field(parent, "pageInfo")
    return FoundList(
        items=cast("Sequence[object]", items),
        truncated=_field(page_info, "hasNextPage") is True,
    )


def entry_index(error: GraphQLError, path: Sequence[str], length: int) -> int | None:
    """The entry an error at ``[*path, i]`` belongs to, if it is one of
    ``length`` entries."""
    error_path = error.get("path")
    if error_path is None or len(error_path) <= len(path):
        return None
    if any(error_path[i] != name for i, name in enumerate(path)):
        return None
    index = error_path[len(path)]
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    return index if 0 <= index < length else None
