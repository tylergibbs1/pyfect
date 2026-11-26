from dataclasses import dataclass, field
from typing import Protocol

import pyfect as fx
from pyfect import layer, testing


@dataclass
class EmailTaken(fx.TaggedError):
    email: str


class UserStore(Protocol):
    def exists(self, email: str) -> fx.Effect[bool]: ...
    def insert(self, email: str) -> fx.Effect[int]: ...


class Users(fx.Tag[UserStore]): ...


class Mailer(Protocol):
    def send(self, to: str, subject: str) -> fx.Effect[None]: ...


class Mail(fx.Tag[Mailer]): ...


@fx.fn
def sign_up(email: str):
    users = yield from Users()
    if (yield from users.exists(email)):
        return (yield from EmailTaken(email))
    user_id = yield from users.insert(email)
    mailer = yield from Mail()
    yield from mailer.send(email, "Welcome!")
    return user_id


# Fakes: plain classes with the same shape as the real services.
@dataclass
class InMemoryUsers:
    emails: list[str] = field(default_factory=list[str])

    def exists(self, email: str) -> fx.Effect[bool]:
        return fx.sync(lambda: email in self.emails)

    def insert(self, email: str) -> fx.Effect[int]:
        return fx.sync(lambda: self.emails.append(email) or len(self.emails))


@dataclass
class RecordingMailer:
    sent: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def send(self, to: str, subject: str) -> fx.Effect[None]:
        return fx.sync(lambda: self.sent.append((to, subject)))


@testing.effect
def test_a_new_user_gets_a_welcome_mail():
    mailer = RecordingMailer()
    fakes = layer.merge(layer.succeed(Users, InMemoryUsers()), layer.succeed(Mail, mailer))
    user_id = yield from sign_up("ada@example.com").pipe(fx.provide(fakes))
    assert user_id == 1
    assert mailer.sent == [("ada@example.com", "Welcome!")]


def already_there(email: str) -> fx.Effect[bool]:
    return fx.succeed(True)


@testing.effect
def test_a_taken_email_fails_and_sends_nothing():
    # layer.mock stubs only the members a test uses. Mail has none here,
    # so any send would die with UnimplementedError and fail the test.
    mocks = layer.merge(layer.mock(Users, exists=already_there), layer.mock(Mail))
    exit = yield from sign_up("ada@example.com").exit().pipe(fx.provide(mocks))
    testing.assert_exit_fail(exit, EmailTaken("ada@example.com"))
