"""Client middleware for GraphQL operations (Effect's ``GraphQLMiddleware``).

A middleware is a tag class whose service is an ``Implementation``: it
gets each request with ``next`` (the rest of the chain) and may change the
request, the result, or fail with its own error ``E`` while needing ``R``::

    class Auth(GraphQLMiddleware[TokenExpired, CurrentUser]): ...

    AuthLive = layer.succeed(Auth, map_request(add_token))

Attach it to an operation with ``op.middleware(Auth)`` (and declare it on
the group, ``class Api(GraphQLGroup[Never, Auth])``, so ``make`` requires
it) or to every operation of a group with ``class Api(GraphQLGroup[Auth]):
...``. Group middleware runs outside operation middleware; within a level,
in attach order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Never, TypeVar

from pyfect.context import Tag
from pyfect.effect import Effect
from pyfect.graphql._types import ExecutionResult, GraphQLRequest
from pyfect.graphql.client_error import GraphQLClientError
from pyfect.stream import Stream, from_effect

if TYPE_CHECKING:
    from pyfect.graphql.operation import AnyOperation

E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteOptions:
    """What a middleware's ``execute`` gets. ``next`` fails with
    ``GraphQLClientError`` and, at runtime, with the errors of the
    middleware further in (Effect's ``Types.unhandled``)."""

    operation: AnyOperation
    request: GraphQLRequest
    next: Callable[[GraphQLRequest], Effect[ExecutionResult, GraphQLClientError]]


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscribeOptions:
    """What a middleware's ``subscribe`` gets."""

    operation: AnyOperation
    request: GraphQLRequest
    next: Callable[[GraphQLRequest], Stream[ExecutionResult, GraphQLClientError]]


@dataclass(frozen=True, slots=True, kw_only=True)
class Implementation(Generic[E_co, R_co]):
    """A middleware's service: one function around queries and mutations,
    one around subscriptions."""

    execute: Callable[[ExecuteOptions], Effect[ExecutionResult, GraphQLClientError | E_co, R_co]]
    subscribe: Callable[
        [SubscribeOptions], Stream[ExecutionResult, GraphQLClientError | E_co, R_co]
    ]


class GraphQLMiddleware(Tag[Implementation[E_co, R_co]], Generic[E_co, R_co], base=True):
    """A middleware tag failing with ``E`` and needing ``R``. Subclass it
    once per middleware."""


type AnyMiddleware = type[GraphQLMiddleware[Any, Any]]


def map_request[E = Never, R = Never](
    f: Callable[[GraphQLRequest, AnyOperation], Effect[GraphQLRequest, E, R]],
) -> Implementation[E, R]:
    """A middleware that only changes the request, for every kind of
    operation."""

    def execute(options: ExecuteOptions) -> Effect[ExecutionResult, GraphQLClientError | E, R]:
        return f(options.request, options.operation).flat_map(options.next)

    def subscribe(options: SubscribeOptions) -> Stream[ExecutionResult, GraphQLClientError | E, R]:
        return from_effect(f(options.request, options.operation)).flat_map(options.next)

    return Implementation(execute=execute, subscribe=subscribe)


__all__ = [
    "AnyMiddleware",
    "ExecuteOptions",
    "GraphQLMiddleware",
    "Implementation",
    "SubscribeOptions",
    "map_request",
]
