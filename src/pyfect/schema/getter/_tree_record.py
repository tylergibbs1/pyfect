"""Bracket paths (Effect's ``makeTreeRecord`` / ``collectBracketPathEntries``):
flat ``(path, value)`` entries, as form fields and query strings carry
them, to a nested tree and back::

    make_tree_record([("user[name]", "Al"), ("user[tags][]", "a")])
    # {"user": {"name": "Al", "tags": ["a"]}}

``"a[b]"`` and ``"a.b"`` are a key, ``"a[0]"`` an index (a canonical array
index below 2**32 - 1, else a key), ``"a[]"`` the next index; a repeated
path collects its values in a list; a later path needing a different
container replaces what was there. An indexed container becomes a list
(``None`` in its holes) only with at most 20 holes, else a dict keyed by
the index text, so ``a[4294967294]`` cannot make a huge list.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeIs, cast

from pyfect._digits import parse_digits

if TYPE_CHECKING:
    from pyfect.schema._tree import TreeValue

_MAX_ARRAY_HOLES = 20
_MAX_INDEX = 2**32 - 1
_BRACKETS = re.compile("\\[([^\\]\r\n\u2028\u2029]*)(\\])?")
"""A bracket and what follows up to its closing bracket or a line terminator (JavaScript's),
so an unmatched run is consumed once rather than scanned again for each bracket."""


def _replace_bracket(match: re.Match[str]) -> str:
    return f".{match[1]}" if match[2] is not None else match[0]


type _Token = str | int


def _is_index(part: str) -> bool:
    value = parse_digits(part, unpadded=True)
    return value is not None and value < _MAX_INDEX


def _tokens(path: str) -> list[_Token]:
    if path == "":
        return [""]
    replaced = _BRACKETS.sub(_replace_bracket, path)
    parts = replaced.split(".")[1 if replaced.startswith(".") else 0 :]
    return [int(part) if _is_index(part) else part for part in parts]


@dataclass(slots=True)
class _Indexed:
    parent: dict[_Token, object]
    key: _Token
    length: int = 0


class _Builder:
    def __init__(self) -> None:
        self.out: dict[_Token, object] = {}
        # Keyed by id(); ``made`` keeps each container alive so ids stay unique.
        self.made: list[object] = []
        self.containers: set[int] = set()
        self.duplicates: set[int] = set()
        self.indexed: dict[int, tuple[dict[_Token, object], _Indexed]] = {}

    def _state(self, value: object) -> _Indexed | None:
        found = self.indexed.get(id(value))
        return None if found is None or found[0] is not value else found[1]

    def add(self, path: str, value: object) -> None:
        tokens = _tokens(path)
        cur = self.out
        for i, raw in enumerate(tokens):
            state = self._state(cur)
            token: _Token = state.length if raw == "" and state is not None else raw
            if state is not None and isinstance(token, int):
                state.length = max(state.length, token + 1)
            if state is None and isinstance(token, int):
                token = str(token)
            has = token in cur
            current = cur.get(token)
            if i == len(tokens) - 1:
                self._leaf(cur, token, current, has=has, value=value)
            else:
                cur = self._descend(cur, token, current, array=_is_array_token(tokens[i + 1]))

    def _leaf(
        self, cur: dict[_Token, object], token: _Token, current: object, *, has: bool, value: object
    ) -> None:
        current_state = self._state(current)
        if current_state is not None:
            cast("dict[_Token, object]", current)[current_state.length] = value
            current_state.length += 1
        elif id(current) in self.duplicates and isinstance(current, list):
            cast("list[object]", current).append(value)
        elif has:
            values: list[object] = [current, value]
            self.made.append(values)
            self.duplicates.add(id(values))
            cur[token] = values
        else:
            cur[token] = value

    def _descend(
        self, cur: dict[_Token, object], token: _Token, current: object, *, array: bool
    ) -> dict[_Token, object]:
        if id(current) in self.containers and (self._state(current) is not None) == array:
            return cast("dict[_Token, object]", current)
        container: dict[_Token, object] = {}
        self.made.append(container)
        self.containers.add(id(container))
        if array:
            self.indexed[id(container)] = (container, _Indexed(cur, token))
        cur[token] = container
        return container

    def finish(self) -> dict[str, object]:
        # Children are made after their parents: materializing in reverse
        # order replaces each nested container before its parent is copied.
        for builder, state in reversed(self.indexed.values()):
            parent, key = state.parent, state.key
            if parent.get(key) is not builder:
                continue  # a later conflicting path replaced it
            if state.length - len(builder) <= _MAX_ARRAY_HOLES:
                parent[key] = [builder.get(i) for i in range(state.length)]
            else:
                parent[key] = {str(k): v for k, v in builder.items()}
        return cast("dict[str, object]", self.out)


def _is_array_token(token: _Token) -> bool:
    return isinstance(token, int) or token == ""


def make_tree_record[A](entries: Iterable[tuple[str, A]], /) -> dict[str, TreeValue[A | None]]:
    """The tree of bracket-path ``entries`` (Effect's ``makeTreeRecord``)."""
    builder = _Builder()
    for path, value in entries:
        builder.add(path, value)
    return cast("dict[str, TreeValue[A | None]]", builder.finish())


def collect_bracket_path_entries[A](
    is_leaf: Callable[[object], TypeIs[A]], /
) -> Callable[[Mapping[str, object]], list[tuple[str, A]]]:
    """A tree flattened to bracket-path entries (Effect's
    ``collectBracketPathEntries``): a list of leaves repeats its key, any
    other list indexes ``key[i]``, a mapping ``key[k]``; values that are
    neither leaves nor containers are dropped."""

    def collect(tree: Mapping[str, object]) -> list[tuple[str, A]]:
        entries: list[tuple[str, A]] = []
        for key, value in tree.items():
            _append_bracket_entries(is_leaf, entries, key, value)
        return entries

    return collect


def _append_bracket_entries[A](
    is_leaf: Callable[[object], TypeIs[A]], entries: list[tuple[str, A]], key: str, value: object
) -> None:
    if is_leaf(value):
        entries.append((key, value))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = cast("Sequence[object]", value)
        if all(is_leaf(item) for item in items):
            entries.extend((key, cast("A", item)) for item in items)
        else:
            for i, item in enumerate(items):
                _append_bracket_entries(is_leaf, entries, f"{key}[{i}]", item)
    elif isinstance(value, Mapping):
        for k, v in cast("Mapping[object, object]", value).items():
            _append_bracket_entries(is_leaf, entries, f"{key}[{k}]", v)
