"""Groups of GraphQL operations (Effect's ``GraphQLGroup``).

A group is a class whose attributes are operations; ``client.make(Group)``
gives an instance whose attributes are their methods. The type argument
names the middleware every operation of the group runs, outermost first::

    class Issues(GraphQLGroup[Auth | Logging]):
        repo_issues = RepoIssues
        issue_updated = IssueUpdated

Read on the class, an operation carries the group's middleware, so another
group takes it with it (Effect's ``GraphQLGroup.merge``)::

    class Everything(GraphQLGroup):
        repo_issues = Issues.repo_issues
        viewer = Viewer
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from typing import Any, Generic, Never, Self, TypeVar, Union, cast, get_args, get_origin

from pyfect.graphql.middleware import AnyMiddleware, GraphQLMiddleware
from pyfect.graphql.operation import AnyOperation, Operation, OperationInfo, Subscription

GM_co = TypeVar("GM_co", covariant=True, default=Never)
G_co = TypeVar("G_co", covariant=True)


class GroupTypes(Generic[G_co, GM_co]):
    """The client type and middleware tags of a group, for ``make``."""


class GraphQLGroup(Generic[GM_co]):
    """A group of operations; subclass it with the operations as class
    attributes. Clients are made by ``client.make`` and
    ``client.make_test``, not by calling the class."""

    __slots__ = ("_methods",)

    def __init__(self, methods: Mapping[AnyOperation, object]) -> None:
        self._methods = dict(methods)

    @classmethod
    def __graphql_group__(cls) -> GroupTypes[Self, GM_co]:
        return GroupTypes()


def group_middlewares(owner: type) -> tuple[AnyMiddleware, ...]:
    """The middleware classes of ``class G(GraphQLGroup[M])``, outermost
    first; none for any other class."""
    for base in getattr(owner, "__orig_bases__", ()):
        if get_origin(base) is GraphQLGroup:
            return _middleware_classes(get_args(base)[0])
    return ()


def _middleware_classes(argument: object) -> tuple[AnyMiddleware, ...]:
    if get_origin(argument) in (Union, types.UnionType):
        return tuple(m for arg in get_args(argument) for m in _middleware_classes(arg))
    if isinstance(argument, type) and issubclass(argument, GraphQLMiddleware):
        return (cast("AnyMiddleware", argument),)
    raise TypeError(f"GraphQLGroup[...] takes middleware classes, got {argument!r}")


def operations_of(group: type[GraphQLGroup[Any]]) -> list[AnyOperation]:
    """The operations of ``group``'s attributes, each once; an attribute a
    subclass overrides holds the subclass's operation. Raises
    ``ValueError`` for two operations with one name."""
    attributes: dict[str, object] = {}
    for cls in reversed(group.__mro__):
        attributes.update(vars(cls))
    by_name: dict[str, AnyOperation] = {}
    for value in attributes.values():
        if not isinstance(value, Operation | Subscription):
            continue
        operation: AnyOperation = cast("OperationInfo", value)
        existing = by_name.get(operation.name)
        if existing is not None and existing is not operation:
            raise ValueError(f'GraphQLGroup: duplicate operation name "{operation.name}"')
        by_name[operation.name] = operation
    return list(by_name.values())


def method_of(instance: object, operation: AnyOperation) -> object:
    """The method of ``operation`` on a client."""
    return cast("GraphQLGroup[Any]", instance)._methods[operation]  # pyright: ignore[reportPrivateUsage]


__all__ = ["GraphQLGroup", "GroupTypes", "group_middlewares", "method_of", "operations_of"]
