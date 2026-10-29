from dataclasses import dataclass

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.persistence import persistable, persisted_cache, persistence
from pyfect.sql import sqlite


class User(S.Class, identifier="User"):
    id: int
    name: str


class UserNotFound(S.TaggedError):
    id: int


# A request names its stored key and carries the schemas of its outcome.
@dataclass(frozen=True)
class GetUser(persistable.Class(success=User, error=UserNotFound)):
    id: int

    def primary_key(self) -> str:
        return f"GetUser:{self.id}"


lookups: list[int] = []


def fetch_user(request: GetUser) -> fx.Effect[User, UserNotFound]:
    lookups.append(request.id)
    if request.id == 1:
        return fx.succeed(User(id=1, name="Ada"))
    return fx.fail(UserNotFound(id=request.id))


def users_cache():
    return persisted_cache.make(
        fetch_user, store_id="users", time_to_live=lambda _exit, _request: 3600
    )


@fx.fn
def program():
    users = yield from users_cache()
    print((yield from users.get(GetUser(1))))
    print(repr((yield from users.get(GetUser(2)).flip())))

    # A new cache, as after a restart: both outcomes come from the store.
    users = yield from users_cache()
    print((yield from users.get(GetUser(1))))
    print(repr((yield from users.get(GetUser(2)).flip())))
    print("lookups:", lookups)


# Outcomes in a SQL table; persistence.layer_memory, layer_kvs and layer_redis also work.
Persistence = persistence.layer_sql.pipe(
    layer.provide(sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:")))
)
fx.run_main(fx.scoped(program()).pipe(fx.provide(Persistence)))
