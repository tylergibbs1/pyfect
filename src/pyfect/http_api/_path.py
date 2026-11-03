"""Endpoint paths: the router path of an endpoint and the URL a client
builds from its path parameters (Effect's ``internal/path``)."""

from __future__ import annotations

import re
from collections.abc import Callable, Set

from pyfect.http.find_my_way._paths import closing_parenthesis
from pyfect.schema import Top, ast

_EMPTY: frozenset[str] = frozenset()
_PARAM = re.compile(r":(\w+)", re.ASCII)
_PARAMS = re.compile(r"::|:(\w+)", re.ASCII)


def last_encoding(node: ast.AST) -> ast.AST:
    """The node a value is finally encoded to."""
    while node.encoding is not None:
        node = node.encoding[-1].to
    return node


def param_names(schema: Top | None) -> Set[str] | None:
    """The keys of a params struct; ``None`` when the schema is not a plain
    struct (any parameter may be one)."""
    if schema is None:
        return _EMPTY
    node = last_encoding(schema.__codec__().ast)
    if isinstance(node, ast.Objects) and not node.index_signatures:
        return frozenset(str(p.name) for p in node.properties)
    return None


def to_router_path(path: str, schema: Top | None) -> str:
    """``path`` with the parameters ``schema`` does not declare escaped
    (``::``), so they match literally."""
    if schema is None or ":" not in path:
        return path
    names = param_names(schema)
    if names is None:
        return path
    out: list[str] = []
    i = 0
    while i < len(path):
        char = path[i]
        if char != ":":
            out.append(char)
            i += 1
            continue
        if path[i + 1 : i + 2] == ":":
            out.append("::")
            i += 2
            continue
        param = _PARAM.match(path, i)
        if param is not None and param.group(1) in names:
            out.append(param.group(0))
            i = param.end()
            following = path[i : i + 1]
            if following == "(":
                end = closing_parenthesis(path, i)
                out.append(path[i : end + 1])
                i = end + 1
            elif following and following not in "/.-?":
                # find-my-way needs a regex to end the parameter name here.
                out.append("(.*?)")
        else:
            out.append("::")
            i += 1
    return "".join(out)


def replace_params(
    path: str,
    names: Set[str] | None,
    replace: Callable[[str, bool], str | None],
) -> str:
    """``path`` with each declared parameter replaced by ``replace(name,
    optional)``; ``None`` drops an optional parameter and its slash."""
    out: list[str] = []
    last = 0
    position = 0
    while (param := _PARAMS.search(path, position)) is not None:
        position = param.end()
        name = param.group(1)
        if name is None or (names is not None and name not in names):
            continue
        end = param.end()
        if path[end : end + 1] == "(":
            end = closing_parenthesis(path, end) + 1
        optional = path[end : end + 1] == "?"
        if optional:
            end += 1
        value = replace(name, optional)
        start = param.start()
        if value is None and path[start - 1 : start] == "/":
            start -= 1
        out.append(path[last:start] + (value or ""))
        position = end
        last = end
    out.append(path[last:])
    return "".join(out)
