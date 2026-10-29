"""``http_api.client.endpoint`` and ``group``: each run of the effect they
return builds its client from that run's services."""

from typing import Any

import pyfect as fx
from pyfect import effect
from pyfect.http import response
from pyfect.http.client import HttpClientService
from pyfect.http.client import make as make_http_client
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http_api import client
from pyfect.http_api import endpoint as ep
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup

_GROUP = HttpApiGroup.make("test").add(ep.get("health", "/health"))
_API = HttpApi.make("Api").add(_GROUP)


def _recording(name: str, sent: list[str]) -> HttpClientService[Any]:
    def send(request: HttpClientRequest, *_: Any) -> fx.Effect[HttpClientResponse]:
        def answer() -> HttpClientResponse:
            sent.append(name)
            return response.make(request, status=204)

        return effect.sync(answer)

    return make_http_client(send)


def test_each_run_of_endpoint_makes_a_client_of_its_own() -> None:
    sent: list[str] = []
    health = _GROUP.endpoints["health"]

    def program() -> Any:
        for name in ("first", "second"):
            method = yield from client.endpoint(
                _API, _GROUP, health, http_client=_recording(name, sent), base_url="http://test"
            )
            yield from method.response_only()

    fx.run_sync(effect.gen(program))
    assert sent == ["first", "second"]


def test_a_reused_endpoint_effect_builds_a_new_client_each_run() -> None:
    """Each run reads its own services (the client middleware provided),
    so a client built by an earlier run must not be handed out again."""
    sent: list[str] = []
    made = client.endpoint(
        _API, _GROUP, _GROUP.endpoints["health"], http_client=_recording("only", sent)
    )
    first = fx.run_sync(made)
    second = fx.run_sync(made)
    assert first is not second
