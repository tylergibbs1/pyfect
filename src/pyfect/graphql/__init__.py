"""GraphQL clients (Effect's ``effect/graphql``), without a GraphQL
parser: operations carry their printed documents and schemas.

``operation`` defines queries, mutations and subscriptions; ``group``
collects them on a class; ``client`` makes a typed client of a group;
``middleware`` wraps its calls; ``protocol`` sends them (HTTP and
graphql-sse); ``client_error`` holds what calls fail with.
"""

from pyfect.graphql import (
    client,
    client_error,
    group,
    middleware,
    operation,
    protocol,
    resolver,
    template,
)
from pyfect.graphql.client import items, layer_test, make, make_test, pages
from pyfect.graphql.client_error import GraphQLClientError, GraphQLError
from pyfect.graphql.group import GraphQLGroup
from pyfect.graphql.middleware import GraphQLMiddleware, Implementation, map_request
from pyfect.graphql.operation import (
    Method,
    NoVariables,
    Operation,
    PartialResult,
    Subscription,
    SubscriptionMethod,
    enum_literals,
    mutation,
    other_typename,
    query,
    subscription,
)
from pyfect.graphql.protocol import (
    ExecutionResult,
    GraphQLProtocol,
    GraphQLRequest,
    layer_http,
    layer_web_socket,
    make_http,
    make_web_socket,
)
from pyfect.graphql.template import DocumentTemplate

__all__ = [
    "DocumentTemplate",
    "ExecutionResult",
    "GraphQLClientError",
    "GraphQLError",
    "GraphQLGroup",
    "GraphQLMiddleware",
    "GraphQLProtocol",
    "GraphQLRequest",
    "Implementation",
    "Method",
    "NoVariables",
    "Operation",
    "PartialResult",
    "Subscription",
    "SubscriptionMethod",
    "client",
    "client_error",
    "enum_literals",
    "group",
    "items",
    "layer_http",
    "layer_test",
    "layer_web_socket",
    "make",
    "make_http",
    "make_test",
    "make_web_socket",
    "map_request",
    "middleware",
    "mutation",
    "operation",
    "other_typename",
    "pages",
    "protocol",
    "query",
    "resolver",
    "subscription",
    "template",
]
