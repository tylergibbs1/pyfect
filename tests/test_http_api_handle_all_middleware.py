"""``handle_all`` with ``builder.entry`` values serves an endpoint that has
middleware of its own as ``handle`` does: the group layer needs the
middleware and what the middleware needs, and the handler gets what the
middleware provides."""

from typing import Any, Never, assert_type

from oracle._http_api import api_layer, run_served

import pyfect as fx
from pyfect import effect, layer
from pyfect import schema as S
from pyfect.context import Tag
from pyfect.http import client as http_client
from pyfect.http_api import builder
from pyfect.http_api import endpoint as ep
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware, MiddlewareOptions


class Sessions(Tag[int], key="test/HandleAllMiddleware/Sessions"): ...


class CurrentUser(Tag[str], key="test/HandleAllMiddleware/CurrentUser"): ...


class Session(
    HttpApiMiddleware[CurrentUser, Never, Sessions], key="test/HandleAllMiddleware/Session"
): ...


class Users(HttpApiGroup, identifier="users"):
    me = ep.get("me", "/me", success=S.String).middleware(Session)


def _session(
    handler: fx.Effect[Any, Any, Any], _options: MiddlewareOptions
) -> fx.Effect[Any, Any, Any]:
    return Sessions().flat_map(lambda n: handler.pipe(fx.provide_service(CurrentUser, f"user-{n}")))


_API = HttpApi.make("api").add(Users)
_USERS = builder.group(
    _API, Users, lambda h: h.handle_all(builder.entry(Users.me)(lambda _r: CurrentUser()))
)


def _get_me() -> Any:
    def program() -> Any:
        response = yield from http_client.get("/me")
        return response.status, (yield from response.text)

    return effect.gen(program)


def test_the_layer_needs_the_middleware_and_what_it_needs_not_what_it_provides() -> None:
    assert_type(_USERS, fx.Layer[Users, Never, Session | Sessions])
    app = api_layer(_API, _USERS, layer.succeed(Session, _session), layer.succeed(Sessions, 7))
    assert run_served(app, _get_me()) == (200, '"user-7"')


def test_without_what_the_middleware_needs_a_request_fails() -> None:
    # The same app as above, less Sessions: the middleware can't run.
    app = api_layer(_API, _USERS, layer.succeed(Session, _session))
    assert run_served(app, _get_me()) == (500, "")
