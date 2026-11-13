from collections.abc import Sequence
from dataclasses import dataclass

import pyfect as fx
from pyfect.batching import Entry

USERS = {1: "ada", 2: "grace", 3: "edsger"}
queries: list[list[int]] = []


@dataclass
class UserNotFound(fx.TaggedError):
    id: int


# A request names what it succeeds and fails with. Frozen, so equal requests
# compare equal.
@dataclass(frozen=True)
class GetUser(fx.Request[str, UserNotFound]):
    id: int


def users_by_id(ids: list[int]) -> dict[int, str]:
    # Stands in for `SELECT ... WHERE id IN (...)`: one query for the whole batch.
    queries.append(ids)
    return {i: USERS[i] for i in ids if i in USERS}


@fx.fn
def run_all(entries: Sequence[Entry[GetUser]]):
    found = users_by_id(sorted({entry.request.id for entry in entries}))
    for entry in entries:
        name = found.get(entry.request.id)
        if name is None:
            yield from entry.fail(UserNotFound(entry.request.id))
        else:
            yield from entry.succeed(name)


users = fx.RequestResolver(run_all)


def get_user(id: int) -> fx.Effect[str, UserNotFound]:
    return fx.request(GetUser(id), users)


@fx.fn
def program():
    # Made concurrently, the three requests are one batch and one query.
    names = yield from fx.for_each([1, 2, 3], get_user, concurrency="unbounded")
    print(names, queries)

    # One after another, each request is a batch of its own.
    queries.clear()
    yield from fx.for_each([1, 2], get_user)
    print(queries)

    # An entry the resolver fails fails only its own request.
    queries.clear()
    found, missing = yield from fx.all(
        get_user(1).result(), get_user(9).result(), concurrency="unbounded"
    )
    print(found, missing, queries)


fx.run_blocking(program().or_die())
