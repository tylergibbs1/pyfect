"""The storage service of an encrypted server (Effect's ``Storage`` in
``eventlog/EventLogServerEncrypted``)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.eventlog._server_encrypted.models import StorageCompaction
from pyfect.eventlog.event_journal import EntryId, RemoteId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.eventlog.event_log_message import WriteAck
from pyfect.stream import Stream


class StorageService(ABC):
    """Where an encrypted server keeps batches (Effect's ``Storage``).

    A batch owns one sequence per entry from its ``sequence``. ``write``
    stores a batch unless all its ids are stored (so retries are
    idempotent); ``entry_sequences`` gives where each id was first stored.
    A storage that supports remote compaction sets ``compaction``; with an
    active snapshot, ``changes`` serves the snapshot's batches for a start
    at or below its base, then the originals above it."""

    first_sequence: int | None = None
    """The lowest assigned sequence (default 0). Overestimating skips
    entries."""

    compaction: StorageCompaction | None = None

    @property
    @abstractmethod
    def get_id(self) -> Effect[RemoteId]: ...

    @abstractmethod
    def get_or_create_session_auth_binding(
        self, public_key: str, signing_public_key: bytes, /
    ) -> Effect[bytes]:
        """The signing key bound to ``public_key``, binding the given one
        on first use. The server passes only verified keys, and rejects one
        that differs from the returned binding."""

    @abstractmethod
    def write(
        self, public_key: str, store_id: StoreId, batches: Sequence[EncryptedBatch], /
    ) -> Effect[list[EncryptedRemoteBatch]]:
        """Store the batches not already stored, in order."""

    @abstractmethod
    def entry_sequences(
        self, public_key: str, store_id: StoreId, entry_ids: Sequence[EntryId], /
    ) -> Effect[list[WriteAck]]:
        """Where each known entry was first stored."""

    @abstractmethod
    def changes(
        self, public_key: str, store_id: StoreId, start_sequence: int, /
    ) -> Stream[EncryptedRemoteBatch]:
        """The stored batches whose last sequence is at or after
        ``start_sequence``, then new ones."""

    @abstractmethod
    def latest_sequence(self, public_key: str, store_id: StoreId, /) -> Effect[int | None]:
        """The sequence of the last stored entry, ``None`` when there is none."""


class Storage(Tag[StorageService], key="effect/eventlog/EventLogServer/Storage"):
    """The storage of an encrypted server."""
