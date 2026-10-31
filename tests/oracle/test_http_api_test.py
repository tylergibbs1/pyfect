"""Ports of Effect's ``httpapi/HttpApiTest.test.ts``. Each test's docstring
is the Effect test title, prefixed by its ``describe`` block."""

from typing import Any

import pyfect as fx
from pyfect import effect, scope, stream
from pyfect import schema as S
from pyfect.exit import Failure
from pyfect.http.server_error import HttpServerError, RequestParseError
from pyfect.http_api import builder, get_group
from pyfect.http_api import endpoint as ep
from pyfect.http_api import schema as api_schema
from pyfect.http_api import test as api_test
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.stream import Stream


def _run[A](program: fx.Effect[A, Any, Any]) -> A:
    return fx.run_sync(scope.scoped(program))


def test_passes_each_payload_element_through_before_the_source_produces_the_next() -> None:
    """HttpApiTest streaming / passes each payload element through before the source produces the next"""  # noqa: E501

    class Test(HttpApiGroup, identifier="test"):
        upload = ep.post(
            "upload",
            "/upload",
            payload=api_schema.StreamNdjson(S.Finite),
            success=S.Array(S.Finite),
        )

    api = HttpApi.make("Api").add(Test)
    first = fx.Deferred[None]()
    second = fx.Deferred[None]()
    seen: list[float] = []

    def record(n: float) -> fx.Effect[bool]:
        seen.append(n)
        return (first if n == 1 else second).succeed(None)

    group = builder.group(
        api,
        Test,
        lambda h: h.handle(Test.upload)(
            lambda request: request.payload.tap(record).run_collect().map(tuple)
        ),
    )

    def program() -> Any:
        client = yield from api_test.groups(api, (Test,)).pipe(fx.provide(group))
        source = (
            stream.make(1.0)
            .concat(stream.from_effect(first.wait().as_(2.0)))
            .concat(stream.from_effect(second.wait().as_(3.0)))
        )
        response = yield from get_group(client, Test).upload(payload=source)
        assert seen == [1, 2, 3]
        assert list(response) == [1, 2, 3]

    _run(effect.gen(program))


def test_dies_with_the_body_read_failure_when_the_payload_source_fails() -> None:
    """HttpApiTest streaming / dies with the body read failure when the payload source fails"""

    class Test(HttpApiGroup, identifier="test"):
        upload = ep.post("upload", "/upload", payload=api_schema.StreamUint8Array())

    api = HttpApi.make("Api").add(Test)
    group = builder.group(
        api, Test, lambda h: h.handle(Test.upload)(lambda request: request.payload.run_drain())
    )

    def program() -> Any:
        client = yield from api_test.groups(api, (Test,)).pipe(fx.provide(group))
        source = stream.make(b"\x01").concat(stream.fail("SourceError"))
        exit_ = yield from get_group(client, Test).upload(payload=source).exit()
        assert isinstance(exit_, Failure)
        error = exit_.cause.squash()
        assert isinstance(error, HttpServerError), f"Expected HttpServerError, got {error!r}"
        assert isinstance(error.reason, RequestParseError)

    _run(effect.gen(program))


def test_keeps_handler_resources_alive_after_the_call_until_the_response_stream_finishes() -> None:
    """HttpApiTest streaming / keeps handler resources alive after the call until the response stream finishes"""  # noqa: E501

    class Test(HttpApiGroup, identifier="test"):
        download = ep.get("download", "/download", success=api_schema.StreamUint8Array())

    api = HttpApi.make("Api").add(Test)
    closed = False

    def close() -> None:
        nonlocal closed
        closed = True

    def chunk() -> bytes:
        assert not closed
        return b"\x01\x02\x03"

    def handler(_request: object) -> fx.Effect[Stream[bytes]]:
        def run() -> Any:
            yield from scope.add_finalizer(lambda _exit: effect.sync(close))
            return stream.from_effect(effect.sync(chunk))

        return effect.gen(run)

    group = builder.group(api, Test, lambda h: h.handle(Test.download)(handler))

    def program() -> Any:
        client = yield from api_test.groups(api, (Test,)).pipe(fx.provide(group))
        response = yield from get_group(client, Test).download()
        assert not closed
        chunks = yield from response.run_collect()
        assert list(chunks) == [b"\x01\x02\x03"]
        assert closed

    _run(effect.gen(program))
