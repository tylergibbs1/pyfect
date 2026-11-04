"""A stand-in ClickHouse HTTP server for the clickhouse driver's tests
(Effect's ``vi.mock("@clickhouse/client")``): an ``HttpClient`` answering
from functions, given to the client as its ``http_client``.

Requests are told apart as ``@clickhouse/client`` sends them: ``GET
/ping``; an insert (its ``query`` in the URL); a query (its body ends with
``FORMAT <name>``); anything else a command. ``ping``, ``query`` and
``insert`` answer each; ``None`` never answers. Commands answer at once and
are recorded with their parameters.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect.http import body as http_body
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.abort import AbortSignal
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.sql import clickhouse

type Answer = Callable[["Call"], fx.Effect[HttpClientResponse, HttpClientError]] | None

_FORMAT = re.compile(r"\s+FORMAT (\w+)$")


@dataclass(frozen=True)
class Call:
    """One request: its SQL, ``param_`` values and settings."""

    request: HttpClientRequest
    signal: AbortSignal
    sql: str
    params: dict[str, str]
    url_params: dict[str, str]

    @property
    def format(self) -> str | None:
        found = _FORMAT.search(self.sql)
        return None if found is None else found.group(1)

    def answer(
        self, body: str | bytes = "", *, status: int = 200, headers: dict[str, str] | None = None
    ) -> fx.Effect[HttpClientResponse, HttpClientError]:
        return fx.succeed(http_response.make(self.request, body, status=status, headers=headers))

    def error(
        self, code: int, message: str = "boom"
    ) -> fx.Effect[HttpClientResponse, HttpClientError]:
        text = f"Code: {code}. DB::Exception: {message}. (SOME_ERROR) (version 25.1)"
        return self.answer(text, status=500, headers={"x-clickhouse-exception-code": str(code)})


def _text(request: HttpClientRequest) -> str:
    body = request.body
    return body.body.decode() if isinstance(body, http_body.Bytes) else ""


@dataclass
class FakeClickhouse:
    ping: Answer = field(default=lambda call: call.answer("Ok.\n"))
    query: Answer = field(default=lambda call: call.answer('{"data": []}'))
    insert: Answer = field(default=lambda call: call.answer(""))
    calls: list[Call] = field(default_factory=list[Call])
    commands: list[Call] = field(default_factory=list[Call])
    inserts: list[Call] = field(default_factory=list[Call])

    def send(
        self, request: HttpClientRequest, _url: Any, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[HttpClientResponse, HttpClientError]:
        url_params = {key: str(value) for key, value in request.url_params}
        call = Call(
            request,
            signal,
            url_params.get("query") or _text(request),
            {k.removeprefix("param_"): v for k, v in url_params.items() if k.startswith("param_")},
            url_params,
        )
        self.calls.append(call)
        if request.url.endswith("/ping"):
            answer = self.ping
        elif "query" in url_params:
            self.inserts.append(call)
            answer = self.insert
        elif call.format is not None:
            answer = self.query
        else:
            self.commands.append(call)
            return call.answer("")
        return fx.never if answer is None else answer(call)

    @property
    def http_client(self) -> http_client.HttpClientService[HttpClientError]:
        return http_client.make(self.send)

    def config(self, **fields: Any) -> clickhouse.ClickhouseClientConfig:
        fields.setdefault("http_client", self.http_client)
        return clickhouse.ClickhouseClientConfig(url="http://localhost:8123", **fields)


__all__ = ["Call", "FakeClickhouse"]
