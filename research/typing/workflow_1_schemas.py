"""Question: how should a workflow (and an activity) be declared so its
payload, success and error come from its schemas, and pyright checks the
handler and the call site against them?

Effect's ``Workflow.make(tag, { payload, success, error, idempotencyKey })``
types everything from the schemas. Three questions:

Q1. ``make(success=S.Number, execute=...)``: does one shared TypeVar ``A``
    for the schema and the effect reject an effect of the wrong type, or
    does pyright widen ``A`` to the union?
Q2. ``to_layer(handler)``: can union matching remove ``WorkflowEngine |
    WorkflowInstance | Scope`` from the handler's requirements, keeping the
    rest?
Q3. ``execute(payload)`` / ``execute(payload, discard=True)``: do overloads
    on a ``Literal[True]`` keyword give ``Effect[A, E]`` and
    ``Effect[str, Never]``?

Run: ``uv run pyright -p research/typing research/typing/workflow_1_schemas.py``.

Answers:

Q1. With the schema and the effect both covariant in ``A``, pyright widens
    ``A`` to ``float | str`` and accepts a wrong effect. ``NoInfer`` is not
    available (Python 3.13's ``typing`` and the installed
    ``typing_extensions`` lack it). A protocol invariant in ``A``
    (``Exactly[A]``, whose one member is ``__codec__``, with an explicit
    invariant TypeVar) fixes ``A`` from the schema, and the effect is then
    checked against it: ``int`` fits a ``float`` schema, ``str`` does not.
    Schema values and schema classes both match it. The error schema works
    the same way; without one, the effect must not fail. (Only with
    ``success=`` written before ``execute=``: see ``workflow_2_exact_schemas``.)
Q2. Yes: ``Callable[[P, str], Effect[A, E, R | Engine | Instance | Scope]]``
    solves ``R`` to the rest, ``Never`` when nothing is left.
Q3. Yes, with the ``discard`` overload first (``Literal[True]``, keyword
    only) and the plain one second.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Never, Protocol, TypedDict, TypeVar, assert_type, overload


import pyfect as fx
from pyfect import schema as S
from pyfect.context import Tag
from pyfect.scope import Scope


class Engine(Tag[object]):
    pass


class Instance(Tag[object]):
    pass


class Db(Tag[object]):
    pass


type C[T] = S.Codec[T, Any, Never, Never]


class Workflow[P, A, E]:
    def __init__(self, payload: C[P], success: C[A], error: C[E]) -> None:
        self.payload = payload
        self.success = success
        self.error = error

    @overload
    def execute(
        self, payload: P, *, discard: Literal[True], detached: bool = False
    ) -> fx.Effect[str, Never, Engine]: ...
    @overload
    def execute(self, payload: P) -> fx.Effect[A, E, Engine]: ...
    def execute(self, payload: P, *, discard: bool = False, detached: bool = False) -> Any:
        raise NotImplementedError

    def to_layer[R](
        self, execute: Callable[[P, str], fx.Effect[A, E, R | Engine | Instance | Scope]]
    ) -> fx.Layer[Never, Never, R | Engine]:
        raise NotImplementedError


def make[P, A, E](*, payload: C[P], success: C[A], error: C[E]) -> Workflow[P, A, E]:
    return Workflow(payload, success, error)


def activity_widening[A](*, success: C[A], execute: fx.Effect[A]) -> fx.Effect[A]:
    return execute


T = TypeVar("T")


class Exactly(Protocol[T]):  # pyright: ignore[reportInvalidTypeVarUse]
    def __codec__(self) -> S.Bottom[T, Any, Never, Never]: ...


def activity(*, success: Exactly[T], execute: fx.Effect[T]) -> fx.Effect[T]:
    return execute


class Pay(TypedDict):
    id: str


wf = make(payload=S.Struct(Pay), success=S.Number, error=S.String)
assert_type(wf, Workflow[Pay, float, str])

# Q3
assert_type(wf.execute({"id": "1"}), fx.Effect[float, str, Engine])
assert_type(wf.execute({"id": "1"}, discard=True), fx.Effect[str, Never, Engine])
wf.execute({"nope": 1})  # pyright: ignore[reportArgumentType]

# Q2
db_effect: fx.Effect[float, str, Db | Engine | Instance | Scope] = fx.succeed(1.0)
assert_type(wf.to_layer(lambda p, i: db_effect), fx.Layer[Never, Never, Db | Engine])
plain: fx.Effect[float, str, Engine | Instance] = fx.succeed(1.0)
assert_type(wf.to_layer(lambda p, i: plain), fx.Layer[Never, Never, Engine])
wrong: fx.Effect[str, str] = fx.succeed("x")
wf.to_layer(lambda p, i: wrong)  # pyright: ignore[reportArgumentType]

# Q1: widening without NoInfer, checked with it
assert_type(activity_widening(success=S.Number, execute=fx.succeed("x")), fx.Effect[float | str])
activity(success=S.Number, execute=fx.succeed("x"))  # pyright: ignore[reportArgumentType]
assert_type(activity(success=S.Number, execute=fx.succeed(1)), fx.Effect[float])
