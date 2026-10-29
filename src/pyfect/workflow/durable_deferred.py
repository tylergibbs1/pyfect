"""Named wait points of a workflow execution (Effect's
``effect/workflow/DurableDeferred``)::

    approval = durable_deferred.make("approval", success=S.Boolean)

    # in the workflow: suspend until someone completes it
    approved = yield from approval.wait()

    # anywhere else, with the token the workflow handed out
    yield from approval.succeed(token=token, value=True)

A deferred's result is stored by the engine, encoded by its schemas, so a
replay of the workflow reads it instead of waiting. A token names the
workflow, the execution and the deferred, so code outside the workflow
can complete the right wait point.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import base64
import json
from collections.abc import Generator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Never, NewType, cast
from weakref import WeakKeyDictionary

from pyfect._concurrency import race_all as race_all_effects
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.brand import Brand
from pyfect.cause import Cause, Interrupt, from_reasons
from pyfect.effect import from_exit, gen, provide_service, succeed, sync
from pyfect.exit import Exit, Failure, Success
from pyfect.schema import (
    Class,
    Codec,
    Defect,
    ExitSchema,
    String,
    StringFromBase64Url,
    Tuple,
    decode_sync,
    decode_to,
    encode_sync,
    from_brand,
    from_json_string,
    to_codec_json,
)
from pyfect.schema import Exit as ExitOf
from pyfect.schema import Never as NeverSchema
from pyfect.schema import Null as NullSchema
from pyfect.schema.transformation import transform
from pyfect.workflow._services import (
    WorkflowEngine,
    WorkflowEngineService,
    WorkflowInstance,
    WorkflowInstanceService,
)
from pyfect.workflow._suspension import suspend as suspend_run
from pyfect.workflow._suspension import wrap_activity_result
from pyfect.workflow.activity import CurrentAttempt, Exactly, codec_of

if TYPE_CHECKING:
    from pyfect.workflow.workflow import Workflow

Token = NewType("Token", str)
"""A string naming a workflow, an execution and a deferred."""

TokenSchema = String.pipe(from_brand(Brand[str, Token].nominal()))
"""Tokens (Effect's ``DurableDeferred.Token``)."""


class TokenParsed(Class):
    """A token taken apart."""

    workflow_name: str
    execution_id: str
    deferred_name: str

    @property
    def as_token(self) -> Token:
        """The token: base64url of the JSON ``[workflow, execution,
        deferred]``, as Effect writes it."""
        text = json.dumps(
            [self.workflow_name, self.execution_id, self.deferred_name],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return Token(base64.urlsafe_b64encode(text.encode()).decode().rstrip("="))

    @staticmethod
    def from_string(token: str) -> TokenParsed:
        """Parse ``token``; raises ``SchemaError`` if it is not one."""
        return decode_sync(TOKEN_FROM_STRING)(token)

    @staticmethod
    def encode(parsed: TokenParsed) -> str:
        return encode_sync(TOKEN_FROM_STRING)(parsed)


def _to_fields(parts: tuple[str, str, str]) -> Mapping[str, object]:
    return {"workflow_name": parts[0], "execution_id": parts[1], "deferred_name": parts[2]}


def _from_fields(fields: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        cast("str", fields["workflow_name"]),
        cast("str", fields["execution_id"]),
        cast("str", fields["deferred_name"]),
    )


TOKEN_FROM_STRING = StringFromBase64Url.pipe(
    decode_to(from_json_string(Tuple(String, String, String)))
).pipe(decode_to(TokenParsed, transform(decode=_to_fields, encode=_from_fields)))
"""Tokens as strings, decoded to ``TokenParsed`` (Effect's
``TokenParsed.FromString``)."""


class DurableDeferred[A, E = Never]:
    """A named wait point of a workflow execution whose result is an ``A``
    or an ``E`` failure. Make one with ``make``."""

    __slots__ = ("error_schema", "exit_schema", "name", "success_schema")

    def __init__(
        self,
        name: str,
        *,
        success: Codec[A, Any, Never, Never],
        error: Codec[E, Any, Never, Never],
    ) -> None:
        self.name = name
        self.success_schema = success
        self.error_schema = error
        self.exit_schema: ExitSchema[A, E, Any, Any, Never, Never] = ExitOf(
            to_codec_json(success), to_codec_json(error), to_codec_json(Defect())
        )

    def __repr__(self) -> str:
        return f"DurableDeferred({self.name!r})"

    @property
    def with_activity_attempt(self) -> Effect[DurableDeferred[A, E]]:
        """This deferred named for the current activity attempt
        (``"{name}/{attempt}"``)."""
        return CurrentAttempt().map(
            lambda attempt: DurableDeferred(
                f"{self.name}/{attempt}", success=self.success_schema, error=self.error_schema
            )
        )

    def wait(self) -> Effect[A, E, WorkflowEngine | WorkflowInstance]:
        """The deferred's result, suspending the execution until it has one
        (Effect's ``DurableDeferred.await``)."""
        return await_(self)

    def into[R](
        self, effect: Effect[A, E, R]
    ) -> Effect[A, E, R | WorkflowEngine | WorkflowInstance]:
        """Run ``effect`` and record its exit as this deferred's result,
        waking executions waiting on it.

        ``effect`` and the write count as one in-flight activity of the
        workflow, so siblings parked on durable waits do not suspend the
        run until the exit is recorded. If ``effect`` parks on a durable
        wait itself, the run suspends once the other activities finish and
        nothing is recorded. Completing a deferred the run waits on still
        replays the run."""
        require_effect(effect, "effect")
        return _record_held(effect, self, check_cache=False)

    def token(self) -> Effect[Token, Never, WorkflowInstance]:
        """The token of this deferred in the current execution."""
        return WorkflowInstance().map(
            lambda instance: (
                TokenParsed(
                    workflow_name=instance.workflow.tag,
                    execution_id=instance.execution_id,
                    deferred_name=self.name,
                ).as_token
            )
        )

    def token_from_execution_id(
        self, *, workflow: Workflow[Any, Any, Any], execution_id: str
    ) -> Token:
        return TokenParsed(
            workflow_name=workflow.tag, execution_id=execution_id, deferred_name=self.name
        ).as_token

    def token_from_payload[P](
        self, *, workflow: Workflow[P, Any, Any], payload: P
    ) -> Effect[Token]:
        return workflow.execution_id(payload).map(
            lambda execution_id: self.token_from_execution_id(
                workflow=workflow, execution_id=execution_id
            )
        )

    def done(self, *, token: str, exit: Exit[A, E]) -> Effect[None, Never, WorkflowEngine]:
        """Record ``exit`` as the result of the deferred ``token`` names,
        waking its execution."""

        def body() -> Generator[Effect[Any, Never, Any], Any]:
            engine = yield from WorkflowEngine()
            parsed = TokenParsed.from_string(token)
            yield from engine.deferred_done(
                self,
                workflow_name=parsed.workflow_name,
                execution_id=parsed.execution_id,
                deferred_name=parsed.deferred_name,
                exit=exit,
            )

        return gen(body)

    def succeed(self, *, token: str, value: A) -> Effect[None, Never, WorkflowEngine]:
        return self.done(token=token, exit=Success(value))

    def fail(self, *, token: str, error: E) -> Effect[None, Never, WorkflowEngine]:
        from pyfect.cause import fail as fail_cause_of

        return self.done(token=token, exit=Failure(fail_cause_of(error)))

    def fail_cause(self, *, token: str, cause: Cause[E]) -> Effect[None, Never, WorkflowEngine]:
        return self.done(token=token, exit=Failure(cause))


def make[A = None, E = Never](
    name: str,
    *,
    success: Codec[A, Any, Never, Never] | None = None,
    error: Codec[E, Any, Never, Never] | None = None,
) -> DurableDeferred[A, E]:
    """A deferred named ``name`` (unique within its workflow). ``success``
    defaults to ``None`` (Effect's ``Void``), ``error`` to none."""
    return DurableDeferred(
        name,
        success=cast("Codec[A, Any, Never, Never]", NullSchema) if success is None else success,
        error=cast("Codec[E, Any, Never, Never]", NeverSchema) if error is None else error,
    )


# --- waits and the runs that own them ---------------------------------------------------

_await_owners: WeakKeyDictionary[WorkflowInstanceService, list[str]] = WeakKeyDictionary()
"""The waits registered under the instance copy of a ``_record_held`` body."""


def _register_await(instance: WorkflowInstanceService, name: str) -> None:
    instance.awaited_deferreds[name] = instance.awaited_deferreds.get(name, 0) + 1
    owned = _await_owners.get(instance)
    if owned is not None:
        owned.append(name)


def _release_awaits(instance: WorkflowInstanceService, names: list[str]) -> None:
    for name in names:
        count = instance.awaited_deferreds[name] - 1
        if count == 0:
            del instance.awaited_deferreds[name]
        else:
            instance.awaited_deferreds[name] = count


def await_[A, E](self: DurableDeferred[A, E]) -> Effect[A, E, WorkflowEngine | WorkflowInstance]:
    """``self``'s result, suspending the execution until there is one."""

    def body() -> Generator[Effect[Any, Any, Any], Any, A]:
        engine = yield from WorkflowEngine()
        instance = yield from WorkflowInstance()
        # Register before the read, so any later completion can preempt the run.
        _register_await(instance, self.name)
        found = yield from wrap_activity_result(engine.deferred_result(self), lambda e: e is None)
        if found is None:
            return (yield from suspend_run(instance))
        return (yield from from_exit(found))

    return gen(body)


def _record_exit(
    engine: WorkflowEngineService,
    instance: WorkflowInstanceService,
    self: DurableDeferred[Any, Any],
    ex: Exit[Any, Any],
) -> Effect[None]:
    """Record ``ex`` into ``self``. An exit of interrupts only is no result
    (the effect suspended, was preempted or interrupted); interrupts mixed
    into a failure are dropped from the recorded cause."""
    if isinstance(ex, Failure):
        if ex.cause.has_interrupts_only:
            return succeed(None)
        if ex.cause.has_interrupts:
            ex = Failure(from_reasons(r for r in ex.cause.reasons if not isinstance(r, Interrupt)))
    return engine.deferred_done(
        self,
        workflow_name=instance.workflow.tag,
        execution_id=instance.execution_id,
        deferred_name=self.name,
        exit=ex,
    )


def _record_held[A, E, R](
    effect: Effect[A, E, R], self: DurableDeferred[Any, Any], *, check_cache: bool
) -> Effect[A, E, R | WorkflowEngine | WorkflowInstance]:
    """Run ``effect`` as one activity of the workflow and record its exit
    into ``self`` (with ``check_cache``, a recorded exit is returned
    instead). The hold spans the lookup, ``effect`` and the write, so a
    parked sibling cannot suspend the run before the continuation starts."""

    def body() -> Generator[Effect[Any, Any, Any], Any, A]:
        engine = yield from WorkflowEngine()
        instance = yield from WorkflowInstance()

        def held() -> Generator[Effect[Any, Any, Any], Any, Exit[A, E] | None]:
            if check_cache:
                cached = yield from engine.deferred_result(self)
                if cached is not None:
                    return cached
            # ``effect`` counts on its own activity state, so a durable wait
            # inside it waits for its own siblings, not for this hold. The
            # copy starts unsuspended: a parked arm of an enclosing race
            # leaves that copy marked suspended.
            local = instance.copy()
            # A losing branch parked on a durable wait has exited when the
            # race settles, so this body owns the waits registered beneath it.
            owned: list[str] = []
            _await_owners[local] = owned
            # A parked ``effect`` interrupts the fiber it runs on; the child
            # keeps that from skipping the suspension handling below.
            fiber = yield from (
                effect.pipe(provide_service(WorkflowInstance, local))
                .on_exit(lambda ex: _record_exit(engine, instance, self, ex))
                .fork(start_immediately=True)
            )

            def settle(ex: Exit[A, E]) -> Exit[A, E] | None:
                if local.suspended and isinstance(ex, Failure) and ex.cause.has_interrupts_only:
                    return None
                return ex

            def release(result: Exit[Exit[A, E] | None, Never]) -> Effect[None]:
                def run() -> None:
                    if isinstance(result, Success) and result.value is not None:
                        _release_awaits(instance, owned)
                    else:
                        parent = _await_owners.get(instance)
                        if parent is not None:
                            parent.extend(owned)

                return sync(run)

            return (
                yield from fiber.await_exit()
                .on_interrupt(fiber.interrupt())
                .map(settle)
                .on_exit(release)
            )

        # Every branch parked: release the hold and let the enclosing
        # activities finish before suspending.
        found = yield from wrap_activity_result(gen(held), lambda e: e is None)
        if found is None:
            return (yield from suspend_run(instance))
        return (yield from from_exit(found))

    return gen(body)


def race_all[A, E, R](
    *,
    name: str,
    success: Exactly[A],
    error: Exactly[E],
    effects: Sequence[Effect[A, E, R]],
) -> Effect[A, E, R | WorkflowEngine | WorkflowInstance]:
    """Race ``effects`` durably: the first to succeed wins (or the last
    failure), its exit is recorded, and a replay gets the recorded exit
    without running them again."""
    if not effects:
        raise ValueError("race_all needs at least one effect")
    deferred: DurableDeferred[A, E] = DurableDeferred(
        f"raceAll/{name}", success=codec_of(success), error=codec_of(error)
    )
    return _record_held(race_all_effects(*effects), deferred, check_cache=True)


__all__ = [
    "TOKEN_FROM_STRING",
    "DurableDeferred",
    "Token",
    "TokenParsed",
    "TokenSchema",
    "await_",
    "make",
    "race_all",
]
