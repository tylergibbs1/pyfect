"""Ports of Effect's ``httpapi/HttpApiDocumentation.test.ts``. Each test's
docstring is the Effect test title, prefixed by its ``describe`` block.

Effect spies on ``HttpServerResponse.jsonUnsafe`` / ``html``; these tests
count the calls of the function each module answers with.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import pytest

from pyfect import layer
from pyfect.http import router, server_response
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http_api import builder, openapi, scalar, swagger
from pyfect.http_api.api import HttpApi


def _health() -> Any:
    return router.add("GET", "/health", server_response.text("OK"))


def _counting(transforms: list[int], *, fail_first: bool = False) -> Callable[[Any], Any]:
    def transform(spec: Any) -> Any:
        transforms.append(1)
        if fail_first and len(transforms) == 1:
            raise RuntimeError("OpenAPI generation defect")
        return spec

    return transform


def _spy(monkeypatch: pytest.MonkeyPatch, module: object, name: str) -> list[int]:
    calls: list[int] = []
    original = getattr(module, name)

    def spy(*args: Any, **kwargs: Any) -> HttpServerResponse:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, spy)
    return calls


def _serve(app: Any, use: Callable[[Callable[[str], Any]], Any]) -> None:
    async def main() -> None:
        made = router.to_web_handler(app, disable_logger=True)

        async def fetch(path: str) -> WebResponse:
            return await made.handler(WebRequest(f"http://test{path}"))

        try:
            await use(fetch)
        finally:
            await made.dispose()

    asyncio.run(main())


def _render(app: Any) -> str:
    out: list[str] = []

    async def use(fetch: Callable[[str], Any]) -> None:
        response = await fetch("/docs")
        out.append(await response.text())

    _serve(app, use)
    return out[0]


def _defers_and_memoizes(app: Any, path: str, transforms: list[int], calls: list[int]) -> None:
    async def use(fetch: Callable[[str], Any]) -> None:
        health = await fetch("/health")
        assert health.status == 200
        assert transforms == []
        assert calls == []
        first = await asyncio.gather(*(fetch(path) for _ in range(20)))
        assert all(response.status == 200 for response in first)
        assert len(transforms) == 1
        assert len(calls) == 1
        cached = await fetch(path)
        assert cached.status == 200
        assert len(transforms) == 1
        assert len(calls) == 1

    _serve(layer.merge(app, _health()), use)


def _retries(app: Any, path: str, transforms: list[int]) -> None:
    async def use(fetch: Callable[[str], Any]) -> None:
        first = await fetch(path)
        assert first.status == 500
        assert len(transforms) == 1
        second = await fetch(path)
        assert second.status == 200
        assert len(transforms) == 2
        cached = await fetch(path)
        assert cached.status == 200
        assert len(transforms) == 2

    _serve(app, use)


def test_builder_defers_and_memoizes_successful_openapi_path_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HttpApiBuilder / defers and memoizes successful openapiPath responses"""
    transforms: list[int] = []
    api = HttpApi.make("OpenApiPath").annotate(openapi.Transform, _counting(transforms))
    calls = _spy(monkeypatch, builder, "json_unsafe")
    app = builder.layer(api, openapi_path="/openapi.json")
    _defers_and_memoizes(app, "/openapi.json", transforms, calls)


def test_builder_retries_openapi_path_generation_after_a_defect() -> None:
    """HttpApiBuilder / retries openapiPath generation after a defect"""
    transforms: list[int] = []
    api = HttpApi.make("OpenApiPathRecovery").annotate(
        openapi.Transform, _counting(transforms, fail_first=True)
    )
    _retries(builder.layer(api, openapi_path="/openapi.json"), "/openapi.json", transforms)


