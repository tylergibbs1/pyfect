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
OM_co = TypeVar("OM_co", covariant=True, default=Never)
G_co = TypeVar("G_co", covariant=True)
GT_co = TypeVar("GT_co", covariant=True)
OT_co = TypeVar("OT_co", covariant=True)


class GroupTypes(Generic[G_co, GT_co, OT_co]):
    """The client type and the middleware tags of a group (run by every
    operation, by some), for ``make``. Kept apart: a union of two class
    TypeVars that are both ``Never`` is ``Unknown``."""


class GraphQLGroup(Generic[GM_co, OM_co]):
    """A group of operations; subclass it with the operations as class
    attributes. Clients are made by ``client.make`` and
    ``client.make_test``, not by calling the class.

    ``GM`` is the middleware every operation runs; ``OM`` the middleware
    some operations run (``op.middleware(M)``, or an operation taken from a
    group with middleware), which ``make`` needs too. Pyright cannot gather
    it from the class attributes, so it is declared, and a group whose
    operations run middleware it does not declare is a ``TypeError``."""

    __slots__ = ("_methods",)

    def __init__(self, methods: Mapping[AnyOperation, object]) -> None:
        self._methods = dict(methods)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        declared = {*group_middlewares(cls), *operation_middlewares(cls)}
        undeclared: dict[AnyMiddleware, None] = {}
        for operation in operations_of(cls):
            for middleware in operation.middlewares:
                if middleware not in declared:
                    undeclared[middleware] = None
        if undeclared:
            names = " | ".join(m.__qualname__ for m in undeclared)
            raise TypeError(
                f"{cls.__qualname__}'s operations run middleware it does not declare: {names}. "
                f"Declare it as the second type argument (class {cls.__qualname__}"
                f"(GraphQLGroup[..., {names}])) so that make() requires it"
            )

    @classmethod
    def __graphql_group__(cls) -> GroupTypes[Self, GM_co, OM_co]:
        return GroupTypes()


def _group_arguments(owner: type) -> tuple[object, ...]:
    """The type arguments of the ``GraphQLGroup[...]`` base nearest
    ``owner`` in its MRO; none for a bare ``GraphQLGroup``."""
    for cls in owner.__mro__:
        for base in getattr(cls, "__orig_bases__", ()):
            if get_origin(base) is GraphQLGroup:
                return get_args(base)
    return ()


def group_middlewares(owner: type) -> tuple[AnyMiddleware, ...]:
    """The middleware classes of ``class G(GraphQLGroup[M])`` (or of a
    subclass of it), outermost first; none for any other class."""
    arguments = _group_arguments(owner)
    return _middleware_classes(arguments[0]) if arguments else ()


def operation_middlewares(owner: type) -> tuple[AnyMiddleware, ...]:
    """The middleware classes declared as ``GraphQLGroup[M, OM]``'s ``OM``."""
    arguments = _group_arguments(owner)
    return _middleware_classes(arguments[1]) if len(arguments) > 1 else ()


def _middleware_classes(argument: object) -> tuple[AnyMiddleware, ...]:
    if argument is Never:
        return ()
    if get_origin(argument) in (Union, types.UnionType):
        return tuple(m for arg in get_args(argument) for m in _middleware_classes(arg))
    if isinstance(argument, type) and issubclass(argument, GraphQLMiddleware):
        return (cast("AnyMiddleware", argument),)
    raise TypeError(f"GraphQLGroup[...] takes middleware classes, got {argument!r}")


def operations_of(group: type[GraphQLGroup[Any, Any]]) -> list[AnyOperation]:
    """The operations of ``group``'s attributes, each once; an attribute a
    subclass overrides holds the subclass's operation. Raises
    ``ValueError`` for two operations with one name."""
    attributes: dict[str, object] = {}
    for cls in reversed(group.__mro__):
        attributes.update(vars(cls))
    by_name: dict[str, AnyOperation] = {}
    for value in attributes.values():
        if not isinstance(value, (Operation, Subscription)):
            continue
        operation: AnyOperation = cast("OperationInfo", value)
        existing = by_name.get(operation.name)
        if existing is not None and existing is not operation:
            raise ValueError(f'GraphQLGroup: duplicate operation name "{operation.name}"')
        by_name[operation.name] = operation
    return list(by_name.values())


def method_of(instance: object, operation: AnyOperation) -> object:
    """The method of ``operation`` on a client."""
    return cast("GraphQLGroup[Any, Any]", instance)._methods[operation]  # pyright: ignore[reportPrivateUsage]


__all__ = [
    "GraphQLGroup",
    "GroupTypes",
    "group_middlewares",
    "method_of",
    "operation_middlewares",
    "operations_of",
]
