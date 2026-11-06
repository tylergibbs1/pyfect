from typing import Never

import pyfect as fx

events: list[str] = []


def open_client(url: str) -> fx.Effect[str, Never, fx.Scope]:
    return fx.acquire_release(
        fx.sync(lambda: events.append(f"open {url}")).as_(f"client of {url}"),
        lambda _client, _exit: fx.sync(lambda: events.append(f"close {url}")),
    )


@fx.gen
def program():
    # A client per URL, shared while any scope holds it, closed once none has.
    clients = yield from fx.RcMap.make(open_client)
    a, b = yield from fx.scoped(
        fx.all(clients.get("https://a.test"), clients.get("https://a.test"))
    )
    assert a == b == "client of https://a.test"
    events.append("both scopes closed")


fx.run_blocking(fx.scoped(program))
assert events == ["open https://a.test", "close https://a.test", "both scopes closed"]
