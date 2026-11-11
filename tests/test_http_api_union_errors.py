"""An error schema given as ``S.Union(...)`` is one schema: its status is
the union's own (500 unless the union is annotated), not its members'. A
tuple lists the schemas one by one, each with its status. Middleware and
endpoints alike, as in Effect 4.1.2: the statuses and bodies below were
printed by Effect's ``HttpApiBuilder`` under Node for the same API (dogfood
ledger #7, where a middleware's ``error = S.Union(...)`` answered 500)."""

from typing import Any, Never

import pytest
from oracle._http_api import respond

from pyfect import effect, layer
from pyfect import schema as S
from pyfect.exit import Success
from pyfect.http.web import WebRequest
from pyfect.http_api import builder
from pyfect.http_api import endpoint as ep
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware


class Unauthorized(S.TaggedError, annotations={"http_api_status": 401}): ...


class Forbidden(S.TaggedError, annotations={"http_api_status": 403}): ...


def _respond(error: Any, failure: object, *, on: str) -> tuple[int, str]:
    class Auth(HttpApiMiddleware[Never, Any], key=f"UnionErrors/{on}"):
        pass

    on_endpoint = on == "endpoint"
    if not on_endpoint:
        Auth.error = error
    get = ep.get("get", "/x", success=S.String, **({"error": error} if on_endpoint else {}))
    group = HttpApiGroup.make("g").add(get.middleware(Auth))
    api = HttpApi.make("Api").add(group)

    def handle(_request: object) -> Any:
        return effect.fail(failure) if on_endpoint else effect.succeed("ok")

    handlers = builder.group(api, group, lambda h: h.handle(group.endpoints["get"])(handle))
    auth = layer.succeed(Auth, lambda eff, _o: eff if on_endpoint else effect.fail(failure))
    exit_ = respond(api, handlers.pipe(layer.provide_merge(auth)), WebRequest("http://localhost/x"))
    assert isinstance(exit_, Success)
    return exit_.value.status, exit_.value.body.text


UNAUTHORIZED = '{"_tag":"Unauthorized"}'
FORBIDDEN = '{"_tag":"Forbidden"}'


@pytest.mark.parametrize("on", ["middleware", "endpoint"])
def test_a_tuple_of_error_schemas_answers_each_members_status(on: str):
    assert _respond((Unauthorized, Forbidden), Unauthorized(), on=on) == (401, UNAUTHORIZED)
    assert _respond((Unauthorized, Forbidden), Forbidden(), on=on) == (403, FORBIDDEN)


@pytest.mark.parametrize("on", ["middleware", "endpoint"])
def test_a_union_error_schema_answers_the_unions_status(on: str):
    union = S.Union(Unauthorized, Forbidden)
    assert _respond(union, Unauthorized(), on=on) == (500, UNAUTHORIZED)
    assert _respond(union, Forbidden(), on=on) == (500, FORBIDDEN)
    annotated = api_schema.status(401)(S.Union(Unauthorized, Forbidden))
    assert _respond(annotated, Forbidden(), on=on) == (401, FORBIDDEN)
