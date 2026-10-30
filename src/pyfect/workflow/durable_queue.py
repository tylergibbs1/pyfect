"""Work a workflow hands to persisted background workers (Effect's
``effect/workflow/DurableQueue``)::

    Emails = durable_queue.make(
        name="emails",
        payload=S.Struct(Email),
        idempotency_key=lambda email: email["id"],
    )

    # in a workflow: offer the item and suspend until a worker is done
    yield from Emails.process({"id": "welcome-ada", "to": "ada@example.com"})

    # in a worker process
    EmailWorker = Emails.worker(send_email, concurrency=5)

``process`` offers the item to the ``PersistedQueue`` named
``DurableQueue/<name>`` with a ``DurableDeferred`` token, then suspends;
a worker takes it, runs the handler and records the handler's ``Exit``
through the token, which resumes the workflow with the typed success or
error.

Delivery is at-least-once: a crash between the handler's success and the
acknowledgement delivers the item again, so handlers must be idempotent.
An item out of attempts is dead-lettered: its deferred never resolves and
the workflow stays parked until the item is requeued out of band (the
id-based de-duplication keeps replays from resurrecting it). Run
``persisted_queue.layer_cleanup`` in one instance to prune old items.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never, TypedDict, cast

from pyfect._core import Effect
from pyfect.effect import die, fail, gen, never
from pyfect.exit import Exit
from pyfect.layer import Layer, effect_discard
from pyfect.logger import log_warning
from pyfect.persistence import persisted_queue
from pyfect.persistence.persisted_queue import PersistedQueueError, PersistedQueueFactory
from pyfect.schedule import Schedule, exponential, min, spaced
from pyfect.schema import Bottom, Codec, SchemaError, Struct
from pyfect.scope import Scope
from pyfect.tracer import ExternalSpan, Span, use_span
from pyfect.workflow._services import WorkflowEngine, WorkflowInstance
from pyfect.workflow.activity import idempotency_key as activity_idempotency_key
from pyfect.workflow.durable_deferred import DurableDeferred, Token, TokenParsed, TokenSchema
from pyfect.workflow.durable_deferred import make as make_deferred


class _QueueItem(TypedDict):
    token: Token
    traceId: str
    spanId: str
    sampled: bool
    payload: object


"""What the queue stores: the item and the token and span to answer to."""

_queue_schemas: dict[int, tuple[object, Bottom[_QueueItem, Any, Never, Never]]] = {}


def _queue_schema(payload: Codec[Any, Any, Never, Never]) -> Bottom[_QueueItem, Any, Never, Never]:
    cached = _queue_schemas.get(id(payload))
    if cached is not None and cached[0] is payload:
        return cached[1]
    schema = Struct(_QueueItem, token=TokenSchema, payload=payload)
    _queue_schemas[id(payload)] = (payload, schema)
    return schema


DEFAULT_RETRY_SCHEDULE: Schedule[Any, Any, Any, Any] = min(exponential(0.5, 1.5), spaced(60))
"""How ``process`` retries a failed offer: exponential from 500 ms, at most
a minute apart."""


class DurableQueue[P, A = None, E = Never]:
    """A queue of ``P`` items whose workers succeed with ``A`` or fail with
    ``E``. Make one with ``make``."""

    __slots__ = ("deferred", "idempotency_key", "name", "payload_schema")

    def __init__(
        self,
        *,
        name: str,
        payload_schema: Codec[P, Any, Never, Never],
        idempotency_key: Callable[[P], str],
        deferred: DurableDeferred[A, E],
    ) -> None:
        self.name = name
        self.payload_schema = payload_schema
        self.idempotency_key = idempotency_key
        self.deferred = deferred

    def __repr__(self) -> str:
        return f"DurableQueue({self.name!r})"

    def _item_deferred(self, name: str) -> DurableDeferred[A, E]:
        """The deferred one queued item answers through."""
        return DurableDeferred(
            name, success=self.deferred.success_schema, error=self.deferred.error_schema
        )

    def _item_done(self, token: Token, exit: Exit[A, E]) -> Effect[None, Never, WorkflowEngine]:
        """Answer the item ``token`` names, through its own deferred (a
        deferred refuses a token naming another one)."""
        return self._item_deferred(TokenParsed.from_string(token).deferred_name).done(
            token=token, exit=exit
        )

    def process(
        self, payload: P, *, retry_schedule: Schedule[Any, Any, Any, Any] | None = None
    ) -> Effect[A, E, WorkflowEngine | WorkflowInstance | PersistedQueueFactory]:
        """Offer ``payload`` and wait (suspended) for a worker to process
        it. A failed offer is retried on ``retry_schedule`` (logged), then
        is a defect."""

        def body() -> Generator[Effect[Any, Any, Any], Any, A]:
            made = self.payload_schema.__codec__().make(payload)
            queue_name = f"DurableQueue/{self.name}"
            queue = yield from persisted_queue.make(
                name=queue_name, schema=_queue_schema(self.payload_schema)
            )
            item_id = yield from activity_idempotency_key(
                f"{queue_name}/{self.idempotency_key(made)}"
            )
            deferred = self._item_deferred(f"{self.deferred.name}/{item_id}")
            token = yield from deferred.token()

            def offer(span: Span) -> Effect[None]:
                item: _QueueItem = {
                    "token": token,
                    "payload": made,
                    "traceId": span.trace_id,
                    "spanId": span.span_id,
                    "sampled": span.sampled,
                }

                def schema_defect(
                    error: PersistedQueueError | SchemaError,
                ) -> Effect[Never, PersistedQueueError]:
                    return die(error) if isinstance(error, SchemaError) else fail(error)

                return (
                    queue.offer(item, id=item_id)
                    .tap_cause(log_warning)
                    .catch_all(schema_defect)
                    .retry(DEFAULT_RETRY_SCHEDULE if retry_schedule is None else retry_schedule)
                    .or_die()
                    .as_void()
                    .annotate_logs(
                        {
                            "package": "effect",
                            "module": "DurableQueue",
                            "fiber": "process",
                            "queueName": self.name,
                        }
                    )
                )

            yield from use_span(
                f"DurableQueue/{self.name}/process", offer, attributes={"id": item_id}
            )
            return (yield from deferred.wait())

        return gen(body)

    def make_worker[R = Never](
        self,
        f: Callable[[P], Effect[A, E, R]],
        *,
        concurrency: int = 1,
    ) -> Effect[Never, Never, WorkflowEngine | PersistedQueueFactory | R]:
        """Take items forever, ``concurrency`` at a time, recording each
        handler's exit for the workflow that offered it. A failure is
        logged and the worker goes on."""

        def body() -> Generator[Effect[Any, Any, Any], Any, Any]:
            queue = yield from persisted_queue.make(
                name=f"DurableQueue/{self.name}", schema=_queue_schema(self.payload_schema)
            )

            def handle(
                item: _QueueItem, _meta: persisted_queue.Metadata
            ) -> Effect[None, Never, Any]:
                payload = cast("P", item["payload"])
                return (
                    f(payload)
                    .exit()
                    .flat_map(lambda ex: self._item_done(item["token"], ex))
                    .with_span(
                        f"DurableQueue/{self.name}/worker",
                        capture_stack_trace=False,
                        parent=ExternalSpan(
                            trace_id=item["traceId"],
                            span_id=item["spanId"],
                            sampled=item["sampled"],
                        ),
                    )
                )

            worker = (
                queue.take(handle)
                .catch_cause(log_warning)
                .forever()
                .annotate_logs(
                    {
                        "package": "effect",
                        "module": "DurableQueue",
                        "fiber": "worker",
                        "queueName": self.name,
                    }
                )
            )
            yield from worker.replicate_effect(concurrency, concurrency=concurrency, discard=True)
            return (yield from never)

        return gen(body)

    def worker[R = Never](
        self, f: Callable[[P], Effect[A, E, R]], *, concurrency: int = 1
    ) -> Layer[Never, Never, WorkflowEngine | PersistedQueueFactory | R]:
        """A layer running ``make_worker`` in the background."""
        started: Effect[object, Never, Any] = self.make_worker(
            f, concurrency=concurrency
        ).fork_scoped()
        return cast(
            "Layer[Never, Never, WorkflowEngine | PersistedQueueFactory | R]",
            effect_discard(cast("Effect[object, Never, Scope]", started)),
        )


def make[P, A = None, E = Never](
    *,
    name: str,
    payload: Codec[P, Any, Never, Never],
    idempotency_key: Callable[[P], str],
    success: Codec[A, Any, Never, Never] | None = None,
    error: Codec[E, Any, Never, Never] | None = None,
) -> DurableQueue[P, A, E]:
    """A queue named ``name`` of ``payload`` items; ``idempotency_key``
    names an item within its workflow execution. ``success`` defaults to
    ``None``, ``error`` to none."""
    return DurableQueue(
        name=name,
        payload_schema=payload,
        idempotency_key=idempotency_key,
        deferred=make_deferred(f"DurableQueue/{name}", success=success, error=error),
    )


__all__ = ["DEFAULT_RETRY_SCHEDULE", "DurableQueue", "make"]
