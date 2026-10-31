"""Question: can a group's handlers be typed so that a group with an endpoint
(or RPC) left unhandled is a pyright error, as Effect's ``HttpApiBuilder.group``
and ``RpcGroup.toLayer`` make it a compile error?

Q1. If the endpoints still to handle were a union type, could each
    ``handle`` remove one, and the layer require the union to be empty?
Q2. Can that union come from the group class, whose endpoints are its
    attributes?

Run: ``uv run pyright -p research/typing research/typing/handlers_1_missing.py``.

Answers:

Q1. Yes, given distinct endpoint types: union matching removes the handled
    one (``Handlers[A | B].handle(A) -> Handlers[B]``; the last one needs an
    overload of its own, or ``Never`` comes out ``Unknown``), and a
    ``to_layer`` taking ``Handlers[Never]`` rejects what is left. Endpoints would need a
    type of their own each (their name as a ``Literal`` type parameter).
Q2. No: pyright has no mapped types, so nothing gathers a class's
    attributes into a union; the group would have to repeat its endpoint
    names as a type argument. pyfect does not ask for that: an RPC group's
    ``to_layer`` raises ``ValueError`` naming each RPC without a handler, and
    an HttpApi group's layer dies when built naming each endpoint (its
    handlers are made then).
"""

from typing import Any, Literal, Never, assert_type, overload


class Endpoint[N: str]:
    def __init__(self, name: N) -> None:
        self.name = name


class Handlers[Rest]:
    @overload
    def handle[N: str](self: "Handlers[Endpoint[N]]", endpoint: Endpoint[N]) -> "Handlers[Never]": ...
    @overload
    def handle[N: str, R](self: "Handlers[Endpoint[N] | R]", endpoint: Endpoint[N]) -> "Handlers[R]": ...
    def handle(self, endpoint: object) -> "Handlers[Any]":
        return Handlers()


def to_layer(handlers: Handlers[Never]) -> None: ...


get_user = Endpoint[Literal["getUser"]]("getUser")
list_users = Endpoint[Literal["listUsers"]]("listUsers")

# Q1: the remaining endpoints, written out.
start: Handlers[Endpoint[Literal["getUser"]] | Endpoint[Literal["listUsers"]]] = Handlers()
done = start.handle(get_user).handle(list_users)
assert_type(done, Handlers[Never])
to_layer(done)
to_layer(start.handle(get_user))  # pyright: ignore[reportArgumentType]


# Q2: a class of endpoints gives no union of them to start from.
class Users:
    get_user = get_user
    list_users = list_users
