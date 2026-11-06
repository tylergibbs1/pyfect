"""End-to-end encryption of the entries an event log sends to a remote
(Effect's ``eventlog/EventLogEncryption``).

Entries go in batches of at most 100 entries or 256 KiB of payload (a
larger entry is a batch alone), each encrypted with AES-GCM under the key
derived from the identity's root secret. The additional data binds a
batch to its store and entry ids, so a server cannot move it to another
store or relabel it. ``layer_subtle`` (Effect's name, for WebCrypto's
``crypto.subtle``) runs on the ``cryptography`` package, the extra
``pyfect-dev[eventlog]``.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Protocol

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.context import Tag
from pyfect.effect import die, gen, sync
from pyfect.encoding.schema_binary import BytesCodec, to_codec, wire_name
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog._identity_derivation import GetMaterial, make_get_identity_root_secret_material
from pyfect.eventlog.event_journal import Entry, EntryId, EntryIdSchema, RemoteEntry
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.redacted import make as redacted


class EncryptedBatch(S.Class, identifier="effect/eventlog/EventLogEncryption/EncryptedBatch"):
    """Encrypted entries: their ids in plaintext, the iv and the
    ciphertext."""

    entry_ids: tuple[EntryId, ...] = S.field(
        S.NonEmptyArray(EntryIdSchema).pipe(wire_name("entryIds"))
    )
    iv: bytes = S.field(S.Bytes)
    encrypted_batch: bytes = S.field(S.Bytes.pipe(wire_name("encryptedBatch")))


class EncryptedRemoteBatch(
    EncryptedBatch, identifier="effect/eventlog/EventLogEncryption/EncryptedRemoteBatch"
):
    """An encrypted batch a remote stored, its first entry at ``sequence``."""

    sequence: int = S.field(S.Natural)


def remote_batch(sequence: int, batch: EncryptedBatch) -> EncryptedRemoteBatch:
    return EncryptedRemoteBatch(
        sequence=sequence,
        entry_ids=batch.entry_ids,
        iv=batch.iv,
        encrypted_batch=batch.encrypted_batch,
    )


_MAX_BATCH_ENTRIES = 100
_MAX_BATCH_PAYLOAD_BYTES = 256 * 1024


def _to_batches(entries: Sequence[Entry]) -> list[list[Entry]]:
    batches: list[list[Entry]] = []
    current: list[Entry] = []
    size = 0
    for entry in entries:
        payload = len(entry.payload)
        if current and (
            len(current) == _MAX_BATCH_ENTRIES or size + payload > _MAX_BATCH_PAYLOAD_BYTES
        ):
            batches.append(current)
            current = []
            size = 0
        current.append(entry)
        size += payload
    if current:
        batches.append(current)
    return batches


def _additional_data(store_id: str, entry_ids: Sequence[bytes]) -> bytes:
    # The store id is length-prefixed, followed by the 16-byte entry ids.
    store = text_encode(store_id)
    return len(store).to_bytes(4) + store + b"".join(entry_ids)


_BATCH_CODEC: BytesCodec[tuple[Entry, ...]] = to_codec(S.NonEmptyArray(Entry))


class EventLogEncryptionService(ABC):
    """What encryption does (Effect's ``EventLogEncryption`` service)."""

    @abstractmethod
    def encrypt(
        self, identity: IdentityService, store_id: str, entries: Sequence[Entry], /
    ) -> Effect[list[EncryptedBatch]]: ...

    @abstractmethod
    def decrypt(
        self, identity: IdentityService, store_id: str, batches: Sequence[EncryptedRemoteBatch], /
    ) -> Effect[list[RemoteEntry]]:
        """The entries of ``batches``; a defect when a batch does not
        decrypt or its entries are not its entry ids."""

    def sha256(self, data: bytes, /) -> Effect[bytes]:
        return sync(lambda: hashlib.sha256(data).digest())

    def sha256_string(self, data: bytes, /) -> Effect[str]:
        return sync(lambda: hashlib.sha256(data).hexdigest())

    @property
    def generate_identity(self) -> Effect[IdentityService]:
        """A new identity: a random UUID public key and 32 random bytes of
        root secret."""
        return sync(lambda: IdentityService(str(uuid.uuid4()), redacted(os.urandom(32))))


class EventLogEncryption(Tag[EventLogEncryptionService], key="effect/eventlog/EventLogEncryption"):
    """How the event log encrypts entries for remotes."""


class AesGcm(Protocol):
    """An AES-GCM implementation (Effect passes a WebCrypto ``Crypto``)."""

    def encrypt(self, key: bytes, iv: bytes, data: bytes, aad: bytes, /) -> bytes: ...

    def decrypt(self, key: bytes, iv: bytes, data: bytes, aad: bytes, /) -> bytes:
        """The plaintext; raises when the data or ``aad`` were altered."""
        ...


class _CryptographyAesGcm:
    def encrypt(self, key: bytes, iv: bytes, data: bytes, aad: bytes, /) -> bytes:
        from pyfect.eventlog import _crypto

        return _crypto.aes_gcm_encrypt(key, iv, data, aad)

    def decrypt(self, key: bytes, iv: bytes, data: bytes, aad: bytes, /) -> bytes:
        from pyfect.eventlog import _crypto

        return _crypto.aes_gcm_decrypt(key, iv, data, aad)


class _AesGcmEncryption(EventLogEncryptionService):
    def __init__(self, cipher: AesGcm | None = None) -> None:
        self._material: GetMaterial = make_get_identity_root_secret_material()
        self._cipher: AesGcm = cipher or _CryptographyAesGcm()

    def encrypt(
        self, identity: IdentityService, store_id: str, entries: Sequence[Entry], /
    ) -> Effect[list[EncryptedBatch]]:
        def body():
            key = (yield from self._material(identity)).encryption_key_material
            result: list[EncryptedBatch] = []
            for batch in _to_batches(entries):
                data = yield from S.encode_effect(_BATCH_CODEC)(tuple(batch)).or_die()
                entry_ids = tuple(entry.id for entry in batch)
                iv = os.urandom(12)
                encrypted = self._cipher.encrypt(
                    key, iv, data, _additional_data(store_id, entry_ids)
                )
                result.append(EncryptedBatch(entry_ids=entry_ids, iv=iv, encrypted_batch=encrypted))
            return result

        return gen(body)

    def decrypt(
        self, identity: IdentityService, store_id: str, batches: Sequence[EncryptedRemoteBatch], /
    ) -> Effect[list[RemoteEntry]]:
        def body():
            key = (yield from self._material(identity)).encryption_key_material
            result: list[RemoteEntry] = []
            for batch in batches:
                data = self._cipher.decrypt(
                    key,
                    batch.iv,
                    batch.encrypted_batch,
                    _additional_data(store_id, batch.entry_ids),
                )
                entries = yield from S.decode_effect(_BATCH_CODEC)(data).or_die()
                if [entry.id for entry in entries] != list(batch.entry_ids):
                    yield from die(ValueError("Encrypted batch entries do not match its entry ids"))
                result.extend(
                    RemoteEntry(remote_sequence=batch.sequence + i, entry=entry)
                    for i, entry in enumerate(entries)
                )
            return result

        return gen(body)


def make_encryption_subtle(cipher: AesGcm | None = None) -> Effect[EventLogEncryptionService]:
    """AES-GCM encryption with ``cipher``, by default the ``cryptography``
    package (Effect's ``makeEncryptionSubtle``)."""
    return sync(lambda: _AesGcmEncryption(cipher))


layer_subtle: Layer[EventLogEncryption] = layer_effect(EventLogEncryption, sync(_AesGcmEncryption))
"""The ``EventLogEncryption`` of ``make_encryption_subtle``."""


__all__ = [
    "AesGcm",
    "EncryptedBatch",
    "EncryptedRemoteBatch",
    "EventLogEncryption",
    "EventLogEncryptionService",
    "layer_subtle",
    "make_encryption_subtle",
    "remote_batch",
]
