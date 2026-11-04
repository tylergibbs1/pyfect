import pyfect as fx
from pyfect.http import client, request
from pyfect.http.client import HttpClient
from pyfect.http.error import HttpClientError, TransportError


# A stand-in network that refuses every connection, as a server that is down.
def refuse(req: request.HttpClientRequest):
    cause = ConnectionRefusedError(61, "Connection refused")
    return fx.fail(HttpClientError(TransportError(req, cause)))


@fx.fn
def fetch():
    http = (yield from HttpClient()).filter_status_ok()
    return (yield from http.get("https://api.example.com/todos/1"))


@fx.fn
def program():
    error = yield from fetch().flip()
    # The reason says what failed; its cause, why. str() includes the cause when the
    # reason has no description of its own.
    print(type(error.reason).__name__)
    print("message:", error.message)
    print("cause:  ", repr(error.reason.cause))
    print("str:    ", error)


fx.run_main(program().pipe(fx.provide(client.layer_test(refuse))))
