"""No client response is born in a reference cycle. A response releases its
connection when it is freed; one in a cycle is freed only when the cycle
collector runs, so an unread response would hold its socket until then
(``with_body_limit`` once kept its body as a closure over itself)."""

import gc
import weakref
from collections.abc import Callable

import pytest

from pyfect import byte_size
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http import server_response
from pyfect.http.response import HttpClientResponse
from pyfect.stream import succeed as succeed_stream


def _original() -> HttpClientResponse:
    return HttpClientResponse(
        req.get("http://test/"),
        200,
        res.make(req.get("http://test/")).headers,
        succeed_stream(b"ok"),
    )


def _interruptible() -> HttpClientResponse:
    return res._InterruptibleResponse(_original(), lambda: None, lambda: None)  # pyright: ignore[reportPrivateUsage]


_MAKE: dict[str, Callable[[], HttpClientResponse]] = {
    "HttpClientResponse": _original,
    "_InterruptibleResponse": _interruptible,
    "_LimitedResponse": lambda: res.with_body_limit(_interruptible(), byte_size.bytes(1024)),
    "_ServerClientResponse": lambda: server_response.to_client_response(server_response.text("ok")),
}


def _classes(cls: type[HttpClientResponse]) -> set[type[HttpClientResponse]]:
    return {cls} | {c for sub in cls.__subclasses__() for c in _classes(sub)}


def test_every_response_class_is_checked() -> None:
    """Only pyfect's classes: a test may subclass a response for itself."""
    pyfect_classes = {c for c in _classes(HttpClientResponse) if c.__module__.startswith("pyfect.")}
    assert {cls.__name__ for cls in pyfect_classes} == set(_MAKE)


@pytest.mark.parametrize("make", _MAKE.values(), ids=list(_MAKE))
def test_a_dropped_response_is_freed_at_once(make: Callable[[], HttpClientResponse]) -> None:
    gc.disable()
    try:
        response = make()
        freed = weakref.ref(response)
        del response
        assert freed() is None
    finally:
        gc.enable()
