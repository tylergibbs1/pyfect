"""Starting one entity (the lookup of Effect's ``entityManager`` resource
map): admit it under the residency cap, build its handlers and RPC server
behind a ``ResourceRef`` (rebuilt after a defect, replaying the requests
it was serving), and drain it when its scope closes."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, cast

from pyfect import cause as Cause
from pyfect import exit as Exit
from pyfect._core import Effect, _Locally
from pyfect.cluster import _cluster_abandon, cluster_metrics
from pyfect.cluster._entity_activation import CurrentActivationScope
from pyfect.cluster._interruptors import acquire_entity, release_entity
from pyfect.cluster._resource_ref import ResourceRef
from pyfect.cluster.cluster_error import EntityNotAssignedToRunner, MailboxFull
from pyfect.cluster.cluster_schema import (
    InterruptOnTermination,
    Persisted,
    is_uninterruptible_for_server,
)
from pyfect.cluster.entity._services import CurrentAddress, CurrentRunnerAddress, KeepAliveLatch
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.reply import Chunk, WithExit
from pyfect.cluster.snowflake import Snowflake
from pyfect.effect import fail, fail_cause, gen, interrupt, succeed, suspend, sync
from pyfect.latch import Latch
from pyfect.logger import CurrentLogAnnotations, log_error
from pyfect.metric import Registration, register_unsafe
from pyfect.metric._state import GaugeState
from pyfect.rpc import message as rpc_message
from pyfect.rpc.message import FromClient, FromServer
from pyfect.rpc.server._core import OnRequest, ServerOptions, make_no_serialization
from pyfect.scope import CloseableScope, Scope, fork_in

from ._core import CloseLatches, ManagerCore, request_envelope, retry_respond, set_context
from ._state import EntityState, RequestEntry, WriteFn

_VOID: Effect[None] = succeed(None)


def _has_stored_exit(core: ManagerCore, request_id: Snowflake) -> Effect[bool]:
    """Whether storage holds the request's exit (``False`` when it cannot
    be read, so the request is replayed)."""

    def tag(reply: Any) -> object:
        if isinstance(reply, dict):
            return cast("dict[str, object]", reply).get("_tag")
        return type(reply).__name__

    def found(replies: list[Any]) -> bool:
        return any(tag(reply) == "WithExit" for reply in replies)

    return (
        core.storage.replies_for_unfiltered([request_id])
        .map(found)
        .catch_cause(lambda _: succeed(False))
    )


def _new_dies(outcome: Cause.Cause[Any], exit: Exit.Exit[Any, Any]) -> bool:
    """Whether ``outcome`` holds a defect ``exit`` does not (a transaction
    wrapper can add defects, not typed errors; interrupts may repeat)."""
    known = (
        [r.defect for r in exit.cause.reasons if isinstance(r, Cause.Die)]
        if isinstance(exit, Exit.Failure)
        else []
    )
    return any(
        isinstance(reason, Cause.Die) and not any(d is reason.defect for d in known)
        for reason in outcome.reasons
    )


class _Activation:
    """One entity's lifetime: its mailbox, its server (through
    ``write_ref``) and the latches its drain waits on."""

    __slots__ = (
        "active_requests",
        "address",
        "close_latches",
        "core",
        "end_latch",
        "keep_alive_latch",
        "mailbox_series",
        "retired",
        "scope",
        "state",
        "write_ref",
    )

    def __init__(self, core: ManagerCore, address: EntityAddress, scope: CloseableScope) -> None:
        self.core = core
        self.address = address
        self.scope = scope
        self.end_latch = Latch()
        self.keep_alive_latch = Latch()
        self.close_latches = CloseLatches()
        self.active_requests: dict[Snowflake, RequestEntry] = {}
        self.mailbox_series: Registration | None = None
        self.retired = Latch()
        self.write_ref: ResourceRef[WriteFn] | None = None
        self.state: EntityState | None = None

    def is_active(self) -> bool:
        return not self.retired.is_open()

    def _ref(self) -> ResourceRef[WriteFn]:
        ref = self.write_ref
        assert ref is not None
        return ref

    # --- replay and restart ---------------------------------------------------------------

    def replay(self, write: WriteFn) -> Effect[None]:
        """Replay the requests already dispatched before admitting new work."""

        @gen
        def run():
            if not self.is_active():
                return
            for request in list(self.active_requests.values()):
                if not request.delivered:
                    continue
                request.sent_exit = False
                yield from write(
                    0, request_envelope(request), self.core.request_write_options(request)
                )

        return run

    def restart(self, cause: Cause.Cause[Any], rebuild: Effect[None]) -> Effect[None]:
        core = self.core

        def after_wait(_: object) -> Effect[None]:
            return rebuild if self.is_active() else self.end_latch.open().as_void()

        def failed(next_cause: Cause.Cause[Any]) -> Effect[None]:
            if next_cause.has_interrupts_only:
                return _VOID
            retry = self._ref().rebuild_unsafe(prepare=self.replay) if self.is_active() else None
            return _VOID if retry is None else self.restart(next_cause, retry)

        return (
            log_error("Defect in entity, restarting", cause)
            .and_then(core.retry_driver(None).ignore())
            .flat_map(after_wait)
            .annotate_logs(
                {
                    "module": "EntityManager",
                    "address": self.address,
                    "runner": core.options.runner_address,
                }
            )
            .catch_cause(failed)
        )

    # --- the handlers and server ----------------------------------------------------------

    def acquire_server(self, handler_scope: CloseableScope) -> Effect[WriteFn]:  # noqa: PLR0915
        core = self.core
        address = self.address
        options = core.options
        storage = core.storage
        activation = self

        @gen
        def run():  # noqa: PLR0915
            shutting_down = [False]
            handler_context = (
                core.context.add(CurrentAddress, address)
                .add(CurrentRunnerAddress, options.runner_address)
                .add(KeepAliveLatch, activation.keep_alive_latch)
                .add(CurrentActivationScope, activation.scope)
                .add(Scope, handler_scope)
                .add(CurrentLogAnnotations, {})
            )

            def defect_building(cause: Cause.Cause[Any]) -> Effect[None]:
                return log_error("Defect building entity handlers", cause)

            build = set_context(core.entity.to_handlers(core.build), handler_context)
            handlers = yield from (
                build.sandbox()
                .tap_error(defect_building)
                .retry(core.defect_retry_policy)
                .catch_all(fail_cause)
            )
            servers: list[Any] = []
            writes: list[WriteFn] = []

            def write_now(
                client_id: int, message: FromClient, on: OnRequest | None
            ) -> Effect[None]:
                return servers[0].write(client_id, message, on)

            def restart_from(cause: Cause.Cause[Any]) -> Effect[None]:
                # Do not inherit the failed handler's transaction context.
                if not activation.is_active():
                    return activation.end_latch.open().as_void()
                rebuild = activation._ref().rebuild_unsafe(
                    from_=writes[0], prepare=activation.replay
                )
                if rebuild is None:
                    return _VOID
                restarting = set_context(activation.restart(cause, rebuild), handler_context)
                return fork_in(restarting, core.manager_scope).as_void()

            def on_exit(response: rpc_message.ResponseExit) -> Effect[None]:  # noqa: PLR0911
                request_id = Snowflake(int(response.request_id))
                request = activation.active_requests.get(request_id)
                if request is None:
                    return _VOID
                request.sent_reply = True
                request.sent_exit = True
                exit = response.exit
                # Rebuild interrupts are not replies; replacement handlers replay the request.
                if (
                    shutting_down[0]
                    and isinstance(exit, Exit.Failure)
                    and exit.cause.has_interrupts
                    and activation.is_active()
                ):
                    return _VOID
                persisted = core.storage_enabled and request.message.annotations.get(Persisted)
                if persisted and isinstance(exit, Exit.Failure) and exit.cause.has_interrupts:
                    # A durable request interrupted by shutdown, or abandoned
                    # because this owner can no longer serve it, is left for
                    # replay instead of being answered.
                    abandoned = _cluster_abandon.is_cause(exit.cause) and (
                        not activation.is_active()
                        or not options.sharding.has_shard_id(address.shard_id)
                    )
                    if shutting_down[0] or request.terminating or abandoned:
                        activation.active_requests.pop(request_id, None)
                        return storage.unregister_reply_handler(request.message.envelope.request_id)
                    # An uninterruptible request ignores the interrupt and runs again.
                    if is_uninterruptible_for_server(request.message.annotations):
                        request.sent_exit = False
                        again = servers[0].write(
                            0, request_envelope(request), core.request_write_options(request)
                        )
                        return fork_in(set_context(again, handler_context), handler_scope).as_void()

                def respond_exit() -> Effect[None, Any]:
                    return request.message.respond(
                        WithExit(request_id=request_id, id=core.snowflakes.next_unsafe(), exit=exit)
                    )

                save = retry_respond(4, suspend(respond_exit))

                def complete_now() -> None:
                    if core.storage_enabled:
                        core.processed_request_ids.add(request.message.envelope.request_id)
                    activation.active_requests.pop(request_id, None)
                    # Start the idle timer when the last request completes.
                    if not activation.active_requests and activation.state is not None:
                        activation.state.last_active_check = core.now_millis()

                complete = sync(complete_now)
                respond = save.and_then(complete).or_die()
                transaction = request.transaction
                if transaction is None:
                    return respond
                if not persisted:
                    if isinstance(exit, Exit.Success):
                        return respond
                    transaction.settle = lambda _: respond
                    return _VOID
                if isinstance(exit, Exit.Success):

                    def settle_success(outcome: Exit.Exit[Any, Any]) -> Effect[None]:
                        if isinstance(outcome, Exit.Success):
                            return complete
                        cause = outcome.cause

                        def committed(stored: bool) -> Effect[None]:
                            if not stored:
                                return restart_from(cause)
                            # Commit succeeded despite the error; callers read the saved reply.
                            return complete.and_then(
                                storage.unregister_reply_handler(
                                    request.message.envelope.request_id
                                )
                            )

                        return _has_stored_exit(core, request.message.envelope.request_id).flat_map(
                            committed
                        )

                    transaction.settle = settle_success
                    return save.or_die()

                def settle_failure(outcome: Exit.Exit[Any, Any]) -> Effect[None]:
                    if isinstance(outcome, Exit.Success) or not _new_dies(outcome.cause, exit):
                        return respond
                    return restart_from(outcome.cause)

                transaction.settle = settle_failure
                return _VOID

            def on_chunk(response: rpc_message.ResponseChunk) -> Effect[None]:
                request_id = Snowflake(int(response.request_id))
                request = activation.active_requests.get(request_id)
                if request is None:
                    return _VOID
                sequence = request.sequence
                request.sequence += 1
                request.sent_reply = True

                def respond_chunk() -> Effect[None, Any]:
                    reply = Chunk[Any](
                        request_id=request_id,
                        id=core.snowflakes.next_unsafe(),
                        sequence=sequence,
                        values=response.values,
                    )
                    request.last_sent_chunk = reply
                    return request.message.respond(reply)

                return retry_respond(4, suspend(respond_chunk)).or_die()

            def on_from_server(response: FromServer) -> Effect[None]:
                match response:
                    case rpc_message.ResponseExit():
                        return on_exit(response)
                    case rpc_message.ResponseChunk():
                        return on_chunk(response)
                    case rpc_message.ResponseDefect():
                        return restart_from(Cause.die(response.defect))
                    case rpc_message.ClientEnd():
                        return activation.end_latch.open().as_void()

            server = yield from _Locally(
                make_no_serialization(
                    core.entity.protocol,
                    on_from_server,
                    ServerOptions(
                        span_prefix=core.entity.type,
                        span_attributes={
                            **options.span_attributes,
                            "entity.type": core.entity.type,
                            "entity.id": address.entity_id,
                        },
                        concurrency=options.concurrency,
                        disable_fatal_defects=options.disable_fatal_defects,
                    ),
                ),
                lambda _: handler_context.merge(handlers),
            )
            servers.append(server)
            writes.append(write_now)

            def mark_shutting_down(_: Exit.Exit[Any, Any]) -> Effect[None]:
                def run_mark() -> None:
                    shutting_down[0] = True

                return sync(run_mark)

            yield from handler_scope.add_finalizer(mark_shutting_down)
            return write_now

        return run

    # --- writing to the server --------------------------------------------------------------

    def write(self, client_id: int, message: FromClient, on: OnRequest | None) -> Effect[None]:
        def body() -> Effect[None]:
            ref = self._ref()
            if not isinstance(message, rpc_message.Request):
                # Interrupts, acks and EOF reach the handlers even during shutdown.
                current = ref.get_unsafe()
                if current is not None:
                    return current(client_id, message, on)
                return ref.await_.flat_map(lambda write: write(client_id, message, on))
            if not self.is_active():
                return interrupt()
            current = ref.get_unsafe()
            if current is None:
                return ref.await_.race_first(self.retired.wait()).flat_map(
                    lambda _: self.write(client_id, message, on)
                )
            request = self.active_requests.get(Snowflake(int(message.id)))
            if request is None:
                return _VOID
            request.delivered = True
            return current(client_id, message, on)

        return suspend(body)

    # --- draining -------------------------------------------------------------------------

    def drain(self) -> Effect[None]:
        """Stop taking requests and wait for the server to end, up to the
        termination timeout or until a forced release."""
        core = self.core
        address = self.address
        state = self.state
        assert state is not None
        activation = self

        def body() -> Effect[None]:
            core.active_servers.pop(address.entity_id, None)
            activation.retired.open_unsafe()
            activation.close_latches.closing = True
            acquire_entity(address)
            core.draining_servers[address.entity_id] = state

            @gen
            def interrupt_and_end():
                for request_id, request in list(activation.active_requests.items()):
                    annotations = request.message.annotations
                    if (
                        not request.delivered
                        or request.sent_exit
                        or not annotations.get(InterruptOnTermination)
                        or is_uninterruptible_for_server(annotations)
                    ):
                        continue
                    request.terminating = True
                    yield from state.write(0, rpc_message.Interrupt(request_id), None)
                # A handler this drain waits for may be parked on a request the
                # retired entity will never start, such as its own queued request.
                # Release callers before ``Eof``, which waits for handler acquisition.
                yield from core.options.abandon_undelivered(address, activation.is_delivered)
                yield from state.write(0, rpc_message.Eof(), None)

            graceful = (
                interrupt_and_end.and_then(activation.end_latch.wait())
                # A defect restart that finds the entity retired opens the end
                # latch without building handlers, so the writes may never land.
                .race_first(activation.end_latch.wait())
                .timeout_option(core.config.entity_termination_timeout)
                .interruptible()
            )

            def forget() -> None:
                if core.draining_servers.get(address.entity_id) is state:
                    del core.draining_servers[address.entity_id]

            return (
                graceful.race_first(activation.close_latches.force.wait().interruptible())
                .as_void()
                .ensuring(sync(forget))
            )

        return suspend(body)

    def is_delivered(self, request_id: Snowflake) -> bool:
        request = self.active_requests.get(request_id)
        return request is not None and request.delivered


def _mailbox_series(
    core: ManagerCore, address: EntityAddress, mailbox: dict[Any, Any]
) -> Registration:
    def get(_: Any) -> GaugeState[int]:
        return GaugeState(len(mailbox))

    return register_unsafe(
        cluster_metrics.entity_mailbox_size.with_attributes(
            {
                "type": core.entity.type,
                "id": address.entity_id,
                "shard": str(address.shard_id),
            }
        ),
        core.context,
        get,
    )


def make_entity(
    core: ManagerCore, address: EntityAddress
) -> Effect[EntityState, EntityNotAssignedToRunner | MailboxFull, Scope]:
    """Start the entity at ``address`` in the current scope."""
    options = core.options

    @gen
    def run():
        if not options.sharding.has_shard_id(address.shard_id):
            return (yield from fail(EntityNotAssignedToRunner(address=address)))
        scope = yield from Scope()

        # Gate the spawn on the runner-wide entity cap. Registering the
        # release must be atomic with taking the slot.
        def admit() -> Effect[None, MailboxFull]:
            if not options.residency.admit_unsafe():
                return fail(MailboxFull(address=address))
            return scope.add_finalizer(lambda _: sync(options.residency.release_unsafe))

        yield from suspend(admit).uninterruptible()
        activation = _Activation(core, address, scope)

        # Finalizers run in reverse, so the mailbox series and the resident
        # mailbox are removed only after the drain finalizer below has ended.
        def remove_resident() -> None:
            release_entity(address)
            if activation.mailbox_series is not None:
                activation.mailbox_series.remove()
            core.resident_mailboxes.pop(id(activation.active_requests), None)

        yield from scope.add_finalizer(lambda _: sync(remove_resident))

        def closed() -> None:
            latches = core.server_close_latches.pop(address, None)
            if latches is not None:
                latches.closed.open_unsafe()

        yield from scope.add_finalizer(lambda _: sync(closed))
        activation.write_ref = yield from ResourceRef.make(
            scope, activation.acquire_server, address
        )
        state = EntityState(
            address=address,
            scope=scope,
            active_requests=activation.active_requests,
            write=activation.write,
            keep_alive_latch=activation.keep_alive_latch,
            last_active_check=core.now_millis(),
        )
        activation.state = state
        yield from scope.add_finalizer(lambda _: activation.drain())
        if not options.sharding.has_shard_id(address.shard_id):
            return (yield from fail(EntityNotAssignedToRunner(address=address)))
        # Do not make shard interruption wait for an entity that is still building.
        core.server_close_latches[address] = activation.close_latches
        core.active_servers[address.entity_id] = state
        core.resident_mailboxes[id(activation.active_requests)] = activation.active_requests
        if core.mailbox_metrics:
            activation.mailbox_series = _mailbox_series(core, address, activation.active_requests)
        return state

    return run


__all__ = ["make_entity"]
