"""A response the program is done with is freed, whatever its request sent.

The soak (tests/soak) found every response to a streamed upload stayed in memory with its
request, span and connection objects, about eight a second under its load. The client
kept each response's abort in a module-wide ``WeakKeyDictionary``, and the abort reached
the response again (the upload body's abort listener holds the request's context, whose
span ended with the response), so the entry never went away. The finalizer that aborts
an unread response held the same chain, so it never ran. The abort is now an attribute of
the response, the upload body's listener goes once the body is done, and no weak-keyed
table in ``pyfect.http`` remains (``test_responses_are_not_kept_in_weak_keyed_tables``).
"""

from __future__ import annotations

import gc
import re
import weakref
from pathlib import Path

import httpx

import pyfect as fx
from pyfect import stream
from pyfect.http import body, httpx_client
from pyfect.http.client import HttpClient
from pyfect.http.response import HttpClientResponse

_HTTP = Path(__file__).resolve().parents[1] / "src" / "pyfect" / "http"


async def _count_body(sent: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=str(len(await sent.aread())).encode())


def _responses_left(
    send: fx.Effect[HttpClientResponse, object, HttpClient], *, read: bool = True
) -> int:
    """Responses still in memory after twenty requests, or finalizers still registered
    for them."""
    refs: list[weakref.ref[HttpClientResponse]] = []
    finalizers = _finalizers()

    @fx.fn
    def once():
        response = yield from send
        refs.append(weakref.ref(response))
        if read:
            yield from response.text

    http = httpx_client.layer_with(transport=httpx.MockTransport(_count_body))
    fx.run_blocking(fx.for_each(range(20), lambda _: once()).pipe(fx.provide(http)).or_die())
    gc.collect()
    return max(sum(ref() is not None for ref in refs), _finalizers() - finalizers)


def _finalizers() -> int:
    """``weakref.finalize`` callbacks waiting for their object to die."""
    registry: dict[object, object] = getattr(weakref.finalize, "_registry")  # noqa: B009
    return len(registry)


def test_the_response_to_a_streamed_upload_is_freed() -> None:
    chunks = stream.make(b"ab", b"cd")
    send = HttpClient().flat_map(
        lambda client: client.post("http://test/", body=body.stream(chunks))
    )
    assert _responses_left(send) == 0


def test_an_unread_response_to_a_streamed_upload_is_freed() -> None:
    """Its finalizer (which aborts the request) must not keep it alive itself."""
    chunks = stream.make(b"ab", b"cd")
    send = HttpClient().flat_map(
        lambda client: client.post("http://test/", body=body.stream(chunks))
    )
    assert _responses_left(send, read=False) == 0


def test_the_response_to_a_plain_request_is_freed() -> None:
    send = HttpClient().flat_map(lambda client: client.post("http://test/", body=body.text("x")))
    assert _responses_left(send) == 0


def test_responses_are_not_kept_in_weak_keyed_tables() -> None:
    """A value that reaches its own key keeps a ``WeakKeyDictionary`` entry forever;
    per-response state belongs on the response."""
    users = sorted(
        path.relative_to(_HTTP).as_posix()
        for path in _HTTP.rglob("*.py")
        if re.search(r"WeakKeyDictionary|WeakValueDictionary", path.read_text())
    )
    assert users == []
