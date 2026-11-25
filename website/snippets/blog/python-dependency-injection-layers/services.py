import sqlite3
from dataclasses import dataclass
from typing import Protocol, assert_type

import pyfect as fx
from pyfect import layer


@dataclass
class EmailTaken(fx.TaggedError):
    email: str


# A service is an interface plus a tag that effects ask for.
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


# The third type parameter lists what sign_up needs before it can run.
assert_type(sign_up("ada@example.com"), fx.Effect[int, EmailTaken, Users | Mail])


@dataclass
class SqliteUsers:
    db: sqlite3.Connection

    def exists(self, email: str) -> fx.Effect[bool]:
        query = "SELECT 1 FROM users WHERE email = ?"
        return fx.sync(lambda: self.db.execute(query, (email,)).fetchone() is not None)

    def insert(self, email: str) -> fx.Effect[int]:
        query = "INSERT INTO users (email) VALUES (?)"
        return fx.sync(lambda: self.db.execute(query, (email,)).lastrowid or 0)


def open_db() -> sqlite3.Connection:
    print("open database")
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
    return db


def close_db(db: sqlite3.Connection) -> None:
    print("close database")
    db.close()


# The layer owns the connection: opened when the layer is built, closed when the program ends.
UsersLive = layer.effect(
    Users,
    fx.acquire_release(fx.sync(open_db), lambda db, _exit: fx.sync(lambda: close_db(db))).map(
        SqliteUsers
    ),
)


class ConsoleMailer:
    def send(self, to: str, subject: str) -> fx.Effect[None]:
        return fx.sync(lambda: print(f"mail to {to}: {subject}"))


MailLive = layer.succeed(Mail, ConsoleMailer())
AppLive = layer.merge(UsersLive, MailLive)


@fx.gen
def program():
    print((yield from sign_up("ada@example.com").exit()))
    print((yield from sign_up("ada@example.com").exit()))


fx.run_blocking(program.pipe(fx.provide(AppLive)))
