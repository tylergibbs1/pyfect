"""The handlers of ``EventLogCompactionRpcs`` over a storage's compaction
primitives (Effect's ``layerCompactionRpcHandlers``).

Every request needs the identity authenticated on the connection; without
storage compaction every handler fails ``NotFound``. A connection keeps
its unjoined segment pieces per identity, store and stage, so pieces of
different stages never join.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Literal, Never

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.eventlog._server_encrypted.models import (
    BeginBusy,
    CompactionInvalidRequest,
    CompactionNotFound,
    StorageCompaction,
)
from pyfect.eventlog._server_encrypted.policy import check_snapshot, is_compaction_wanted
from pyfect.eventlog._server_encrypted.storage import StorageService
from pyfect.eventlog.event_journal import StoreId
from pyfect.eventlog.event_log_message import (
    ChunkedMessage,
    CompactionBeginResult,
    CompactionBusy,
    CompactionCommitPayload,
    CompactionFetchPayload,
    CompactionInputHeader,
    CompactionNoOp,
    CompactionNotWanted,
    CompactionPartPayload,
    CompactionScopePayload,
    CompactionStagePayload,
    CompactionStarted,
    CompactionStatus,
    EventLogAuthentication,
    EventLogCompactionRpcs,
    EventLogProtocolError,
    JoinState,
    ProtocolErrorCode,
    SingleMessage,
    decode_compaction_segment,
    encode_changes_encrypted,
    encode_compaction_input_headers,
)
from pyfect.eventlog.event_log_server import AuthenticatedIdentities, make_framer
from pyfect.layer import Layer
from pyfect.rpc import RpcRequest, ServerClient
from pyfect.rpc.group import HandlersFor
from pyfect.stream import Stream
from pyfect.stream import unwrap as stream_unwrap

type _Scoped = CompactionScopePayload | CompactionStagePayload
type _StageKey = tuple[str, StoreId, str]
type _Frame = SingleMessage | ChunkedMessage


class _PendingSegments(
    Tag[dict[_StageKey, JoinState]],
    key="effect/eventlog/EventLogServerEncrypted/PendingSegments",
):
    """One connection's unjoined segment pieces by identity, store and
    stage."""


def _stage_key(request: CompactionStagePayload) -> _StageKey:
    return (request["public_key"], request["store_id"], request["stage_id"])


def _pending_segments(client: ServerClient, request: CompactionStagePayload) -> JoinState:
    found = client.annotations.get_option(_PendingSegments)
    stages = found.value if found is not None else {}
    if found is None:
        client.annotate(_PendingSegments, stages)
    return stages.setdefault(_stage_key(request), ChunkedMessage.initial_join_state())


def _release_pending_segments(client: ServerClient, request: CompactionStagePayload) -> None:
    found = client.annotations.get_option(_PendingSegments)
    if found is not None:
        found.value.pop(_stage_key(request), None)


def _protocol_error(
    request_tag: str, request: _Scoped, code: ProtocolErrorCode, message: str
) -> EventLogProtocolError:
    return EventLogProtocolError(
        request_tag=request_tag,
        public_key=request["public_key"],
        store_id=request["store_id"],
        code=code,
        message=message,
    )


def _from_compaction_error(
    request_tag: str, request: _Scoped
) -> Callable[[CompactionNotFound | CompactionInvalidRequest], EventLogProtocolError]:
    def convert(error: CompactionNotFound | CompactionInvalidRequest) -> EventLogProtocolError:
        if isinstance(error, CompactionNotFound):
            return _protocol_error(request_tag, request, "NotFound", "Compaction stage not found")
        return _protocol_error(request_tag, request, "InvalidRequest", error.message)

    return convert


def layer_compaction_rpc_handlers(
    storage: StorageService,
) -> Layer[HandlersFor[EventLogCompactionRpcs], Never, EventLogAuthentication]:
    compaction = storage.compaction
    to_frames = make_framer()

    def frames(data: bytes) -> tuple[_Frame, ...]:
        return tuple(to_frames(data))

    def with_compaction[A](
        request_tag: str,
        request: RpcRequest[_Scoped],
        f: Callable[[StorageCompaction], Effect[A, CompactionNotFound | CompactionInvalidRequest]],
    ) -> Effect[A, EventLogProtocolError]:
        def run() -> Effect[A, EventLogProtocolError]:
            payload = request.payload
            authenticated = request.client.annotations.get_option(AuthenticatedIdentities)
            if authenticated is None or payload["public_key"] not in authenticated.value:
                return fail(
                    _protocol_error(
                        request_tag, payload, "Forbidden", "Identity is not authenticated"
                    )
                )
            if compaction is None:
                return fail(
                    _protocol_error(request_tag, payload, "NotFound", "Compaction is not supported")
                )
            return f(compaction).map_error(_from_compaction_error(request_tag, payload))

        return suspend(run)

    def with_compaction_stream[A](
        request_tag: str,
        request: RpcRequest[_Scoped],
        f: Callable[[StorageCompaction], Stream[A, CompactionNotFound]],
    ) -> Stream[A, EventLogProtocolError]:
        convert = _from_compaction_error(request_tag, request.payload)
        return stream_unwrap(
            with_compaction(request_tag, request, lambda c: succeed(f(c).map_error(convert)))
        )

    def status(
        request: RpcRequest[CompactionScopePayload],
    ) -> Effect[CompactionStatus, EventLogProtocolError]:
        payload = request.payload

        def run(c: StorageCompaction) -> Effect[CompactionStatus]:
            return c.status(payload["public_key"], payload["store_id"]).map(
                lambda s: CompactionStatus(
                    wanted=is_compaction_wanted(s, c.config.threshold_floor), head=s.head
                )
            )

        return with_compaction("CompactionStatus", request, run)

    def begin(
        request: RpcRequest[CompactionScopePayload],
    ) -> Effect[CompactionBeginResult, EventLogProtocolError]:
        payload = request.payload

        def run(
            c: StorageCompaction,
        ) -> Generator[Effect[Any, Never, Never], Any, CompactionBeginResult]:
            current = yield from c.status(payload["public_key"], payload["store_id"])
            if not is_compaction_wanted(current, c.config.threshold_floor):
                return CompactionNotWanted()
            result = yield from c.begin(
                payload["public_key"], payload["store_id"], through=current.lag_head
            )
            if isinstance(result, BeginBusy):
                return CompactionBusy()
            return CompactionStarted(stage_id=result.stage_id)

        return with_compaction("CompactionBegin", request, lambda c: gen(lambda: run(c)))

    def input_(
        request: RpcRequest[CompactionStagePayload],
    ) -> Stream[_Frame, EventLogProtocolError]:
        payload = request.payload

        def encode(headers: tuple[CompactionInputHeader, ...]) -> Effect[tuple[_Frame, ...]]:
            return encode_compaction_input_headers(headers).or_die().map(frames)

        return with_compaction_stream(
            "CompactionInput",
            request,
            lambda c: (
                c.input_headers(payload["public_key"], payload["store_id"], payload["stage_id"])
                .map(lambda h: CompactionInputHeader(sequence=h.sequence, entry_ids=h.entry_ids))
                .map_array_effect(encode)
            ),
        )

    def fetch(request: RpcRequest[CompactionFetchPayload]) -> Stream[_Frame, EventLogProtocolError]:
        payload = request.payload
        return with_compaction_stream(
            "CompactionFetch",
            request,
            lambda c: c.fetch(
                payload["public_key"], payload["store_id"], payload["stage_id"], payload["batches"]
            ).map_array_effect(
                lambda batches: encode_changes_encrypted(batches).or_die().map(frames)
            ),
        )

    def part(request: RpcRequest[CompactionPartPayload]) -> Effect[None, EventLogProtocolError]:
        payload = request.payload
        public_key, store_id, stage_id = (
            payload["public_key"],
            payload["store_id"],
            payload["stage_id"],
        )

        def run(
            c: StorageCompaction,
        ) -> Generator[Effect[Any, CompactionInvalidRequest | CompactionNotFound, Never], Any]:
            data = ChunkedMessage.join(_pending_segments(request.client, payload), payload["chunk"])
            if data is None:
                return
            batches = yield from decode_compaction_segment(data).catch_all(
                lambda _: c.abort(public_key, store_id, stage_id).and_then(
                    fail(CompactionInvalidRequest(stage_id, "Invalid segment"))
                )
            )
            yield from c.stage_part(public_key, store_id, stage_id, payload["chunk"].id, batches)

        return with_compaction("CompactionPart", request, lambda c: gen(lambda: run(c)))

    def abort(request: RpcRequest[CompactionStagePayload]) -> Effect[None, EventLogProtocolError]:
        payload = request.payload

        def run(c: StorageCompaction) -> Effect[None]:
            _release_pending_segments(request.client, payload)
            return c.abort(payload["public_key"], payload["store_id"], payload["stage_id"])

        return with_compaction("CompactionAbort", request, run)

    def commit(
        request: RpcRequest[CompactionCommitPayload],
    ) -> Effect[Literal["Committed", "Superseded"], EventLogProtocolError]:
        payload = request.payload
        public_key, store_id, stage_id = (
            payload["public_key"],
            payload["store_id"],
            payload["stage_id"],
        )

        def run(
            c: StorageCompaction,
        ) -> Effect[
            Literal["Committed", "Superseded"], CompactionNotFound | CompactionInvalidRequest
        ]:
            _release_pending_segments(request.client, payload)
            result = payload["result"]
            if isinstance(result, CompactionNoOp):
                return c.record_no_op(public_key, store_id, stage_id).as_("Committed")

            def abort_invalid(
                error: CompactionNotFound | CompactionInvalidRequest,
            ) -> Effect[None]:
                if isinstance(error, CompactionInvalidRequest):
                    return c.abort(public_key, store_id, stage_id)
                return succeed(None)

            return (
                check_snapshot(c, public_key, store_id, stage_id, result.segment_count)
                .tap_error(abort_invalid)
                .flat_map(lambda sequences: c.commit(public_key, store_id, stage_id, sequences))
            )

        return with_compaction("CompactionCommit", request, run)

    handlers = (
        EventLogCompactionRpcs.handlers()
        .handle(EventLogCompactionRpcs.compaction_status)(status)
        .handle(EventLogCompactionRpcs.compaction_begin)(begin)
        .handle(EventLogCompactionRpcs.compaction_input)(input_)
        .handle(EventLogCompactionRpcs.compaction_fetch)(fetch)
        .handle(EventLogCompactionRpcs.compaction_part)(part)
        .handle(EventLogCompactionRpcs.compaction_abort)(abort)
        .handle(EventLogCompactionRpcs.compaction_commit)(commit)
    )
    return EventLogCompactionRpcs.to_layer(handlers)
