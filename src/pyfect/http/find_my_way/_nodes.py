"""find-my-way's radix tree: static, parametric and wildcard nodes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Self

type Node = StaticNode | ParametricNode | WildcardNode


@dataclass(frozen=True, slots=True)
class Handler[A]:
    params: tuple[str, ...]
    handler: A

    def create_params(self, values: list[str]) -> dict[str, str]:
        return dict(zip(self.params, values, strict=False))


@dataclass(frozen=True, slots=True)
class Brother:
    params_count: int
    path_index: int
    node: Node


class _NodeBase:
    __slots__ = ("handler",)

    def __init__(self) -> None:
        # The first route added to a node wins (find-my-way's
        # "unconstrained handler").
        self.handler: Handler[object] | None = None

    @property
    def is_leaf(self) -> bool:
        return self.handler is not None

    def add_route(self, handler: Handler[object]) -> None:
        if self.handler is None:
            self.handler = handler


class _ParentNode(_NodeBase):
    __slots__ = ("static_children",)

    def __init__(self) -> None:
        super().__init__()
        self.static_children: dict[str, StaticNode] = {}

    def find_static_matching_child(self, path: str, index: int) -> StaticNode | None:
        child = self.static_children.get(path[index : index + 1])
        if child is None or not path.startswith(child.prefix[1:], index + 1):
            return None
        return child

    def get_static_child(self, path: str, index: int = 0) -> Self | StaticNode | None:
        if len(path) == index:
            return self
        child = self.find_static_matching_child(path, index)
        if child is None:
            return None
        return child.get_static_child(path, index + len(child.prefix))

    def create_static_child(self, path: str) -> Self | StaticNode:
        if not path:
            return self
        child = self.static_children.get(path[0])
        if child is not None:
            i = 1
            while i < len(child.prefix):
                if path[i : i + 1] != child.prefix[i]:
                    child = child.split(self, i)
                    break
                i += 1
            return child.create_static_child(path[i:])
        node = StaticNode(path)
        self.static_children[path[0]] = node
        return node


class StaticNode(_ParentNode):
    __slots__ = ("parametric_children", "prefix", "wildcard_child")
    tag: Literal["static"] = "static"

    def __init__(self, prefix: str) -> None:
        super().__init__()
        self.prefix = prefix
        self.parametric_children: list[ParametricNode] = []
        self.wildcard_child: WildcardNode | None = None

    def create_parametric_child(
        self, regex: re.Pattern[str] | None, static_suffix: str, node_path: str
    ) -> ParametricNode:
        for child in self.parametric_children:
            same = (
                not child.is_regex
                if regex is None
                else child.regex is not None and child.regex.pattern == regex.pattern
            )
            if same:
                child.node_paths.add(node_path)
                return child
        child = ParametricNode(regex, static_suffix, node_path)
        self.parametric_children.append(child)
        self.parametric_children.sort(key=_ParametricOrder)
        return child

    def create_wildcard_child(self) -> WildcardNode:
        if self.wildcard_child is None:
            self.wildcard_child = WildcardNode()
        return self.wildcard_child

    def split(self, parent: _ParentNode, length: int) -> StaticNode:
        parent_prefix = self.prefix[:length]
        self.prefix = self.prefix[length:]
        node = StaticNode(parent_prefix)
        node.static_children[self.prefix[0]] = self
        parent.static_children[parent_prefix[0]] = node
        return node

    def next_node(
        self, path: str, index: int, stack: list[Brother], params_count: int
    ) -> Node | None:
        node: Node | None = self.find_static_matching_child(path, index)
        first_brother = 0
        if node is None:
            if not self.parametric_children:
                return self.wildcard_child
            node = self.parametric_children[0]
            first_brother = 1
        if self.wildcard_child is not None:
            stack.append(Brother(params_count, index, self.wildcard_child))
        stack.extend(
            Brother(params_count, index, child)
            for child in reversed(self.parametric_children[first_brother:])
        )
        return node


class _ParametricOrder:
    """find-my-way's comparator: regex nodes before plain ones, and a
    regex whose suffix ends with another's before it."""

    __slots__ = ("node",)

    def __init__(self, node: ParametricNode) -> None:
        self.node = node

    def __lt__(self, other: _ParametricOrder) -> bool:
        a, b = self.node, other.node
        if not a.is_regex:
            return False
        if not b.is_regex:
            return True
        return a.static_suffix != b.static_suffix and a.static_suffix.endswith(b.static_suffix)


class ParametricNode(_ParentNode):
    __slots__ = ("is_regex", "node_paths", "regex", "static_suffix")
    tag: Literal["parametric"] = "parametric"

    def __init__(self, regex: re.Pattern[str] | None, static_suffix: str, node_path: str) -> None:
        super().__init__()
        self.regex = regex
        self.static_suffix = static_suffix
        self.is_regex = regex is not None
        self.node_paths = {node_path}

    def next_node(
        self, path: str, index: int, stack: list[Brother], params_count: int
    ) -> Node | None:
        del stack, params_count
        return self.find_static_matching_child(path, index)


class WildcardNode(_NodeBase):
    __slots__ = ()
    tag: Literal["wildcard"] = "wildcard"

    def next_node(
        self, path: str, index: int, stack: list[Brother], params_count: int
    ) -> Node | None:
        del path, index, stack, params_count
        return None
