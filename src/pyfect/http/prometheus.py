"""The metrics registry over HTTP (Effect's ``PrometheusMetrics.layerHttp``).
Add ``layer_http()`` to an app's routes for a Prometheus scrape endpoint."""

from __future__ import annotations

from typing import Never

from pyfect.http import router
from pyfect.http import server_response as response
from pyfect.http.router import HttpRouter
from pyfect.layer import Layer
from pyfect.metric import MetricNameMapper, prometheus_format


def layer_http(
    *,
    path: str = "/metrics",
    prefix: str | None = None,
    metric_name_mapper: MetricNameMapper | None = None,
) -> Layer[Never, Never, HttpRouter]:
    """A ``GET`` route at ``path`` answering with ``prometheus_format``."""
    text = prometheus_format(prefix=prefix, metric_name_mapper=metric_name_mapper)
    return router.add(
        "GET",
        path,
        text.map(
            lambda body: response.text(
                body, content_type="text/plain; version=0.0.4; charset=utf-8"
            )
        ),
    )


__all__ = ["layer_http"]
