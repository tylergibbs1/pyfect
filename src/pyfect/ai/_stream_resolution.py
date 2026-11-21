"""``stream_text``'s tool-call resolution: the provider's parts as they
come, each tool call's handler started once the stream has moved past the
call, and the finish parts after every tool result.

A tool call waits one chunk before its handler starts, so a truncating
finish (``"length"``, ``"content-filter"`` ...) arriving next means the
handler never runs. On such a finish the running handlers are interrupted
and each tool call left without a result gets an ``execution-interrupted``
failure result.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Never, cast

import pyfect as fx
from pyfect._core import Effect
from pyfect.ai import _approvals as A
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai import toolkit as K
from pyfect.ai.id_generator import IdGenerator
from pyfect.ai.tool import AnyTool, is_client_executed
from pyfect.fiber_set import FiberSet
from pyfect.queue import Queue
from pyfect.semaphore import Semaphore
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC
from pyfect.stream import _sources as StreamSources
from pyfect.stream._many import merge_all

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency

type EncodedPart = Any
type Chunk = Sequence[EncodedPart]

_COMPLETE: tuple[str, ...] = ("stop", "tool-calls", "pause")


def resolvable_tool(kit: K.WithHandler[Any, Any, Any, Any], name: object) -> AnyTool | None:
    """The tool whose handler resolves calls to ``name``. Calls to unknown and
    client-executed tools are left for the caller to answer. Every lookup that decides
    whether to run, interrupt or wait for a tool call goes through here."""
    tool = kit.tools.get(name) if isinstance(name, str) else None
    return None if tool is None or is_client_executed(tool) else tool


def incomplete_reason(reasons: Sequence[object]) -> str | None:
    """The first finish reason that leaves tool calls unanswered."""
    for reason in reasons:
        if reason not in _COMPLETE:
            return reason if isinstance(reason, str) else "unknown"
    return None


def interrupted_result(id: str, name: str, reason: str) -> R.AnyToolResultPart:
    """The failure result of a tool call a truncated response left
    unanswered."""
    result = {
        "type": "execution-interrupted",
        "reason": "Tool call execution was interrupted because the response finished "
        f'with reason "{reason}"',
    }
    return R.tool_result_part(
        id=id, name=name, is_failure=True, result=result, encoded_result=result
    )


def result_part(id: str, name: str, result: K.HandlerResult) -> R.AnyToolResultPart:
    return R.tool_result_part(
        id=id,
        name=name,
        is_failure=result.is_failure,
        result=result.result,
        encoded_result=result.encoded_result,
        preliminary=result.preliminary,
        model_output=result.model_output,
    )


def resolve_calls(
    kit: K.WithHandler[Any, Any, Any, Any],
    calls: Sequence[EncodedPart],
    messages: Sequence[P.Message],
    concurrency: Concurrency,
) -> Stream[R.AnyToolResultPart | R.ToolApprovalRequestPart, Any, Any]:
    """Each call's results: ``execution-denied`` when the user denied it,
    the handler's when approved or not needing approval, else an approval
    request."""
    approvals = A.collect(messages)
    approved = {approval.tool_call_id for approval in approvals.approved}
    denied = {approval.tool_call_id: approval for approval in approvals.denied}

    def handle(id: str, name: str, call: EncodedPart) -> Stream[R.AnyToolResultPart, Any, Any]:
        handled = kit.handle(name, call.get("params"), id)
        return StreamC.unwrap(handled).map(lambda result: result_part(id, name, result))

    def run(call: EncodedPart) -> Stream[Any, Any, Any]:
        id, name = cast("str", call["id"]), cast("str", call["name"])
        tool = resolvable_tool(kit, name)
        if tool is None:
            return StreamC.empty
        if id in denied:
            return StreamC.make(A.denied_result(id, name, denied[id].reason))
        if id in approved:
            return handle(id, name, call)
        return StreamC.unwrap(
            A.needs_approval(tool, call, messages).flat_map(
                lambda needed: (
                    approval_request(id).map(StreamC.make)
                    if needed
                    else fx.succeed(handle(id, name, call))
                )
            )
        )

    return merge_all([run(call) for call in calls], concurrency=concurrency)


def approval_request(tool_call_id: str) -> Effect[R.ToolApprovalRequestPart, Never, IdGenerator]:
    return IdGenerator().flat_map(
        lambda generator: generator.generate_id().map(
            lambda approval_id: R.ToolApprovalRequestPart(
                approval_id=approval_id, tool_call_id=tool_call_id
            )
        )
    )


def resolve_stream(
    kit: K.WithHandler[Any, Any, Any, Any],
    provider: Stream[EncodedPart, Any, Any],
    on_chunk: Callable[[Chunk], Effect[list[Any], Any, Any]],
    concurrency: Concurrency,
    *,
    messages: Sequence[P.Message],
) -> Effect[Stream[Any, Any, Any], Any, Any]:
    """The stream of ``provider``'s parts (decoded and
    checked by ``on_chunk``) with the tool results of ``kit``'s tools, or
    approval requests for the calls needing approval (in the context of
    ``messages``). Needs a ``Scope``, which the handlers and the provider's
    run live in."""

    def start(queue: Queue[Any, Any]) -> Effect[Stream[Any, Any, Any], Any, Any]:
        def run(fibers: FiberSet[None, Any], semaphore: Semaphore | None) -> Effect[Any, Any, Any]:
            resolution = _Resolution(kit, queue, fibers, semaphore, messages)
            return resolution.run(provider, on_chunk).fork_scoped()

        return (
            FiberSet[None, Any]
            .make()
            .flat_map(lambda fibers: _permits(concurrency).flat_map(lambda s: run(fibers, s)))
            .as_(StreamSources.from_queue(queue))
        )

    return Queue[Any, Any].unbounded().flat_map(start)


def _permits(concurrency: Concurrency) -> Effect[Semaphore | None]:
    if concurrency is None or concurrency == "unbounded":
        return fx.succeed(None)
    return cast("Effect[Semaphore | None]", Semaphore.make(concurrency))


class _Resolution:
    """The state of one streamed response: the tool calls waiting for the
    next chunk, those without a final result yet, and the finish parts."""

    def __init__(
        self,
        kit: K.WithHandler[Any, Any, Any, Any],
        queue: Queue[Any, Any],
        fibers: FiberSet[None, Any],
        semaphore: Semaphore | None,
        messages: Sequence[P.Message],
    ) -> None:
        self.kit = kit
        self.messages = messages
        self.queue = queue
        self.fibers = fibers
        self.semaphore = semaphore
        self.buffered: list[EncodedPart] = []
        self.pending: dict[str, str] = {}
        self.finishes: list[R.FinishPart] = []

    def _incomplete(self) -> str | None:
        return incomplete_reason([finish.reason for finish in self.finishes])

    def _handle(self, call: EncodedPart) -> Effect[None, Any, Any]:
        id, name = cast("str", call["id"]), cast("str", call["name"])
        tool = resolvable_tool(self.kit, name)
        if tool is None:
            return fx.void

        def request(approval_id: str) -> None:
            part = R.ToolApprovalRequestPart(approval_id=approval_id, tool_call_id=id)
            self.queue.offer_unsafe(part)
            self.pending.pop(id, None)

        def run(needed: bool) -> Effect[None, Any, Any]:
            if needed:
                ids = IdGenerator().flat_map(lambda generator: generator.generate_id())
                return ids.map(request)
            return self._run_handler(id, name, call)

        return A.needs_approval(tool, call, self.messages).flat_map(run)

    def _run_handler(self, id: str, name: str, call: EncodedPart) -> Effect[None, Any, Any]:
        def offer(result: K.HandlerResult) -> Effect[None]:
            def run() -> None:
                self.queue.offer_unsafe(result_part(id, name, result))
                if not result.preliminary:
                    self.pending.pop(id, None)

            return fx.sync(run)

        handled = self.kit.handle(name, call.get("params"), id)
        return StreamC.unwrap(handled).run_for_each(offer)

    def _fork_buffered(self) -> Effect[None, Any, Any]:
        def run() -> Effect[None, Any, Any]:
            calls, self.buffered = self.buffered, []
            forks: list[Effect[object, Any, Any]] = []
            for call in calls:
                handle = self._handle(call)
                if self.semaphore is not None:
                    handle = self.semaphore.with_permits(handle)
                forks.append(self.fibers.run(handle))
            return fx.for_each(forks, lambda fork: fork).as_(None)

        return fx.suspend(run)

    def _chunk(
        self, on_chunk: Callable[[Chunk], Effect[list[Any], Any, Any]], chunk: Chunk
    ) -> Effect[None, Any, Any]:
        def emitted(parts: list[Any]) -> Effect[None, Any, Any]:
            immediate: list[Any] = []
            for part in parts:
                if isinstance(part, R.FinishPart):
                    self.finishes.append(part)
                else:
                    immediate.append(part)
            offered = self.queue.offer_all(immediate).as_(None) if immediate else fx.void
            start = self._fork_buffered() if self._incomplete() is None else fx.void

            def buffer() -> None:
                for part in chunk:
                    if part.get("type") == "tool-call" and part.get("providerExecuted") is not True:
                        if resolvable_tool(self.kit, part.get("name")) is not None:
                            self.pending[cast("str", part["id"])] = cast("str", part["name"])
                        self.buffered.append(part)

            return offered.and_then(start).and_then(fx.sync(buffer))

        return on_chunk(chunk).flat_map(emitted)

    def _settle(self) -> Effect[None, Any, Any]:
        def run() -> Effect[None, Any, Any]:
            reason = self._incomplete()
            if reason is None:
                return self._fork_buffered().and_then(
                    self.fibers.join().race_first(self.fibers.await_empty())
                )
            return self.fibers.clear().and_then(
                fx.suspend(
                    lambda: self.queue.offer_all(
                        [interrupted_result(id, name, reason) for id, name in self.pending.items()]
                    ).as_(None)
                )
            )

        return fx.suspend(run)

    def run(
        self,
        provider: Stream[EncodedPart, Any, Any],
        on_chunk: Callable[[Chunk], Effect[list[Any], Any, Any]],
    ) -> Effect[None, Any, Any]:
        return (
            provider.run_for_each_array(lambda chunk: self._chunk(on_chunk, chunk))
            .and_then(self._settle())
            .and_then(fx.suspend(lambda: self.queue.offer_all(self.finishes)))
            .and_then(self.queue.end())
            .tap_cause(self.queue.fail_cause)
            .as_(None)
        )
