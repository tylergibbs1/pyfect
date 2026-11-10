"""Storing a request's final reply (the exit branch of Effect's
``entityManager`` ``onExit``). A persisted reply is stored only while this
runner still owns the request's shard; a fenced reply is abandoned for the
shard's owner. A save is retried, unless a retry could store a success
outside the request's transaction. A save that failed but committed anyway
is completed from storage. With a transaction, the outcome settles once it
commits or rolls back."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pyfect import cause as Cause
from pyfect import exit as Exit
from pyfect._core import Effect
from pyfect.cluster.cluster_error import EntityNotAssignedToRunner, PersistenceError
from pyfect.cluster.reply import WithExit
from pyfect.cluster.snowflake import Snowflake
from pyfect.effect import fail, succeed, suspend, sync
from pyfect.logger import log_debug

from ._core import ManagerCore, retry_respond
from ._state import RequestEntry

if TYPE_CHECKING:
    from ._activation import _Activation

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


@dataclass(eq=False, slots=True, kw_only=True)
class ExitReply:
    activation: _Activation
    request: RequestEntry
    request_id: Snowflake
    exit: Exit.Exit[Any, Any]
    persisted: bool
    restart_from: Callable[[Cause.Cause[Any]], Effect[None]]
    fenced: bool = False
    """Set once ownership was not confirmed, so the reply was not stored."""

    @property
    def _envelope_id(self) -> Snowflake:
        return self.request.message.envelope.request_id

    def run(self) -> Effect[None]:
        """Store the reply, now or when the request's transaction settles."""
        transaction = self.request.transaction
        respond = self._respond()
        if transaction is None:
            return respond
        if not self.persisted:
            if isinstance(self.exit, Exit.Success):
                return respond
            transaction.settle = lambda _: respond
            return _VOID
        if isinstance(self.exit, Exit.Success):
            transaction.settle = self._settle_success
            return self._save().or_die()

        def settle_failure(outcome: Exit.Exit[Any, Any]) -> Effect[None]:
            if isinstance(outcome, Exit.Success) or not _new_dies(outcome.cause, self.exit):
                return respond
            return self.restart_from(outcome.cause)

        transaction.settle = settle_failure
        return _VOID

    def _save(self) -> Effect[None, Any]:
        core = self.activation.core
        exit = self.exit

        def respond_exit() -> Effect[None, Any]:
            reply = WithExit(
                request_id=self.request_id, id=core.snowflakes.next_unsafe(), exit=exit
            )
            return self.request.message.respond(reply)

        # A failed save can abort the request transaction, so a retry could
        # store a success outside it. Save once and let the failed
        # transaction replay the request.
        once = (
            self.persisted
            and self.request.transaction is not None
            and isinstance(exit, Exit.Success)
        )
        write = retry_respond(0 if once else 4, suspend(respond_exit))
        if not self.persisted:
            return write

        # A runner that lost the shard must not decide the stored result. A
        # rejection is not retried.
        address = self.activation.address

        def fence(owned: bool) -> Effect[None, Any]:
            if owned:
                return write
            self.fenced = True
            return fail(EntityNotAssignedToRunner(address=address))

        return core.options.is_shard_owned(address.shard_id).flat_map(fence)

    def _respond(self) -> Effect[None]:
        def save_failed(error: object) -> Effect[None, Any]:
            if isinstance(error, EntityNotAssignedToRunner):
                return self._abandon()
            # A save can commit and still fail, as when the COMMIT
            # acknowledgement is lost. Volatile requests skip the lookup:
            # their replies are never stored, and a storage read could stall
            # a custom responder's failure.
            if isinstance(error, PersistenceError) and self.persisted:
                return self._complete_if_stored(lambda: fail(error))
            return fail(error)

        return self._save().and_then(self._complete()).catch_all(save_failed).or_die()

    def _settle_success(self, outcome: Exit.Exit[Any, Any]) -> Effect[None]:
        if isinstance(outcome, Exit.Success):
            return self._complete()
        # A rejected save failed the transaction, rolling back the handler's
        # writes; the request is left for the owner.
        if self.fenced:
            return self._abandon()
        # The commit can succeed despite the error.
        cause = outcome.cause
        return self._complete_if_stored(lambda: self.restart_from(cause))

    def _complete(self) -> Effect[None]:
        activation = self.activation

        def run() -> None:
            activation.restart_step = None
            if activation.core.storage_enabled:
                activation.core.processed_request_ids.add(self._envelope_id)
            activation.remove_active_request(self.request_id)

        return sync(run)

    def _complete_if_stored[E](self, otherwise: Callable[[], Effect[None, E]]) -> Effect[None, E]:
        """Complete when storage holds the exit anyway, and let callers read
        the stored reply instead of waiting on a handler that will never be
        resumed."""
        storage = self.activation.core.storage
        envelope_id = self._envelope_id

        def decide(stored: bool) -> Effect[None, E]:
            if not stored:
                return otherwise()
            return self._complete().and_then(storage.unregister_reply_handler(envelope_id))

        return _has_stored_exit(self.activation.core, envelope_id).flat_map(decide)

    def _abandon(self) -> Effect[None]:
        """Leave the request for the shard's owner: release the claim so its
        next poll sees it, and let local callers re-route."""
        storage = self.activation.core.storage
        envelope_id = self._envelope_id

        def run() -> Effect[None]:
            self.activation.remove_active_request(self.request_id)
            return (
                log_debug("Abandoning a request whose shard this runner no longer owns")
                .and_then(storage.unregister_reply_handler(envelope_id))
                .and_then(storage.reset_requests([envelope_id]).ignore())
            )

        return suspend(run)


__all__ = ["ExitReply"]
