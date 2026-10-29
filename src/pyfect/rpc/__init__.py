"""Remote procedure calls (Effect's ``effect/rpc``)."""

from pyfect.rpc import client_error, message, middleware, serialization, worker
from pyfect.rpc import schema as rpc_schema
from pyfect.rpc._methods import CallOptions, StreamMethod, UnaryMethod
from pyfect.rpc._rpc import (
    AnyRpc,
    ParseOptions,
    Rpc,
    RpcRequest,
    ServerClient,
    StreamRpc,
    exit_schema,
    fork,
    make,
    uninterruptible,
    wrap,
)
from pyfect.rpc.client_error import RpcClientDefect, RpcClientError
from pyfect.rpc.group import (
    HandlerOf,
    Handlers,
    HandlersFor,
    RpcGroup,
    access_handler,
    to_layer_handler,
)
from pyfect.rpc.middleware import RpcMiddleware

__all__ = [
    "AnyRpc",
    "CallOptions",
    "HandlerOf",
    "Handlers",
    "HandlersFor",
    "ParseOptions",
    "Rpc",
    "RpcClientDefect",
    "RpcClientError",
    "RpcGroup",
    "RpcMiddleware",
    "RpcRequest",
    "ServerClient",
    "StreamMethod",
    "StreamRpc",
    "UnaryMethod",
    "access_handler",
    "client_error",
    "exit_schema",
    "fork",
    "make",
    "message",
    "middleware",
    "rpc_schema",
    "serialization",
    "to_layer_handler",
    "uninterruptible",
    "worker",
    "wrap",
]
