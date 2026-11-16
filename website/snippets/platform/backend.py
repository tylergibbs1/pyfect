import threading
from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect.http import client
from pyfect.http import response as res
from pyfect.http.abort import AbortSignal
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest

type Response = fx.Effect[res.HttpClientResponse, HttpClientError]


def send(request: HttpClientRequest, url: fx.Url, signal: AbortSignal, _fiber: Any) -> Response:
    """A transport answering on a timer thread: /slow takes five seconds."""
    delay = 5 if url.pathname == "/slow" else 0

    def register(resume: Callable[[Response], None]) -> None:
        timer = threading.Timer(delay, lambda: resume(fx.succeed(res.make(request, "pong"))))

        def abort() -> None:
            timer.cancel()
            print("aborted", url.pathname)

        # The signal fires when the request is interrupted: stop the work it started.
        signal.add_listener(abort)
        timer.start()

    return fx.callback(register)


@fx.fn
def program():
    http = client.make(send)
    reply = yield from http.get("http://backend/fast").flat_map(lambda r: r.text)
    print("fast", reply)
    late = yield from http.get("http://backend/slow").timeout("50 millis").option()
    print("slow", late)


fx.run_main(program())
