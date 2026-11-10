"""The client side of encrypted remote compaction (Effect's
``EventLogRemoteCompaction`` and ``makeEncryptedCompaction`` in
``eventlog/EventLogRemote``)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pyfect._core import Effect
from pyfect.effect import gen
from pyfect.eventlog._batches import to_batches
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog._remote_error import EventLogRemoteError
from pyfect.eventlog.event_journal import Entry, RemoteEntry, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EventLogEncryptionService
from pyfect.eventlog.event_log_message import (
    ChunkedMessage,
    CompactionBeginResult,
    CompactionInputHeader,
    CompactionResult,
    CompactionStatus,
    EventLogCompactionRpcs,
    SingleMessage,
    decode_changes_encrypted,
    decode_compaction_input_headers,
    encode_compaction_segment,
)
from pyfect.rpc.client_error import RpcClientError
from pyfect.stream import Stream


@dataclass(frozen=True, slots=True)
class CompactionStage:
    """A stage ``EventLogRemoteCompaction.begin`` opened, with the identity
    and store it belongs to."""

    identity: IdentityService
    store_id: StoreId
    stage_id: str


class EventLogRemoteCompaction(Protocol):
    """Client side of encrypted remote compaction. A run opens a stage with
    ``begin``, reads its input headers with ``input``, fetches the batches
    it needs with ``fetch``, uploads the kept entries with ``upload`` and
    calls ``commit``; ``abort`` releases a stage that will not be
    committed."""

    def status(
        self, *, identity: IdentityService, store_id: StoreId
    ) -> Effect[CompactionStatus, EventLogRemoteError]: ...

    def begin(
        self, *, identity: IdentityService, store_id: StoreId
    ) -> Effect[CompactionBeginResult, EventLogRemoteError]: ...

    def input(
        self, stage: CompactionStage, /
    ) -> Stream[CompactionInputHeader, EventLogRemoteError]:
        """The stage's input batch headers, in input order."""
        ...

    def fetch(
        self, stage: CompactionStage, sequences: Sequence[int], /
    ) -> Stream[RemoteEntry, EventLogRemoteError]:
        """The input batches at ``sequences``, decrypted."""
        ...

    def upload(
        self, stage: CompactionStage, entries: Sequence[Entry], /
    ) -> Effect[int, EventLogRemoteError]:
        """Encrypt the kept ``entries`` (in input-sequence order) and upload
        them in segments of about ``ChunkedMessage.chunk_size``, succeeding
        with the segment count. An oversized segment is split into pieces,
        and a segment is resent in full after a dropped connection."""
        ...

    def commit(
        self, stage: CompactionStage, result: CompactionResult, /
    ) -> Effect[Literal["Committed", "Superseded"], EventLogRemoteError]: ...

    def abort(self, stage: CompactionStage, /) -> Effect[None]:
        """Release the stage, ignoring failures."""
        ...


class RemoteSession(Protocol):
    """What a remote's compaction client shares with the remote: its
    authentication."""

    def request[A, E](
        self, method: str, identity: IdentityService, effect: Effect[A, E], /
    ) -> Effect[A, EventLogRemoteError]:
        """Authenticate, run ``effect``, and authenticate again after a
        refusal."""
        ...

    def framed[A, E, E2](
        self,
        method: str,
        identity: IdentityService,
        frames: Callable[[], Stream[SingleMessage | ChunkedMessage, E]],
        decode: Callable[[bytes], Effect[Iterable[A], E2]],
        /,
    ) -> Stream[A, EventLogRemoteError]:
        """Authenticate, then join and decode a framed response stream."""
        ...


# How many times a segment is sent before a dropped connection, an
# ``RpcClientError``, fails the upload.
_SEGMENT_ATTEMPTS = 3


def _encoded_batch_size(batch: EncryptedBatch) -> int:
    # Ignores the segment framing.
    return len(batch.encrypted_batch) + len(batch.iv) + len(batch.entry_ids) * 16


def _is_client_error(error: object) -> bool:
    return isinstance(error, RpcClientError)


