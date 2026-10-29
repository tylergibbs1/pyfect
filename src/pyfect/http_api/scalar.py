"""Scalar API reference for an ``HttpApi`` (Effect's ``HttpApiScalar``):
``layer(api)`` serves it at ``GET /docs`` with Scalar bundled,
``layer_cdn(api)`` loads Scalar from jsDelivr. The page is made on the
first request and kept.
"""

from __future__ import annotations

from typing import Any, Literal, Never, TypedDict
from urllib.parse import quote

from pyfect._core import Effect
from pyfect.effect import sync
from pyfect.http.router import HttpRouter, HttpRouterService, use
from pyfect.http.server_response import HttpServerResponse, html
from pyfect.http_api import _html
from pyfect.http_api.api import HttpApi
from pyfect.layer import Layer

type ScalarThemeId = Literal[
    "alternate",
    "default",
    "moon",
    "purple",
    "solarized",
    "bluePlanet",
    "saturn",
    "kepler",
    "mars",
    "deepSpace",
    "laserwave",
    "none",
]


class ScalarAuthentication(TypedDict, total=False):
    preferredSecurityScheme: str | list[str | list[str]] | None


class ScalarConfig(TypedDict, total=False):
    """Scalar's configuration, by Scalar's own option names. ``customFetch``
    is a JavaScript function expression, written into the page as code."""

    theme: ScalarThemeId
    layout: Literal["modern", "classic"]
    proxyUrl: str
    authentication: ScalarAuthentication
    customFetch: str
    showSidebar: bool
    hideModels: bool
    hideTestRequestButton: bool
    hideSearch: bool
    darkMode: bool
    forceDarkModeState: Literal["dark", "light"]
    hideDarkModeToggle: bool
    favicon: str
    customCss: str
    baseServerURL: str
    withDefaultFonts: bool
    defaultOpenAllTags: bool
    showOperationId: bool


def _page(api: HttpApi[Any], script: str, config: ScalarConfig | None) -> HttpServerResponse:
    from pyfect.http_api import openapi

    spec = openapi.from_api(api)
    options: dict[str, Any] = dict(config or {})
    custom_fetch = options.pop("customFetch", None)
    scalar_config = {"_integration": "html", **options}
    info = spec["info"]
    description = info.get("description")
    meta = (
        ("", "")
        if not description
        else (
            f'<meta name="description" content="{_html.escape_attribute(description)}"/>',
            f'<meta name="og:description" content="{_html.escape_attribute(description)}"/>',
        )
    )
    fetch = "" if custom_fetch is None else f",\n        customFetch: {custom_fetch}"
    return html(f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>{_html.escape(info["title"])}</title>
    {meta[0]}
    {meta[1]}
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <div id="api-reference-container"></div>
    {script}
    <script>
      window.Scalar.createApiReference(document.getElementById('api-reference-container'), {{
        ...{_html.escape_json(scalar_config)},
        content: {_html.escape_json(spec)}{fetch}
      }})
    </script>
  </body>
</html>""")


def _serve(
    api: HttpApi[Any], path: str, script: Effect[str], config: ScalarConfig | None
) -> Layer[Never, Never, HttpRouter]:
    def add(router: HttpRouterService) -> Effect[None]:
        def with_script(source: str) -> Effect[None]:
            page = _html.memoize_success(lambda: _page(api, source, config))
            return router.add("GET", path, sync(page))

        return script.flat_map(with_script)

    return use(add)


def layer(
    api: HttpApi[Any], *, path: str = "/docs", scalar: ScalarConfig | None = None
) -> Layer[Never, Never, HttpRouter]:
    """``GET path`` answering with the Scalar reference of ``api``, Scalar
    bundled in the page."""
    return _serve(api, path, sync(lambda: f"<script>{_html.asset('scalar.js')}</script>"), scalar)


def layer_cdn(
    api: HttpApi[Any],
    *,
    path: str = "/docs",
    scalar: ScalarConfig | None = None,
    version: str = "latest",
) -> Layer[Never, Never, HttpRouter]:
    """``layer`` loading Scalar ``version`` from jsDelivr."""
    source = (
        "https://cdn.jsdelivr.net/npm/@scalar/api-reference@"
        f"{quote(version, safe="-_.!~*'()")}/dist/browser/standalone.min.js"
    )
    script = f'<script src="{_html.escape_attribute(source)}" crossorigin></script>'
    return _serve(api, path, sync(lambda: script), scalar)


__all__ = ["ScalarAuthentication", "ScalarConfig", "ScalarThemeId", "layer", "layer_cdn"]