def test_scalar_defers_and_memoizes_successful_openapi_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HttpApiScalar / defers and memoizes successful OpenAPI responses"""
    transforms: list[int] = []
    api = HttpApi.make("Docs").annotate(openapi.Transform, _counting(transforms))
    calls = _spy(monkeypatch, scalar, "html")
    _defers_and_memoizes(scalar.layer_cdn(api), "/docs", transforms, calls)


def test_scalar_retries_openapi_generation_after_a_defect() -> None:
    """HttpApiScalar / retries OpenAPI generation after a defect"""
    transforms: list[int] = []
    api = HttpApi.make("ScalarRecovery").annotate(
        openapi.Transform, _counting(transforms, fail_first=True)
    )
    _retries(scalar.layer_cdn(api), "/docs", transforms)


def test_defers_inline_scalar_generation_until_the_route_is_requested() -> None:
    """HttpApiScalar / defers inline Scalar generation until the route is requested"""
    transforms: list[int] = []
    api = HttpApi.make("ScalarInline").annotate(openapi.Transform, _counting(transforms))

    async def use(fetch: Callable[[str], Any]) -> None:
        health = await fetch("/health")
        assert health.status == 200
        assert transforms == []
        docs = await fetch("/docs")
        assert docs.status == 200
        assert len(transforms) == 1

    _serve(layer.merge(scalar.layer(api), _health()), use)


def _extract_spec(html: str) -> object:
    marker = "        content: "
    start = html.index(marker)
    end = html.index("\n      })", start)
    return json.loads(html[start + len(marker) : end])


def _extract_swagger_spec(html: str) -> object:
    marker = '  <script id="swagger-spec" type="application/json">\n    '
    start = html.index(marker)
    end = html.index("\n  </script>", start)
    return json.loads(html[start + len(marker) : end])


def test_escapes_openapi_metadata_in_its_html_contexts() -> None:
    """HttpApiScalar / escapes OpenAPI metadata in its HTML contexts"""
    title = 'Docs "title" </title><script>'
    injected_tag = '<script id="script-data-injected">'
    description = f"\"quoted\" 'single' </script >{injected_tag}"
    api = (
        HttpApi.make("Docs")
        .annotate(openapi.Title, title)
        .annotate(openapi.Description, description)
    )
    html = _render(scalar.layer_cdn(api))
    assert '<title>Docs "title" &lt;/title&gt;&lt;script&gt;</title>' in html
    escaped = (
        "&quot;quoted&quot; &#39;single&#39; &lt;/script &gt;"
        "&lt;script id=&quot;script-data-injected&quot;&gt;"
    )
    assert f'<meta name="description" content="{escaped}"/>' in html
    assert f'<meta name="og:description" content="{escaped}"/>' in html
    assert "</script >" not in html
    assert _extract_spec(html) == openapi.from_api(api)


def test_encodes_cdn_versions_before_interpolating_the_script_source() -> None:
    """HttpApiScalar / encodes CDN versions before interpolating the script source"""
    version = '1.2.3"></script><script id="injected">'
    html = _render(scalar.layer_cdn(HttpApi.make("Docs"), version=version))
    encoded = quote(version, safe="-_.!~*'()")
    assert (
        f'src="https://cdn.jsdelivr.net/npm/@scalar/api-reference@{encoded}'
        '/dist/browser/standalone.min.js"'
    ) in html
    assert html.count("<script") == 2
    assert 'id="injected"' not in html


def test_swagger_defers_and_memoizes_successful_openapi_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HttpApiSwagger / defers and memoizes successful OpenAPI responses"""
    transforms: list[int] = []
    api = HttpApi.make("Docs").annotate(openapi.Transform, _counting(transforms))
    calls = _spy(monkeypatch, swagger, "html")
    _defers_and_memoizes(swagger.layer(api), "/docs", transforms, calls)


def test_swagger_retries_openapi_generation_after_a_defect() -> None:
    """HttpApiSwagger / retries OpenAPI generation after a defect"""
    transforms: list[int] = []
    api = HttpApi.make("SwaggerRecovery").annotate(
        openapi.Transform, _counting(transforms, fail_first=True)
    )
    _retries(swagger.layer(api), "/docs", transforms)


def test_escapes_script_end_tag_variants_in_openapi_data() -> None:
    """HttpApiSwagger / escapes script end-tag variants in OpenAPI data"""
    injected_tag = '<script id="script-data-injected">'
    api = HttpApi.make("Docs").annotate(openapi.Description, f"</script/>{injected_tag}")
    html = _render(swagger.layer(api))
    assert "</script/>" not in html
    assert _extract_swagger_spec(html) == openapi.from_api(api)
