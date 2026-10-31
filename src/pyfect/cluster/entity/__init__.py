"""Entities (Effect's ``Entity``): addressable types whose instances
answer RPCs across a cluster. Subclass ``Entity`` with the RPCs as
attributes, register the handlers with ``to_layer`` (or a mailbox with
``to_layer_queue``) and call them through ``client()``."""

from pyfect.cluster.entity._entity import ClusterClientError, Entity
from pyfect.cluster.entity._handlers import (
    Bound,
    Concurrency,
    EntityHandlerFn,
    EntityHandlers,
    EntityOptions,
    StreamBound,
)
from pyfect.cluster.entity._keep_alive import KeepAliveRpc, keep_alive
from pyfect.cluster.entity._queue import Behaviour, Replier
from pyfect.cluster.entity._request import Request
from pyfect.cluster.entity._services import CurrentAddress, CurrentRunnerAddress, KeepAliveLatch
from pyfect.cluster.entity._test_client import make_test_client

__all__ = [
    "Behaviour",
    "Bound",
    "ClusterClientError",
    "Concurrency",
    "CurrentAddress",
    "CurrentRunnerAddress",
    "Entity",
    "EntityHandlerFn",
    "EntityHandlers",
    "EntityOptions",
    "KeepAliveLatch",
    "KeepAliveRpc",
    "Replier",
    "Request",
    "StreamBound",
    "keep_alive",
    "make_test_client",
]
