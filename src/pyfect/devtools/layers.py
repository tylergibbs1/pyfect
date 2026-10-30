"""Ready-made DevTools layers (Effect's ``devtools/DevTools``): every span
is reported to the DevTools at ``ws://localhost:34437`` by default."""

from __future__ import annotations

from typing import Never

from pyfect.devtools.client import layer_tracer
from pyfect.layer import Layer
from pyfect.layer import provide as layer_provide
from pyfect.socket import Socket, WebSocketConstructor
from pyfect.socket import layer_web_socket as socket_layer_web_socket

__all__ = ["DEFAULT_URL", "layer", "layer_socket", "layer_web_socket"]

DEFAULT_URL = "ws://localhost:34437"

layer_socket: Layer[Never, Never, Socket] = layer_tracer
"""Reports spans over the ``Socket`` provided."""


def layer_web_socket(url: str = DEFAULT_URL) -> Layer[Never, Never, WebSocketConstructor]:
    """Reports spans over a WebSocket to ``url``."""
    return layer_tracer.pipe(layer_provide(socket_layer_web_socket(url)))


def layer(url: str = DEFAULT_URL) -> Layer[Never]:
    """Reports spans over a WebSocket to ``url``, opened with the
    ``websockets`` client (the ``websockets`` extra)."""
    from pyfect.socket.ws import layer_web_socket_constructor

    return layer_web_socket(url).pipe(layer_provide(layer_web_socket_constructor))
