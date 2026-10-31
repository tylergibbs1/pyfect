"""The entities of Effect's ``test/cluster/TestEntity.ts``."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Never, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.cluster.cluster_schema import Dynamic, Persisted, WithTransaction
from pyfect.cluster.entity import Entity, Request
from pyfect.cluster.message_storage import MemoryTransaction
from pyfect.context import Context, Tag
from pyfect.errors import Done
from pyfect.latch import Latch
from pyfect.queue import Queue
from pyfect.rpc import fork, rpc_schema
from pyfect.rpc import make as make_rpc


class User(S.Class, identifier="User"):
    id: int
    name: str


class BoomError(S.TaggedError, identifier="BoomError"):
    cause: object = S.field(S.Unknown)


class IdPayload(TypedDict):
    id: int


class IdsPayload(TypedDict):
    ids: list[int]


class KeyPayload(S.Class):
    key: str

    def primary_key(self) -> str:
        return self.key


class IdKeyPayload(S.Class):
    id: int

    def primary_key(self) -> str:
        return str(self.id)


def _with_transaction(annotations: Context[Any], _request: Any) -> Context[Any]:
    return annotations.add(WithTransaction, True)


StreamWithKey = make_rpc(
    "StreamWithKey", success=rpc_schema.Stream(S.Int, S.Never), payload=KeyPayload
)


class TestEntity(Entity, type="TestEntity", rpc_annotations=Context.make(Persisted, True)):
    get_user = make_rpc("GetUser", success=User, payload=S.Struct(IdPayload))
    get_user_volatile = make_rpc(
        "GetUserVolatile", success=User, payload=S.Struct(IdPayload)
    ).annotate(Persisted, False)
    never = make_rpc("Never")
    fail = make_rpc("Fail", error=BoomError)
    never_fork = make_rpc("NeverFork")
    never_volatile = make_rpc("NeverVolatile").annotate(Persisted, False)
    request_with_key = make_rpc("RequestWithKey", payload=KeyPayload)
    stream_with_key = StreamWithKey
    get_all_users = make_rpc("GetAllUsers", success=User, payload=S.Struct(IdsPayload), stream=True)
    get_all_users_volatile = make_rpc(
        "GetAllUsersVolatile", success=User, payload=S.Struct(IdsPayload), stream=True
    ).annotate(Persisted, False)
    with_transaction = make_rpc(
        "WithTransaction", success=S.Boolean, payload=S.Struct(IdPayload)
    ).annotate(Dynamic, _with_transaction)
    fail_with_transaction = make_rpc(
        "FailWithTransaction", error=BoomError, payload=IdKeyPayload
    ).annotate(Dynamic, _with_transaction)
    never_with_transaction = make_rpc("NeverWithTransaction").annotate(Dynamic, _with_transaction)


@dataclass(slots=True, eq=False)
class TestEntityStateService:
    messages: Queue[None, Never]
    stream_messages: Queue[None, Done]
    envelopes: Queue[Request[Any], Never]
    interrupts: Queue[Request[Any], Never]
    build_latch: Latch
    defect_trigger: list[bool] = field(default_factory=lambda: [False])
    layer_builds: list[int] = field(default_factory=lambda: [0])


class TestEntityState(Tag[TestEntityStateService], key="TestEntityState"):
    pass


@fx.gen
def _make_state():
    return TestEntityStateService(
        messages=(yield from Queue[None, Never].unbounded()),
        stream_messages=(yield from Queue[None, Done].unbounded()),
        envelopes=(yield from Queue[Request[Any], Never].unbounded()),
        interrupts=(yield from Queue[Request[Any], Never].unbounded()),
        build_latch=Latch(True),
    )


test_entity_state_layer = fx.layer.effect(TestEntityState, _make_state)


def _users(ids: Iterable[int]) -> stream.Stream[User]:
    return stream.from_iterable([User(id=i, name=f"User {i}") for i in ids]).rechunk(1)


@fx.gen
def _build_test_entity():
    state = yield from TestEntityState()
    state.layer_builds[0] += 1
    yield from state.build_latch.wait()

    def never(envelope: Request[Any]) -> fx.Effect[None]:
        def start() -> fx.Effect[None]:
            state.envelopes.offer_unsafe(envelope)
            return fx.never

        def interrupted() -> None:
            state.interrupts.offer_unsafe(envelope)

        return fx.suspend(start).on_interrupt(fx.sync(interrupted))

    def get_user(envelope: Request[IdPayload]) -> fx.Effect[User]:
        def run() -> User:
            state.envelopes.offer_unsafe(envelope)
            if state.defect_trigger[0]:
                state.defect_trigger[0] = False
                raise RuntimeError("User not found")
            return User(id=envelope.payload["id"], name=f"User {envelope.payload['id']}")

        return fx.sync(run)

    def get_user_volatile(envelope: Request[IdPayload]) -> fx.Effect[User]:
        def run() -> User:
            state.envelopes.offer_unsafe(envelope)
            return User(id=envelope.payload["id"], name=f"User {envelope.payload['id']}")

        return fx.sync(run)

    def request_with_key(envelope: Request[KeyPayload]) -> fx.Effect[None]:
        state.envelopes.offer_unsafe(envelope)
        return state.messages.take()

    def stream_with_key(envelope: Request[KeyPayload]) -> stream.Stream[int]:
        last = envelope.last_sent_chunk_value
        sequence = [0 if last is None else last + 1]

        def next_value(_: None) -> int:
            value = sequence[0]
            sequence[0] += 1
            return value

        return stream.from_queue(state.stream_messages).map(next_value)

    def get_all_users(envelope: Request[IdsPayload]) -> stream.Stream[User]:
        state.envelopes.offer_unsafe(envelope)
        return _users(envelope.payload["ids"])

    def with_transaction(envelope: Request[IdPayload]) -> fx.Effect[bool]:
        def run() -> fx.Effect[bool]:
            state.envelopes.offer_unsafe(envelope)
            return MemoryTransaction()

        return fx.suspend(run)

    def fail_with_transaction(envelope: Request[IdKeyPayload]) -> fx.Effect[None, BoomError]:
        def run() -> fx.Effect[None, BoomError]:
            state.envelopes.offer_unsafe(envelope)
            return fx.fail(BoomError(cause="boom"))

        return fx.suspend(run)

    e = TestEntity
    return (
        e.handlers()
        .handle(e.get_user)(get_user)
        .handle(e.get_user_volatile)(get_user_volatile)
        .handle(e.never)(never)
        .handle(e.fail)(lambda _: fx.fail(BoomError(cause=RuntimeError("boom"))))
        .handle(e.never_fork)(lambda envelope: fork(never(envelope)))
        .handle(e.never_volatile)(never)
        .handle(e.request_with_key)(request_with_key)
        .handle(e.stream_with_key)(stream_with_key)
        .handle(e.get_all_users)(get_all_users)
        .handle(e.get_all_users_volatile)(lambda envelope: _users(envelope.payload["ids"]))
        .handle(e.with_transaction)(with_transaction)
        .handle(e.fail_with_transaction)(fail_with_transaction)
        .handle(e.never_with_transaction)(never)
    )


test_entity_no_state = TestEntity.to_layer_effect(
    _build_test_entity, defect_retry_policy=fx.schedule.forever
)

test_entity_layer = test_entity_no_state.pipe(fx.layer.provide_merge(test_entity_state_layer))


class CallerId(Tag[str], key="effect/test/cluster/CallerId"):
    pass


class ContextBleedEntity(Entity, type="ContextBleedEntity"):
    read_caller = make_rpc("ReadCaller", success=S.String).annotate(Persisted, False)
    read_caller_persisted = make_rpc("ReadCallerPersisted", success=S.String).annotate(
        Persisted, True
    )


def _read_caller(_: object) -> fx.Effect[str]:
    return fx.service_option(CallerId).map(lambda found: "none" if found is None else found.value)


context_bleed_layer = ContextBleedEntity.to_layer(
    ContextBleedEntity.handlers()
    .handle(ContextBleedEntity.read_caller)(_read_caller)
    .handle(ContextBleedEntity.read_caller_persisted)(_read_caller)
)
