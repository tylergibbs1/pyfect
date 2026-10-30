"""The Effect DevTools protocol (Effect's ``effect/devtools``): report
spans, span events and metrics to the DevTools over a socket.

``layer()`` connects to the DevTools at ``ws://localhost:34437``;
``layer_socket`` uses the ``Socket`` provided.
"""

from pyfect.devtools import client, schema, server
from pyfect.devtools.client import DevToolsClient, DevToolsClientService, layer_tracer, make_tracer
from pyfect.devtools.layers import DEFAULT_URL, layer, layer_socket, layer_web_socket

__all__ = [
    "DEFAULT_URL",
    "DevToolsClient",
    "DevToolsClientService",
    "client",
    "layer",
    "layer_socket",
    "layer_tracer",
    "layer_web_socket",
    "make_tracer",
    "schema",
    "server",
]
