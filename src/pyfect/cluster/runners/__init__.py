"""How runners talk to each other (Effect's ``Runners``): ping a runner,
send it a message, tell it a persisted message is waiting, and deliver to
this runner's entities through storage.

``make`` completes a ``RunnersTransport`` with local delivery;
``layer_noop`` serves a single runner, and ``layer_rpc`` speaks the
``Rpcs`` protocol to other runners through an ``RpcClientProtocol``.
"""

from pyfect.cluster.runners._local import make
from pyfect.cluster.runners._noop import layer_noop, make_noop
from pyfect.cluster.runners._rpc import (
    EnvelopePayload,
    NotifyPayload,
    ReplyEncodedSchema,
    RequestPayload,
    Rpcs,
    layer_rpc,
    make_rpc_client,
    make_rpc_runners,
)
from pyfect.cluster.runners._service import (
    LocalSendError,
    NotifyLocalFn,
    RpcClientProtocol,
    RpcClientProtocolService,
    Runners,
    RunnersService,
    RunnersTransport,
    SendError,
    SendLocalFn,
)

__all__ = [
    "EnvelopePayload",
    "LocalSendError",
    "NotifyLocalFn",
    "NotifyPayload",
    "ReplyEncodedSchema",
    "RequestPayload",
    "RpcClientProtocol",
    "RpcClientProtocolService",
    "Rpcs",
    "Runners",
    "RunnersService",
    "RunnersTransport",
    "SendError",
    "SendLocalFn",
    "layer_noop",
    "layer_rpc",
    "make",
    "make_noop",
    "make_rpc_client",
    "make_rpc_runners",
]
