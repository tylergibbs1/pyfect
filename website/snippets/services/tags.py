from typing import Protocol

import pyfect as fx
from pyfect import layer


# 1. The service's shape: any class or Protocol.
class Mailer(Protocol):
    def send(self, to: str, body: str) -> fx.Effect[None]: ...


# 2. A tag: the service's identity, which effects ask for.
class Mail(fx.Tag[Mailer]): ...


@fx.fn
def welcome(user: str):
    mailer = yield from Mail()  # needs Mail: welcome(...) is Effect[None, Never, Mail]
    yield from mailer.send(user, "Welcome!")


# 3. An implementation, provided by a layer.
class Outbox:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, to: str, body: str) -> fx.Effect[None]:
        return fx.sync(lambda: self.sent.append(f"{to}: {body}"))


outbox = Outbox()
MailLive = layer.succeed(Mail, outbox)

# provide removes Mail from the requirements; run_sync accepts only Effect[A, E, Never].
fx.run_sync(welcome("ada@example.com").pipe(fx.provide(MailLive)))
assert outbox.sent == ["ada@example.com: Welcome!"]
