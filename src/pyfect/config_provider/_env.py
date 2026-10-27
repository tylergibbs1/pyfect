"""``from_env`` and ``from_env_record``: flat ``NAME=value`` pairs read as a
tree, each ``_`` in a name starting a new path segment."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from pyfect.config_provider._node import Array, Node, Path, Record, Value
from pyfect.config_provider._provider import ConfigProvider, make
from pyfect.effect import succeed

_CANONICAL_INDEX = re.compile(r"0|[1-9][0-9]*")
_MAX_INDEX = 2**32 - 1


type _Trie = dict[str, _Trie]
"""Name segments below a path; empty when no name continues past it."""


def from_env_record(
    env: Mapping[str, str | None], *, preserve_empty_strings: bool = False
) -> ConfigProvider:
    """A provider over ``env``; ``None`` values are skipped. A name is split
    on every ``_`` (``A__B`` has an empty middle segment), and a path also
    matches the name its segments join to, so ``("NODE_ENV",)`` and
    ``("NODE", "ENV")`` both find ``NODE_ENV``. A path whose children are
    all array indices (``A_0``, ``A_1``) is an ``Array``; one with other
    children a ``Record``, holding the path's own value if it has one. An
    empty value is absent unless ``preserve_empty_strings``. As in Effect,
    the names are read when the provider is made and the values at each
    lookup."""
    trie = _trie(env)
    return make(lambda path: succeed(_node_at(trie, env, path, preserve_empty_strings)))


def from_env(
    env: Mapping[str, str] | None = None, *, preserve_empty_strings: bool = False
) -> ConfigProvider:
    """``from_env_record`` over ``env``, or over ``os.environ`` (names and
    values read at each lookup) when no ``env`` is given."""
    if env is not None:
        return from_env_record(env, preserve_empty_strings=preserve_empty_strings)
    return make(
        lambda path: succeed(_node_at(_trie(os.environ), os.environ, path, preserve_empty_strings))
    )


def _trie(env: Mapping[str, str | None]) -> _Trie:
    root: _Trie = {}
    for name, value in env.items():
        if value is None:
            continue
        node = root
        for segment in name.split("_"):
            node = node.setdefault(segment, {})
    return root


def _node_at(
    trie: _Trie, env: Mapping[str, str | None], path: Path, preserve_empty_strings: bool
) -> Node | None:
    leaf = env.get("_".join(str(seg) for seg in path))
    if leaf == "" and not preserve_empty_strings:
        leaf = None
    node: _Trie | None = trie
    for seg in path:
        node = node.get(str(seg))
        if node is None:
            break
    if not node:
        return None if leaf is None else Value(leaf)
    if all(_is_index(child) for child in node):
        return Array(max(int(child) for child in node) + 1, leaf)
    return Record(frozenset(node), leaf)


def _is_index(key: str) -> bool:
    return _CANONICAL_INDEX.fullmatch(key) is not None and int(key) < _MAX_INDEX
