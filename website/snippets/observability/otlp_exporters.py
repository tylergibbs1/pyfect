import json
from typing import Any

import pyfect as fx
from pyfect import layer
from pyfect.http import client, response
from pyfect.http.body import Bytes
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.observability import otlp, otlp_exporter

# A collector that records what it is sent. In production, provide a real
# client (`pyfect.http.httpx_client.layer`) and point base_url at the collector.
sent: dict[str, Any] = {}


def post(requests: fx.Effect[HttpClientRequest, Any, Any]):
    def record(request: HttpClientRequest) -> HttpClientResponse:
        assert isinstance(request.body, Bytes)
        sent[request.url] = json.loads(request.body.body)
        return response.make(request)

    return requests.map(record)


collector = layer.succeed(HttpClient, client.make_with(post, fx.succeed))

telemetry = otlp.layer_json(
    base_url="http://localhost:4318",
    resource={"service_name": "atlas", "service_version": "1.0.0"},
    logger_merge_with_existing=False,  # export logs instead of printing them too
).pipe(layer.provide(collector))


@fx.gen
def program():
    yield from fx.log_info("looking up").with_span("GET /ask")
    # Export now instead of waiting for the next interval.
    yield from (yield from otlp_exporter.Flusher()).flush


fx.run_blocking(program.pipe(fx.provide(telemetry)))

traces = sent["http://localhost:4318/v1/traces"]
assert traces["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] == "GET /ask"
logs = sent["http://localhost:4318/v1/logs"]
assert logs["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"] == {
    "stringValue": "looking up"
}
