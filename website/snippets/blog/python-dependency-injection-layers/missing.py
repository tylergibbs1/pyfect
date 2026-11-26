from typing import Never, Protocol, assert_type

import pyfect as fx
from pyfect import layer


class Mailer(Protocol):
    def send(self, to: str, subject: str) -> fx.Effect[None]: ...


class Mail(fx.Tag[Mailer]): ...


class UserStore(Protocol):
    def insert(self, email: str) -> fx.Effect[int]: ...


class Users(fx.Tag[UserStore], key="Users"): ...


@fx.fn
def sign_up(email: str):
    users = yield from Users()
    user_id = yield from users.insert(email)
    mailer = yield from Mail()
    yield from mailer.send(email, "Welcome!")
    return user_id


class ConsoleMailer:
    def send(self, to: str, subject: str) -> fx.Effect[None]:
        return fx.sync(lambda: print(f"mail to {to}: {subject}"))


# provide removes exactly what the layer builds; Users is still needed.
half = sign_up("ada@example.com").pipe(fx.provide(layer.succeed(Mail, ConsoleMailer())))
assert_type(half, fx.Effect[int, Never, Users])

# pyright rejects the run. Ignore it and the program dies at the first `yield from Users()`.
exit = fx.run_blocking_exit(half)  # pyright: ignore[reportArgumentType]
assert isinstance(exit, fx.Failure)
print(exit.cause.defects[0])
