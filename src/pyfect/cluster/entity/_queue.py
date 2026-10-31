"""An entity served from a mailbox queue (Effect's ``toLayerQueue``): its
behaviour takes requests from the queue and answers them with a
``Replier``."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, cast

from pyfect import exit as Exit
from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.cluster.entity._handlers import EntityHandlers
from pyfect.cluster.entity._request import Request
from pyfect.effect import callback, from_exit, gen, sync
from pyfect.queue import Dequeue, Queue
from pyfect.scope import Scope, fork_scoped
from pyfect.stream import Stream, from_queue, unwrap

if TYPE_CHECKING:
    from pyfect.cluster.entity._entity import Entity

type _Resume = Callable[[Effect[Any, Any]], None]


class Replier:
    """Answers the requests a queue-based entity takes. A streamed RPC is
    answered with a ``Stream`` or a ``Dequeue`` of its items."""

    __slots__ = ("_resumes",)

    def __init__(self, resumes: dict[int, tuple[Request[Any], _Resume]]) -> None:
        self._resumes = resumes

    def complete(self, request: Request[Any], exit: Exit.Exit[Any, Any]) -> Effect[None]:
        def run() -> None:
            found = self._resumes.pop(id(request), None)
            if found is not None:
                found[1](from_exit(exit))

        return sync(run)

    def succeed(self, request: Request[Any], value: object) -> Effect[None]:
        return self.complete(request, Exit.succeed(value))

    def fail(self, request: Request[Any], error: object) -> Effect[None]:
        return self.complete(request, Exit.fail(error))

    def fail_cause(self, request: Request[Any], cause: Cause[Any]) -> Effect[None]:
        return self.complete(request, Exit.Failure(cause))


type Behaviour[R] = Callable[[Dequeue[Request[Any], Never], Replier], Effect[Never, Never, R]]


def queue_handlers[R](
    entity: type[Entity], behaviour: Behaviour[R]
) -> Effect[EntityHandlers[Any, Any], Never, R | Scope]:
    """Handlers putting each request in a mailbox, with ``behaviour``
    forked into the current scope to answer them."""

    @gen
    def make():
        mailbox = yield from Queue[Request[Any], Never].unbounded()
        resumes: dict[int, tuple[Request[Any], _Resume]] = {}

        def enqueue(request: Request[Any]) -> Effect[Any, Any]:
            def register(resume: _Resume) -> None:
                mailbox.offer_unsafe(request)
                resumes[id(request)] = (request, resume)

            return callback(register)

        def stream_of(value: Any) -> Stream[Any, Any, Any]:
            if isinstance(value, Stream):
                return cast("Stream[Any, Any, Any]", value)
            return from_queue(cast("Dequeue[Any, Any]", value))

        def enqueue_stream(request: Request[Any]) -> Stream[Any, Any, Any]:
            return unwrap(enqueue(request).map(stream_of))

        by_tag = {
            tag: enqueue_stream if rpc.is_stream else enqueue for tag, rpc in entity.rpcs.items()
        }

        def fail_all(cause: Cause[Any]) -> Effect[None]:
            def run() -> None:
                waiting = list(resumes.values())
                resumes.clear()
                for _, resume in waiting:
                    resume(from_exit(Exit.Failure(cause)))

            return sync(run)

        yield from fork_scoped(
            behaviour(mailbox, Replier(resumes)).catch_cause(fail_all).interruptible()
        )
        return EntityHandlers[Any, Any](entity, by_tag)

    return make


__all__ = ["Behaviour", "Replier", "queue_handlers"]
