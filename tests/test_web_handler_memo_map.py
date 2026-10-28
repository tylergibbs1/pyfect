"""``memo_map`` for web handlers (Effect's ``toWebHandler`` /
``HttpEffect.toWebHandlerLayerWith`` option): handlers built with one
``MemoMap`` share the layers they have in common."""

import asyncio

from pyfect import effect, layer
from pyfect.context import Tag
from pyfect.http import router, server_response
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import WebHandlerLayer, to_web_handler_layer
from pyfect.layer import MemoMap


class Shared(Tag[int]): ...


def _counting() -> tuple[list[int], layer.Layer[Shared]]:
    builds: list[int] = []

    def build() -> int:
        builds.append(len(builds))
        return len(builds)

    return builds, layer.effect(Shared, effect.sync(build))


def _route(shared: layer.Layer[Shared]):
    """A route whose handler uses the ``Shared`` the app layer builds."""
    app = router.add("GET", "/", Shared().map(lambda n: server_response.text(str(n))))
    return app.pipe(layer.provide_merge(shared))


async def _bodies(*handlers: WebHandlerLayer) -> list[str]:
    try:
        responses = [await made.handler(WebRequest("http://localhost/")) for made in handlers]
        return [await response.text() for response in responses]
    finally:
        for made in handlers:
            await made.dispose()


def test_router_web_handlers_with_one_memo_map_share_layers() -> None:
    builds, shared = _counting()

    async def main() -> list[str]:
        memo_map = MemoMap()
        # The router layer is shared too, so the app layer adds its routes once.
        app = _route(shared)
        first = router.to_web_handler(app, disable_logger=True, memo_map=memo_map)
        second = router.to_web_handler(app, disable_logger=True, memo_map=memo_map)
        return await _bodies(first, second)

    assert asyncio.run(main()) == ["1", "1"]
    assert builds == [0]


def test_router_web_handlers_without_a_memo_map_build_their_own() -> None:
    builds, shared = _counting()

    async def main() -> list[str]:
        first = router.to_web_handler(_route(shared), disable_logger=True)
        second = router.to_web_handler(_route(shared), disable_logger=True)
        return await _bodies(first, second)

    assert asyncio.run(main()) == ["1", "2"]
    assert builds == [0, 1]


def test_web_handler_layers_with_one_memo_map_share_layers() -> None:
    builds, shared = _counting()
    app = Shared().map(lambda n: server_response.text(str(n)))

    async def main() -> list[str]:
        memo_map = MemoMap()
        first = to_web_handler_layer(app, shared, memo_map=memo_map)
        second = to_web_handler_layer(app, shared, memo_map=memo_map)
        return await _bodies(first, second)

    assert asyncio.run(main()) == ["1", "1"]
    assert builds == [0]
