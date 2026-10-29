"""Typed HTTP APIs (Effect's ``effect/http-api``): declare endpoints once,
serve them, call them with a derived client and document them with
OpenAPI.

- ``endpoint``: ``get`` / ``post`` / ... make an ``HttpApiEndpoint`` from
  its path and the schemas of its params, query, payload, headers,
  successes and errors
- ``group``: ``HttpApiGroup``, a class whose attributes are endpoints
- ``api``: ``HttpApi``, groups under one identifier
- ``builder``: ``group(api, Users, build)`` is the layer of a group's
  handlers, ``layer(api)`` adds every group's routes to the router
- ``client``: ``make(api)`` derives a client whose methods are typed by
  the declarations; ``test``: one calling the handlers in memory
- ``schema``: response statuses, encodings, streams (SSE, NDJSON,
  bytes), upgrades and response headers; ``error``: the status errors
- ``middleware``, ``security``: ``HttpApiMiddleware`` and the
  credentials it decodes (bearer, basic, API keys)
- ``openapi``: the OpenAPI 3.1 document of an API; ``swagger`` and
  ``scalar`` serve it as documentation pages

::

    class Users(HttpApiGroup, identifier="users"):
        get_user = endpoint.get(
            "getUser", "/users/:id", params=S.Struct(UserParams), success=User, error=NotFound
        )

    api = HttpApi.make("app").add(Users)
    UsersLive = builder.group(api, Users, lambda h: h.handle(Users.get_user)(get_user))
    user = yield from client[Users].get_user(params={"id": 1})
"""

from pyfect.http_api import (
    api,
    builder,
    client,
    endpoint,
    error,
    group,
    middleware,
    openapi,
    scalar,
    schema,
    security,
    swagger,
    test,
)
from pyfect.http_api._handlers import Handlers, HttpApiRequest
from pyfect.http_api.api import HttpApi
from pyfect.http_api.client import Client
from pyfect.http_api.endpoint import HttpApiEndpoint
from pyfect.http_api.error import HttpApiPayloadTooLarge, HttpApiSchemaError
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware
from pyfect.http_api.security import HttpApiSecurity

__all__ = [
    "Client",
    "Handlers",
    "HttpApi",
    "HttpApiEndpoint",
    "HttpApiGroup",
    "HttpApiMiddleware",
    "HttpApiPayloadTooLarge",
    "HttpApiRequest",
    "HttpApiSchemaError",
    "HttpApiSecurity",
    "api",
    "builder",
    "client",
    "endpoint",
    "error",
    "group",
    "middleware",
    "openapi",
    "scalar",
    "schema",
    "security",
    "swagger",
    "test",
]