@dataclass(frozen=True, slots=True)
class EncryptedCompaction:
    """``EventLogRemoteCompaction`` over a compaction RPC client, encrypting
    with the ``EventLogEncryption``."""

    session: RemoteSession
    client: EventLogCompactionRpcs
    encryption: EventLogEncryptionService

    def status(
        self, *, identity: IdentityService, store_id: StoreId
    ) -> Effect[CompactionStatus, EventLogRemoteError]:
        call = self.client.compaction_status(
            {"public_key": identity.public_key, "store_id": store_id}
        )
        return self.session.request("compactionStatus", identity, call)

    def begin(
        self, *, identity: IdentityService, store_id: StoreId
    ) -> Effect[CompactionBeginResult, EventLogRemoteError]:
        call = self.client.compaction_begin(
            {"public_key": identity.public_key, "store_id": store_id}
        )
        return self.session.request("compactionBegin", identity, call)

    def input(
        self, stage: CompactionStage, /
    ) -> Stream[CompactionInputHeader, EventLogRemoteError]:
        return self.session.framed(
            "compactionInput",
            stage.identity,
            lambda: self.client.compaction_input(
                {
                    "public_key": stage.identity.public_key,
                    "store_id": stage.store_id,
                    "stage_id": stage.stage_id,
                }
            ),
            decode_compaction_input_headers,
        )

    def fetch(
        self, stage: CompactionStage, sequences: Sequence[int], /
    ) -> Stream[RemoteEntry, EventLogRemoteError]:
        def decode(data: bytes):
            return decode_changes_encrypted(data).flat_map(
                lambda batches: self.encryption.decrypt(stage.identity, stage.store_id, batches)
            )

        return self.session.framed(
            "compactionFetch",
            stage.identity,
            lambda: self.client.compaction_fetch(
                {
                    "public_key": stage.identity.public_key,
                    "store_id": stage.store_id,
                    "stage_id": stage.stage_id,
                    "batches": tuple(sequences),
                }
            ),
            decode,
        )

    def upload(
        self, stage: CompactionStage, entries: Sequence[Entry], /
    ) -> Effect[int, EventLogRemoteError]:
        def body():
            segment: list[EncryptedBatch] = []
            segment_bytes = 0
            segment_count = 0

            # The server forgets a segment's pieces when the connection drops,
            # so a retry resends all of them.
            def send_segment():
                nonlocal segment, segment_bytes, segment_count
                if not segment:
                    return
                batches = segment
                id = segment_count
                segment_count += 1
                segment = []
                segment_bytes = 0
                data = yield from encode_compaction_segment(batches).map_error(
                    lambda cause: EventLogRemoteError(method="compactionUpload", cause=cause)
                )
                pieces = ChunkedMessage.split(id, data)

                def send_pieces():
                    for chunk in pieces:
                        yield from self.client.compaction_part(
                            {
                                "public_key": stage.identity.public_key,
                                "store_id": stage.store_id,
                                "stage_id": stage.stage_id,
                                "chunk": chunk,
                            }
                        )

                sent = gen(send_pieces).retry(while_=_is_client_error, times=_SEGMENT_ATTEMPTS - 1)
                yield from self.session.request("compactionUpload", stage.identity, sent)

            # Whole batches go into a segment until the next one would take it
            # past ``ChunkedMessage.chunk_size``.
            for batch in to_batches(entries):
                encrypted = yield from self.encryption.encrypt(
                    stage.identity, stage.store_id, batch
                )
                for sealed in encrypted:
                    size = _encoded_batch_size(sealed)
                    if segment and segment_bytes + size > ChunkedMessage.chunk_size:
                        yield from send_segment()
                    segment.append(sealed)
                    segment_bytes += size
            yield from send_segment()
            return segment_count

        return gen(body)

    def commit(
        self, stage: CompactionStage, result: CompactionResult, /
    ) -> Effect[Literal["Committed", "Superseded"], EventLogRemoteError]:
        call = self.client.compaction_commit(
            {
                "public_key": stage.identity.public_key,
                "store_id": stage.store_id,
                "stage_id": stage.stage_id,
                "result": result,
            }
        )
        return self.session.request("compactionCommit", stage.identity, call)

    def abort(self, stage: CompactionStage, /) -> Effect[None]:
        call = self.client.compaction_abort(
            {
                "public_key": stage.identity.public_key,
                "store_id": stage.store_id,
                "stage_id": stage.stage_id,
            }
        )
        return self.session.request("compactionAbort", stage.identity, call).ignore()
