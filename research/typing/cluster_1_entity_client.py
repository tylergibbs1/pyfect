"""Can an entity's RPCs be read on an entity client with the entity's
payload, success and error types, and the cluster's client errors in place
of ``RpcClientError``, while a plain RPC client keeps ``RpcClientError``?

Run with ``uv run pyright -p research/typing research/typing/cluster_1_entity_client.py``.

Findings (pyright 1.1.414):

C1. No mapped types, so an entity's client cannot be computed from a list
    of RPCs (Effect's ``RpcClient.From<Rpcs, E>``). An entity is a class
    whose attributes are the RPCs (an ``RpcGroup`` subclass, Effect's
    ``Entity.make(type, [rpcs])``), and its client is an instance of that
    class, so ``client.get_user`` is read through the RPC's ``__get__``.
C2. The client's transport error is the instance's type argument: a
    nominal marker base ``ClientErrors[TE]`` (``Entity`` extends
    ``ClientErrors[MailboxFull | ...]``) read by a first ``__get__``
    overload, before the ``RpcGroup`` one. The method's fourth type
    parameter ``TE`` defaults to ``RpcClientError``, so a plain RPC client
    is unchanged.
C3. The middleware overloads work the same way (``E | ME`` with ``TE``).
C4. ``make_client(Entity)`` solves the client type from ``type[T]``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Never, Self, TypeVar, assert_type, overload

from pyfect import Effect

P = TypeVar("P", covariant=True)
S = TypeVar("S")
E = TypeVar("E")
TE = TypeVar("TE", covariant=True)


class RpcClientError(Exception): ...


class MailboxFull(Exception): ...


class Group:
    pass


class ClientErrors(Generic[TE]):
    """Marks a group whose clients fail with ``TE`` instead of
    ``RpcClientError``."""


class Method[P1, S1, E1, TE1 = RpcClientError]:
    def __call__(self, payload: P1) -> Effect[S1, E1 | TE1]: ...


class Rpc(Generic[P, S, E]):
    @overload
    def __get__(self, instance: None, owner: type[object], /) -> Self: ...
    @overload
    def __get__[TE1](
        self, instance: ClientErrors[TE1], owner: type[object], /
    ) -> Method[P, S, E, TE1]: ...
    @overload
    def __get__(self, instance: Group, owner: type[object], /) -> Method[P, S, E]: ...
    def __get__(self, instance: object, owner: type[object], /) -> Any: ...


def make_rpc[P1, S1, E1 = Never](payload: P1, success: S1, error: E1 | None = None) -> Rpc[P1, S1, E1]: ...


class Entity(Group, ClientErrors[MailboxFull]):
    pass


class Counter(Entity):
    increment = make_rpc(payload=1, success="")


class Plain(Group):
    increment = make_rpc(payload=1, success="")


def make_client[T: Entity](entity: type[T]) -> Effect[Callable[[str], T]]: ...


def check(counter: Counter, plain: Plain) -> None:
    assert_type(counter.increment(1), Effect[str, MailboxFull])
    assert_type(plain.increment(1), Effect[str, RpcClientError])
    assert_type(Counter.increment, Rpc[int, str, Never])
    assert_type(make_client(Counter), Effect[Callable[[str], Counter]])
