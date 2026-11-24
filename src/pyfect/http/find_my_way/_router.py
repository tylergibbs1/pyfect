"""find-my-way's router: routes registered by method and path pattern,
found by method and URL."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Generic, TypeVar, cast

from pyfect._js import decode_uri, decode_uri_component
from pyfect.http.find_my_way import _query_string
from pyfect.http.find_my_way._nodes import (
    Brother,
    Handler,
    Node,
    ParametricNode,
    StaticNode,
    WildcardNode,
)
from pyfect.http.find_my_way._paths import (
    closing_parenthesis,
    remove_duplicate_slashes,
    trim_last_slash,
    trim_regex_anchors,
)

_FULL_PATH = re.compile(r"^https?://.*?/")
_OPTIONAL_PARAM = re.compile(r"(/:[^/()]*?)\?(/?)")
_CLEAN_SINGLE_PARAM = re.compile(r"^[^:*(]*/:[^/:*(.-]+$")
_COMPLEX_PARAM = re.compile(r"[(*]|[^/]:|:[^/]*[-.]")

HTTP_METHODS: tuple[str, ...] = (
    "ACL", "BIND", "CHECKOUT", "CONNECT", "COPY", "DELETE", "GET", "HEAD", "LINK", "LOCK",
    "M-SEARCH", "MERGE", "MKACTIVITY", "MKCALENDAR", "MKCOL", "MOVE", "NOTIFY", "OPTIONS",
    "PATCH", "POST", "PROPFIND", "PROPPATCH", "PURGE", "PUT", "QUERY", "REBIND", "REPORT",
    "SEARCH", "SOURCE", "SUBSCRIBE", "TRACE", "UNBIND", "UNLINK", "UNLOCK", "UNSUBSCRIBE",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class RouterConfig:
    """How request paths are normalized before matching.

    ``use_semicolon_delimiter`` ends the path at the first ``;`` as well as at
    ``?`` and ``#``. ``decode_static_path`` percent-decodes the whole path
    before matching; without it, route text without parameters only matches
    the same characters as received, and parameter values are decoded once
    (a malformed escape in one does not match). ``strict_config`` turns every
    normalization off."""

    ignore_trailing_slash: bool = True
    ignore_duplicate_slashes: bool = True
    case_sensitive: bool = False
    max_param_length: int = 100
    use_semicolon_delimiter: bool = True
    decode_static_path: bool = True


strict_config = RouterConfig(
    case_sensitive=True,
    ignore_trailing_slash=False,
    ignore_duplicate_slashes=False,
    use_semicolon_delimiter=False,
    decode_static_path=False,
)
"""A ``RouterConfig`` that matches static route text literally, for when a
proxy authorizes requests by path prefix. Parameter values are still decoded,
so ``/files/:name`` is reached by ``/files/%73ecret``. Override a field with
``dataclasses.replace``."""


A_co = TypeVar("A_co", covariant=True)


@dataclass(frozen=True, slots=True)
class FindResult(Generic[A_co]):
    handler: A_co
    params: dict[str, str]
    search_params: dict[str, str | list[str]]


@dataclass(frozen=True, slots=True)
class _Route:
    method: str
    pattern: str


@dataclass(slots=True)
class _Registered:
    node: Node
    handler: Handler[object]
    fallback: bool


# Components whose escapes ``decodeURI`` keeps and find-my-way decodes
# itself in parameters: ``# $ & + , / : ; = ? @`` and ``%``.
_COMPONENT_ESCAPES: dict[str, str] = {
    "25": "%", "23": "#", "24": "$", "26": "&", "2B": "+", "2C": ",", "2F": "/",
    "3A": ":", "3B": ";", "3D": "=", "3F": "?", "40": "@",
}  # fmt: skip


def _component_char(escape: str) -> str | None:
    return _COMPONENT_ESCAPES.get(escape.upper())


def _safe_decode_uri(path: str, semicolon: bool = True) -> tuple[str, str, bool]:
    """The path decoded but for component escapes, the query split off at
    ``?``, ``#`` or (with ``semicolon``) ``;``, and whether parameters must
    still be decoded."""
    should_decode = should_decode_param = False
    query = ""
    # Each ``%25`` becomes ``%2525``, joined once: splicing the path per
    # escape (as find-my-way does) costs time quadratic in their number.
    pieces: list[str] = []
    start = 0
    end = len(path)
    i = 1
    while i < end:
        char = path[i]
        if char == "%":
            if _component_char(path[i + 1 : i + 3]) is None:
                should_decode = True
            else:
                should_decode_param = True
                if path[i + 1 : i + 3] == "25":
                    should_decode = True
                    pieces.append(path[start : i + 1])
                    pieces.append("25")
                    start = i + 1
                i += 2
        elif char in "?#" or (char == ";" and semicolon):
            query = path[i + 1 :]
            end = i
            break
        i += 1
    pieces.append(path[start:end])
    path = "".join(pieces)
    return (decode_uri(path) if should_decode else path), query, should_decode_param


type _DecodeParam = Callable[[str], str | None]
"""Decodes a parameter value; ``None`` for a malformed escape, which does not match."""


def _path_end(path: str, semicolon: bool) -> int:
    for i in range(1, len(path)):
        char = path[i]
        if char in "?#" or (char == ";" and semicolon):
            return i
    return len(path)


def _try_decode_component(text: str) -> str | None:
    try:
        return decode_uri_component(text)
    except ValueError:
        return None


# Second decoding pass: expects ``_safe_decode_uri`` to have decoded every other escape.
def _safe_decode_component(text: str) -> str:
    start = text.find("%")
    if start == -1:
        return text
    decoded: list[str] = []
    last = start
    i = start
    while i < len(text):
        if text[i] == "%":
            if i + 2 >= len(text):
                break
            decoded.append(text[last:i] + (_component_char(text[i + 1 : i + 3]) or "undefined"))
            last = i + 3
        i += 1
    return text[:start] + "".join(decoded) + text[last:]


def _is_clean(path: str, semicolon: bool) -> bool:
    """A canonical lowercase path needs no normalization."""
    if not path.startswith("/") or (len(path) > 1 and path.endswith("/")):
        return False
    for i in range(1, len(path)):
        char = path[i]
        if (
            char in "%?#"
            or (char == ";" and semicolon)
            or "A" <= char <= "Z"
            or (char == "/" and path[i - 1] == "/")
        ):
            return False
    return True


@dataclass
class Router[A]:
    """Routes by method and path. Paths are ``/``-rooted patterns with
    ``:name`` parameters (``:name(regex)``, ``:name?`` last, ``::`` for a
    literal colon) and a trailing ``*`` wildcard; ``"*"`` matches all."""

    config: RouterConfig = field(default_factory=RouterConfig)
    max_param_length_exceeded: bool = False
    _routes: dict[_Route, _Registered] = field(default_factory=dict[_Route, _Registered])
    _trees: dict[str, StaticNode] = field(default_factory=dict[str, StaticNode])
    _static: dict[str, dict[str, Handler[object]]] = field(
        default_factory=dict[str, dict[str, Handler[object]]]
    )
    _single_param: dict[str, dict[str, Handler[object]]] = field(
        default_factory=dict[str, dict[str, Handler[object]]]
    )
    _single_param_disabled: set[str] = field(default_factory=set[str])

    def on(self, method: str | Iterable[str], path: str, handler: A) -> None:
        """Register ``handler``; a duplicate method and pattern raises
        ``ValueError``."""
        self._register(method, path, handler, fallback=False)

    def all(self, path: str, handler: A) -> None:
        self.on(HTTP_METHODS, path, handler)

    def on_fallback(self, method: str, path: str, handler: A) -> None:
        """Register ``handler`` unless a route is already declared at
        ``path``; a route declared there later replaces it. ``"*"`` is
        every method."""
        methods = HTTP_METHODS if method == "*" else method
        self._register(methods, path, handler, fallback=True)

    def _register(
        self, method: str | Iterable[str], path: str, handler: A, *, fallback: bool
    ) -> None:
        optional = _OPTIONAL_PARAM.search(path)
        if optional is not None:
            if optional.end() != len(path):
                raise ValueError("Optional Parameter needs to be the last parameter of the path")
            full = _OPTIONAL_PARAM.sub(r"\1\2", path, count=1)
            self._register(method, full, handler, fallback=fallback)
            bare = _OPTIONAL_PARAM.sub(r"\2", path, count=1) or "/"
            self._register(method, bare, handler, fallback=fallback)
            return
        if self.config.ignore_duplicate_slashes:
            path = remove_duplicate_slashes(path)
        if self.config.ignore_trailing_slash:
            path = trim_last_slash(path)
        for name in [method] if isinstance(method, str) else method:
            self._on(name, path, handler, fallback)

    def _on(self, method: str, path: str, handler: A, fallback: bool) -> None:  # noqa: PLR0912, PLR0915
        tree = self._trees.get(method)
        if tree is None:
            tree = self._trees[method] = StaticNode("/")
        pattern: str = path
        if pattern == "*" and tree.prefix:
            root = StaticNode("")
            root.static_children["/"] = tree
            tree = self._trees[method] = root
        parent_index = len(tree.prefix)
        current: Node = tree
        params: list[str] = []
        lower = not self.config.case_sensitive
        # Decoded lookups see a literal % in the request as %25.
        escape = self.config.decode_static_path
        i = 0
        while i <= len(pattern):
            char = pattern[i : i + 1]
            if char == ":" and pattern[i + 1 : i + 2] == ":":
                i += 2
                continue
            is_param = char == ":"
            is_wildcard = char == "*"
            if is_param or is_wildcard or (i == len(pattern) and i != parent_index):
                static_path = pattern[parent_index:i]
                if lower:
                    static_path = static_path.lower()
                static_path = static_path.replace("::", ":")
                if escape:
                    static_path = static_path.replace("%", "%25")
                assert not isinstance(current, WildcardNode)
                current = current.create_static_child(static_path)
            if is_param:
                is_regex_node = False
                is_param_safe = True
                backtrack = ""
                regexps: list[str] = []
                parts = ""
                last_start = i + 1
                j: int = last_start
                while True:
                    c = pattern[j : j + 1]
                    is_regex_param = c == "("
                    is_static_part = c in ("-", ".")
                    is_end: bool = c == "/" or j == len(pattern)
                    if is_regex_param or is_static_part or is_end:
                        params.append(pattern[last_start:j])
                        is_regex_node = is_regex_node or is_regex_param or is_static_part
                        if is_regex_param:
                            end: int = closing_parenthesis(pattern, j)
                            regexps.append(trim_regex_anchors(pattern[j : end + 1]))
                            j = end + 1
                            is_param_safe = True
                        else:
                            regexps.append(
                                "(.*?)" if is_param_safe else f"({backtrack}|(?:(?!{backtrack}).)*)"
                            )
                            is_param_safe = False
                        static_start: int = j
                        while j < len(pattern):
                            c = pattern[j]
                            if c == "/":
                                break
                            if c == ":":
                                if pattern[j + 1 : j + 2] == ":":
                                    j += 1
                                else:
                                    break
                            j += 1
                        static_part = pattern[static_start:j]
                        if static_part:
                            static_part = static_part.replace("::", ":")
                            if escape:
                                static_part = static_part.replace("%", "%25")
                            backtrack = re.escape(static_part)
                            regexps.append(backtrack)
                        last_start = j + 1
                        parts += "()" + static_part
                        if is_end or pattern[j : j + 1] == "/" or j == len(pattern):
                            node_pattern = parts if is_regex_node else static_part
                            node_path = pattern[i:j]
                            pattern = pattern[: i + 1] + node_pattern + pattern[j:]
                            i += len(node_pattern)
                            regex = (
                                re.compile("(?:" + "".join(regexps) + r")\Z", re.ASCII)
                                if is_regex_node
                                else None
                            )
                            assert isinstance(current, StaticNode)
                            current = current.create_parametric_child(regex, static_part, node_path)
                            parent_index = i + 1
                            break
                    j += 1
            elif is_wildcard:
                params.append("*")
                assert isinstance(current, StaticNode)
                current = current.create_wildcard_child()
                parent_index = i + 1
                if i != len(pattern) - 1:
                    raise ValueError("Wildcard must be the last character in the route")
            i += 1

        if lower:
            pattern = pattern.lower()
        if pattern == "*":
            pattern = "/*"
        route = _Route(method, pattern)
        added = Handler[object](tuple(params), handler)
        existing = self._routes.get(route)
        # Different regex nodes can share a normalized pattern.
        if existing is not None and existing.node is current:
            if fallback:
                return
            if existing.fallback:
                current.replace_route(existing.handler, added)
                existing.fallback = False
                return
        if existing is not None:
            raise ValueError(f"Method '{method}' already declared for route '{pattern}'")
        current.add_route(added)
        stored = current.handler
        assert stored is not None
        self._routes[route] = _Registered(current, stored, fallback)
        if not params:
            key = self._escape_percent(pattern.replace("::", ":"))
            self._static.setdefault(method, {}).setdefault(key, stored)
        elif _CLEAN_SINGLE_PARAM.match(path):
            if method not in self._single_param_disabled:
                prefix = path[: path.index(":")]
                if lower:
                    prefix = prefix.lower()
                prefix = self._escape_percent(prefix)
                self._single_param.setdefault(method, {}).setdefault(prefix, stored)
        elif _COMPLEX_PARAM.search(path):
            self._single_param_disabled.add(method)
            self._single_param.pop(method, None)

    def _escape_percent(self, path: str) -> str:
        # Decoded lookups see a literal % in the request as %25.
        return path.replace("%", "%25") if self.config.decode_static_path else path

    def has(self, method: str, path: str) -> bool:
        tree = self._trees.get(method)
        if tree is None:
            return False
        node = tree.get_static_child(path)
        return node is not None and node.is_leaf

    def find(self, method: str, path: str) -> FindResult[A] | None:
        self.max_param_length_exceeded = False
        current: Node | None = self._trees.get(method)
        if current is None:
            return None
        query = ""
        decode_param: _DecodeParam | None = None
        clean = _is_clean(path, self.config.use_semicolon_delimiter)
        if not clean:
            normalized = self._normalize(path)
            if normalized is None:
                return None
            path, query, decode_param = normalized
        origin = path
        if not clean and not self.config.case_sensitive:
            path = path.lower()

        def result(handle: Handler[object], values: list[str]) -> FindResult[A]:
            return FindResult(
                cast("A", handle.handler),
                handle.create_params(values),
                _query_string.parse(query),
            )

        static = self._static.get(method)
        if static is not None and (handle := static.get(path)) is not None:
            return result(handle, [])
        single = self._single_param.get(method)
        if single is not None:
            prefix_length = path.rfind("/") + 1
            handle = single.get(path[:prefix_length])
            if handle is not None and len(path) > prefix_length:
                param: str | None = origin[prefix_length:]
                if decode_param is not None:
                    param = decode_param(param)
                # A malformed escape falls through to the tree, where another route may match.
                if param is not None:
                    if len(param) <= self.config.max_param_length:
                        return result(handle, [param])
                    self.max_param_length_exceeded = True

        assert isinstance(current, StaticNode)
        found = self._walk(current, path, origin, decode_param)
        return None if found is None else result(*found)

    def _walk(
        self, current: Node, path: str, origin: str, decode_param: _DecodeParam | None
    ) -> tuple[Handler[object], list[str]] | None:
        """The tree search: the handler matching ``path`` and its parameter values."""
        assert isinstance(current, StaticNode)
        index = len(current.prefix)
        params: list[str] = []
        length = len(path)
        stack: list[Brother] = []
        while True:
            if index == length and current.handler is not None:
                return current.handler, params
            node: Node | None = current.next_node(path, index, stack, len(params))
            while True:
                # No child matched, or its parameter did not: resume from the next brother node.
                if node is None:
                    if not stack:
                        return None
                    brother = stack.pop()
                    index = brother.path_index
                    del params[brother.params_count :]
                    node = brother.node
                if isinstance(node, StaticNode):
                    index += len(node.prefix)
                    break
                is_wildcard = isinstance(node, WildcardNode)
                end = length if is_wildcard else origin.find("/", index)
                if end == -1:
                    end = length
                param = origin[index:end]
                if decode_param is not None:
                    param = decode_param(param)
                if param is not None and self._push_param(node, param, params):
                    index = end
                    break
                node = None
            current = node

    def _normalize(self, path: str) -> tuple[str, str, _DecodeParam | None] | None:
        """The path to match, its query, and how to decode its parameters;
        ``None`` when a malformed escape makes the path unmatchable."""
        semicolon = self.config.use_semicolon_delimiter
        decode_param: _DecodeParam | None = None
        if not path.startswith("/"):
            path = _FULL_PATH.sub("/", path, count=1)
        if self.config.decode_static_path:
            try:
                path, query, should_decode_param = _safe_decode_uri(path, semicolon)
            except ValueError:
                return None
            if should_decode_param:
                decode_param = _safe_decode_component
        else:
            end = _path_end(path, semicolon)
            query = path[end + 1 :]
            path = path[:end]
            if "%" in path:
                decode_param = _try_decode_component
        if self.config.ignore_duplicate_slashes:
            path = remove_duplicate_slashes(path)
        if self.config.ignore_trailing_slash:
            path = trim_last_slash(path)
        return path, query, decode_param

    def _push_param(
        self, node: ParametricNode | WildcardNode, param: str, params: list[str]
    ) -> bool:
        if isinstance(node, WildcardNode):
            params.append(param)
            return True
        max_length = self.config.max_param_length
        if node.regex is None:
            if len(param) > max_length:
                self.max_param_length_exceeded = True
                return False
            params.append(param)
            return True
        matched = node.regex.match(param)
        if matched is None:
            return False
        groups = [group or "" for group in matched.groups()]
        if any(len(group) > max_length for group in groups):
            self.max_param_length_exceeded = True
            return False
        params.extend(groups)
        return True


__all__ = ["HTTP_METHODS", "FindResult", "Router", "RouterConfig", "strict_config"]
