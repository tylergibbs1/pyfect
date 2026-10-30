# Groups made with ``HttpApiGroup.make`` type their endpoints as ``Any``.
# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""A JSON payload is read only from a request that says it is JSON: a body
with no ``Content-Type`` is a 415, so a cross-site "simple" request (a
``no-cors`` fetch of a ``Blob``) cannot reach a JSON endpoint."""

import asyncio
from typing import Any

import pytest
from oracle._http_api import struct

from pyfect import effect, layer
from pyfect import schema as S
from pyfect.http import router, server
from pyfect.http.web import WebRequest
from pyfect.http_api import builder
from pyfect.http_api import endpoint as ep
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup


def _serve(requests: list[WebRequest]) -> tuple[list[int], list[Any]]:
    group = HttpApiGroup.make("g").add(
        ep.post("transfer", "/transfer", payload=struct({"amount": S.Finite})),
        ep.post("optional", "/optional", payload=S.NullOr(struct({"amount": S.Finite}))),
    )
    api = HttpApi.make("api").add(group)
    seen: list[Any] = []

    def record(ctx: Any) -> Any:
        seen.append(ctx.payload)
        return effect.void

    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["transfer"])(record).handle(group.endpoints["optional"])(
            record
        ),
    )
    app = builder.layer(api).pipe(layer.provide(live)).pipe(layer.provide(server.layer_services))

    async def main() -> list[int]:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            return [(await made.handler(request)).status for request in requests]
        finally:
            await made.dispose()

    return asyncio.run(main()), seen


def _post(path: str, body: bytes, headers: dict[str, str]) -> WebRequest:
    return WebRequest(f"http://localhost{path}", method="POST", headers=headers, body=body)


@pytest.mark.parametrize(
    "headers", [{}, {"content-length": "12"}, {"transfer-encoding": "chunked"}]
)
def test_a_body_without_a_content_type_is_a_415(headers: dict[str, str]) -> None:
    statuses, seen = _serve([_post("/transfer", b'{"amount":1}', headers)])
    assert statuses == [415]
    assert seen == []


def test_a_json_body_is_decoded() -> None:
    request = _post("/transfer", b'{"amount":1}', {"content-type": "application/json"})
    assert _serve([request]) == ([204], [{"amount": 1}])


def test_an_empty_body_without_a_content_type_is_still_an_empty_payload() -> None:
    assert _serve([_post("/optional", b"", {"content-length": "0"})]) == ([204], [None])


def test_the_security_cookie_is_same_site_lax_by_default() -> None:
    from pyfect.http_api import security

    key = security.api_key(key="session", in_="cookie")
    group = HttpApiGroup.make("g").add(ep.post("login", "/login"))
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api,
        group,
        lambda h: h.handle(group.endpoints["login"])(
            lambda _ctx: builder.security_set_cookie(key, "v")
        ),
    )
    app = builder.layer(api).pipe(layer.provide(live)).pipe(layer.provide(server.layer_services))

    async def main() -> list[str]:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            response = await made.handler(_post("/login", b"", {}))
            return response.get_set_cookie()
        finally:
            await made.dispose()

    [cookie] = asyncio.run(main())
    assert "SameSite=Lax" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
