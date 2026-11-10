import pyfect as fx
from pyfect.http import client, request, response
from pyfect.http.client import HttpClient
from pyfect.http.cookies import Cookie
from pyfect.ref import Ref


@fx.fn
def visit():
    jar = yield from Ref[tuple[Cookie, ...]].make(())
    http = (yield from HttpClient()).with_cookies_ref(jar)
    yield from http.post("https://api.example.com/login")
    yield from http.get("https://api.example.com/me")
    yield from http.get("https://other.example/")  # another host: no cookie
    return (yield from jar.get())


# A stand-in server: /login sets a session cookie; each request's Cookie header is recorded.
sent: list[str | None] = []


def handle(req: request.HttpClientRequest):
    sent.append(req.headers.get("cookie"))
    if req.url.endswith("/login"):
        return fx.succeed(response.make(req, headers={"set-cookie": "session=abc; HttpOnly"}))
    return fx.succeed(response.make(req))


stored = fx.run_main(visit().pipe(fx.provide(client.layer_test(handle))))
print(sent)
assert stored[0].options is not None and stored[0].options.host_only  # no Domain: this host only
