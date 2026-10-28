"""ASGI: HTTP apps on any ASGI 3 server, and ASGI applications inside
apps.

``to_asgi(app, layer)`` is an ASGI application for uvicorn, hypercorn,
granian or a host framework (FastAPI's ``app.mount``). Its ``lifespan``
scope builds the layer in a ``ManagedRuntime`` and releases it at
shutdown; each request runs on its own fiber on the server's loop::

    app = router.to_http_effect(routes)
    asgi_app = asgi.to_asgi(app, services)  # uvicorn module:asgi_app

Request bodies are streams that wait for the client; streamed responses
are sent chunk by chunk; a client disconnect interrupts the request (a
client abort, 499) and stops its body. A ``websocket`` scope is a ``GET``
request whose ``upgrade`` is a WebSocket ``Socket`` (``request.upgrade``
accepts it); an app that does not upgrade answers with its response.
Under a host framework's ``Mount``, ``root_path`` is removed from the
request's URL. Host frameworks send no lifespan to mounted apps: pass
``asgi_app.lifespan()`` to the host's own (``FastAPI(lifespan=lambda _:
asgi_app.lifespan())``).

``router.to_asgi(routes)`` serves a router's routes the same way.

The other way round, ``from_asgi(fastapi_app)`` is an app answering with
another framework's application, mountable under a router prefix
(``root_path`` is the prefix), and ``lifespan(fastapi_app)`` runs its
startup and shutdown in a scope. ``pyfect.http.uvicorn_server`` serves an
app on a port with uvicorn (extra ``pyfect[server]``).
"""

from pyfect.http.asgi._app import AsgiApp, to_asgi, to_asgi_with
from pyfect.http.asgi._http import HIGH_WATER_MARK, ClientDisconnectedError
from pyfect.http.asgi._mount import AsgiLifespanError, AsgiNoResponseError, from_asgi, lifespan
from pyfect.http.asgi._serve import AsgiHandler, UnsupportedScopeError
from pyfect.http.asgi._types import AsgiApplication, Message, Receive, Scope, Send
from pyfect.http.asgi._web_socket import AsgiWebSocket

__all__ = [
    "HIGH_WATER_MARK",
    "AsgiApp",
    "AsgiApplication",
    "AsgiHandler",
    "AsgiLifespanError",
    "AsgiNoResponseError",
    "AsgiWebSocket",
    "ClientDisconnectedError",
    "Message",
    "Receive",
    "Scope",
    "Send",
    "UnsupportedScopeError",
    "from_asgi",
    "lifespan",
    "to_asgi",
    "to_asgi_with",
]
