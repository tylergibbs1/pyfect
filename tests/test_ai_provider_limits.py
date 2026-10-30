"""The provider adapters against a server they do not control (a proxy, a
compatible server, a compromised endpoint): bodies are read under a limit,
streamed tool parameters are bounded, and the provider's secret headers
stay out of redirects and response parts."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
import json
from typing import Any, TypedDict, cast

import pytest
from oracle._ai_http import MockHttp, sse_response

import pyfect as fx
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.anthropic import client as aclient
from pyfect.ai.anthropic import language_model as alm
from pyfect.ai.openai_compat import client as oclient
from pyfect.ai.openai_compat import language_model as olm
from pyfect.http import response as http_response
from pyfect.http.client import HttpClientService
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact
from pyfect.result import Err

CHUNK = 1024


class Params(TypedDict):
    a: str


Tool = T.make("Tool", parameters=S.Struct(Params), success=S.String)
Kit = K.make(Tool)


class Counter:
    def __init__(self, chunks: int, chunk: int = CHUNK) -> None:
        self.pulled = 0
        self.chunks = chunks
        self.chunk = chunk

    def body(self) -> Any:
        def step(i: int) -> fx.Effect[tuple[bytes, int] | None]:
            def run() -> tuple[bytes, int] | None:
                if i >= self.chunks:
                    return None
                piece = (b'{"pad":"' + b"A" * (self.chunk - 8)) if i == 0 else b"A" * self.chunk
                self.pulled += len(piece)
                return piece, i + 1

            return fx.sync(run)

        return stream.unfold(0, step)

    def mock(self, status: int = 200) -> MockHttp:
        return MockHttp(
            lambda request: fx.succeed(
                http_response.make(
                    request,
                    self.body(),
                    status=status,
                    headers={"content-type": "application/json"},
                )
            )
        )


def _anthropic(effect: Any, mock: MockHttp, **options: Any) -> Any:
    return (
        effect.pipe(fx.provide(alm.model("claude-sonnet-4-20250514").layer))
        .pipe(fx.provide(aclient.layer(api_key=redact("sk-ant-secret"), **options)))
        .pipe(fx.provide(mock.layer))
    )


def _openai(effect: Any, mock: MockHttp, **options: Any) -> Any:
    return (
        effect.pipe(fx.provide(olm.model("gpt-4o-mini").layer))
        .pipe(fx.provide(oclient.layer(api_key=redact("sk-oa-secret"), **options)))
        .pipe(fx.provide(mock.layer))
    )


PROVIDERS = pytest.mark.parametrize("provide", [_anthropic, _openai], ids=["anthropic", "openai"])


def _ai_error(result: object) -> E.AiError:
    assert isinstance(result, Err), result
    error = cast("Any", result).error
    assert isinstance(error, E.AiError), error
    return error


@PROVIDERS
@testing.effect
def test_a_response_body_is_read_under_the_limit(provide: Any):
    counter = Counter(64)
    result = yield from provide(
        lm.generate_text("hi").result(), counter.mock(), max_response_bytes=CHUNK
    )
    reason = _ai_error(result).reason
    assert isinstance(reason, E.InvalidOutputError)
    assert "exceeds" in reason.description
    assert counter.pulled <= 2 * CHUNK


@PROVIDERS
@pytest.mark.parametrize("status", [400, 500])
@testing.effect
def test_an_error_body_is_read_under_a_fixed_limit(provide: Any, status: int):
    counter = Counter(64, 64 * 1024)  # 4 MiB
    result = yield from provide(lm.generate_text("hi").result(), counter.mock(status))
    _ai_error(result)
    assert counter.pulled <= 1024 * 1024 + 64 * 1024


def _anthropic_tool_stream(deltas: int) -> list[object]:
    start = {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 0},
        },
    }
    block = {"type": "tool_use", "id": "toolu_1", "name": "Tool", "input": {}}
    return [
        start,
        {"type": "content_block_start", "index": 0, "content_block": block},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"a":"'},
        },
        *(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": "A" * 100},
            }
            for _ in range(deltas)
        ),
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 1},
        },
        {"type": "message_stop"},
    ]


def _openai_chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl_1",
        "object": "chat.completion.chunk",
        "model": "gpt-4o-mini",
        "created": 1,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def _openai_tool_stream(deltas: int) -> list[object]:
    def call(arguments: str, first: bool = False) -> dict[str, Any]:
        function = {"name": "Tool", "arguments": arguments} if first else {"arguments": arguments}
        entry: dict[str, Any] = {"index": 0, "function": function}
        if first:
            entry |= {"id": "call_1", "type": "function"}
        return _openai_chunk({"tool_calls": [entry]})

    return [
        call('{"a":"', first=True),
        *(call("A" * 100) for _ in range(deltas)),
        call('"}'),
        _openai_chunk({}, "tool_calls"),
        "[DONE]",
    ]


@pytest.mark.parametrize(
    ("provide", "events"),
    [(_anthropic, _anthropic_tool_stream), (_openai, _openai_tool_stream)],
    ids=["anthropic", "openai"],
)
@testing.effect
def test_streamed_tool_params_are_bounded(provide: Any, events: Any):
    small = MockHttp(lambda request: fx.succeed(sse_response(request, events(5))))
    ok = yield from provide(
        lm.stream_text("hi", toolkit=Kit, disable_tool_call_resolution=True).run_collect().result(),
        small,
        max_response_bytes=4096,
    )
    assert not isinstance(ok, Err), ok
    big = MockHttp(lambda request: fx.succeed(sse_response(request, events(100))))
    result = yield from provide(
        lm.stream_text("hi", toolkit=Kit, disable_tool_call_resolution=True).run_collect().result(),
        big,
        max_response_bytes=4096,
    )
    reason = _ai_error(result).reason
    assert isinstance(reason, E.InvalidOutputError)
    assert "exceed" in reason.description


def _redirecting(seen: list[HttpClientRequest]) -> MockHttp:
    def handle(request: HttpClientRequest) -> Any:
        seen.append(request)
        if "evil.example" in request.url:
            return fx.succeed(http_response.make(request, "{}", status=500))
        return fx.succeed(
            http_response.make(
                request, None, status=307, headers={"location": "https://evil.example/steal"}
            )
        )

    return MockHttp(handle)


def _follow(client: HttpClientService[Any, Any]) -> HttpClientService[Any, Any]:
    return client.follow_redirects()


@pytest.mark.parametrize(
    ("provide", "options", "secrets"),
    [
        (_anthropic, {}, ["sk-ant-secret"]),
        (
            _openai,
            {"organization_id": redact("org-secret"), "project_id": redact("proj-secret")},
            ["sk-oa-secret", "org-secret", "proj-secret"],
        ),
    ],
    ids=["anthropic", "openai"],
)
@testing.effect
def test_secret_headers_do_not_follow_a_cross_origin_redirect(
    provide: Any, options: dict[str, Any], secrets: list[str]
):
    seen: list[HttpClientRequest] = []
    yield from provide(
        lm.generate_text("hi").result(), _redirecting(seen), transform_client=_follow, **options
    )
    assert len(seen) == 2
    assert "evil.example" in seen[1].url
    sent = json.dumps(dict(seen[1].headers.items()))
    for secret in secrets:
        assert secret not in sent


def _completion() -> dict[str, Any]:
    return {
        "id": "chatcmpl_1",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "created": 1,
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}
        ],
    }


@pytest.mark.parametrize("streamed", [False, True])
@testing.effect
def test_openai_secret_headers_are_redacted_in_response_metadata(streamed: bool):
    def handle(request: HttpClientRequest) -> Any:
        if streamed:
            return fx.succeed(
                sse_response(
                    request, [_openai_chunk({"content": "ok"}), _openai_chunk({}, "stop"), "[DONE]"]
                )
            )
        return fx.succeed(
            http_response.make(
                request, json.dumps(_completion()), headers={"content-type": "application/json"}
            )
        )

    run: Any = (
        lm.stream_text("hi").run_collect()
        if streamed
        else lm.generate_text("hi").map(lambda r: r.content)
    )
    parts = yield from _openai(
        run,
        MockHttp(handle),
        organization_id=redact("org-secret"),
        project_id=redact("proj-secret"),
    )
    [metadata] = [p for p in parts if isinstance(p, R.ResponseMetadataPart)]
    shown = json.dumps(metadata.request, default=str)
    assert "org-secret" not in shown
    assert "proj-secret" not in shown
    assert "sk-oa-secret" not in shown


def _clients() -> list[Any]:
    return [
        pytest.param(aclient.make, id="anthropic"),
        pytest.param(oclient.make, id="openai"),
    ]


@pytest.mark.parametrize("make", _clients())
@pytest.mark.parametrize("status", [200, 500])
@testing.effect
def test_every_client_call_reads_under_the_limit(make: Any, status: int):
    """Walks each client's ``create_*`` calls, so a new call is covered."""
    from dataclasses import fields

    built = yield from make(max_response_bytes=CHUNK).pipe(fx.provide(Counter(0).mock().layer))
    calls = [f.name for f in fields(built) if f.name.startswith("create_")]
    assert len(calls) >= 2
    for name in calls:
        counter = Counter(4096, CHUNK)  # 4 MiB
        service = yield from make(max_response_bytes=CHUNK).pipe(
            fx.provide(counter.mock(status).layer)
        )
        sent: Any = getattr(service, name)({"model": "m", "messages": []})

        def drain(value: Any) -> Any:
            streams = [v for v in value if isinstance(v, stream.Stream)]
            return streams[0].run_drain() if streams else fx.void

        result = yield from sent.flat_map(drain).result()
        _ai_error(result)
        assert counter.pulled <= 1024 * 1024 + CHUNK, name
