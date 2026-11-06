from dataclasses import dataclass, field

import pyfect as fx
from pyfect import layer


@dataclass
class Database:
    rows: dict[str, str] = field(default_factory=lambda: {"1": "Ada"})

    def query(self, key: str) -> fx.Effect[str | None]:
        return fx.succeed(self.rows.get(key))


class Db(fx.Tag[Database]): ...


@dataclass
class UserRepo:
    db: Database

    def name(self, user_id: str) -> fx.Effect[str]:
        return self.db.query(user_id).map(lambda row: row or "unknown")


class Users(fx.Tag[UserRepo]): ...


DbLive = layer.sync(Db, Database)


# UsersLive needs Db to build: Layer[Users, Never, Db].
@fx.gen
def make_users():
    db = yield from Db()
    return UserRepo(db)


UsersLive = layer.effect(Users, make_users)

# provide on a layer satisfies its needs: Layer[Users].
AppLive = UsersLive.pipe(layer.provide(DbLive))


@fx.gen
def program():
    users = yield from Users()
    return (yield from users.name("1"))


assert fx.run_blocking(program.pipe(fx.provide(AppLive))) == "Ada"

# merge builds several layers together: Layer[Db | Users].
Both = layer.merge(DbLive, AppLive)
assert fx.run_blocking(program.pipe(fx.provide(Both))) == "Ada"
