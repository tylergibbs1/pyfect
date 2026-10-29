"""Swagger UI for an ``HttpApi`` (Effect's ``HttpApiSwagger``)::

    app = builder.layer(api).pipe(layer.merge(swagger.layer(api)))

serves the API's OpenAPI document in Swagger UI at ``GET /docs``. The page
bundles Swagger UI, so it needs no network; it is made on the first
request and kept.
"""

from __future__ import annotations

from typing import Any, Never

from pyfect._core import Effect
from pyfect.effect import sync
from pyfect.http.router import HttpRouter, HttpRouterService, use
from pyfect.http.server_response import HttpServerResponse, html
from pyfect.http_api import _html
from pyfect.http_api.api import HttpApi
from pyfect.layer import Layer


def _page(api: HttpApi[Any], javascript: str, css: str) -> HttpServerResponse:
    from pyfect.http_api import openapi

    spec = openapi.from_api(api)
    return html(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_html.escape(spec["info"]["title"])} Documentation</title>
  <style>{css}</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script id="swagger-spec" type="application/json">
    {_html.escape_json(spec)}
  </script>
  <script>
    {javascript}
    window.onload = () => {{
      window.ui = SwaggerUIBundle({{
        spec: JSON.parse(document.getElementById("swagger-spec").textContent),
        dom_id: "#swagger-ui",
      }});
    }};
  </script>
</body>
</html>""")


def layer(api: HttpApi[Any], *, path: str = "/docs") -> Layer[Never, Never, HttpRouter]:
    """``GET path`` answering with Swagger UI for ``api``."""

    def add(router: HttpRouterService) -> Effect[None]:
        def with_assets(assets: tuple[str, str]) -> Effect[None]:
            javascript, css = assets
            page = _html.memoize_success(lambda: _page(api, javascript, css))
            return router.add("GET", path, sync(page))

        return sync(lambda: (_html.asset("swagger-ui.js"), _html.asset("swagger-ui.css"))).flat_map(
            with_assets
        )

    return use(add)


__all__ = ["layer"]
