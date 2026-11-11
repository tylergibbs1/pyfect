"""End-to-end encryption of the entries an event log sends to a remote
(Effect's ``eventlog/EventLogEncryption``).

Entries go in batches of at most 100 entries or 256 KiB of payload (a
larger entry is a batch alone), each encrypted with AES-256-GCM under the
key derived from the identity's root secret. The additional data binds a
batch to its store and entry ids, so a server cannot move it to another
store or relabel it. ``layer`` runs on the ``pyfect.crypto`` services in
context; ``layer_subtle`` (Effect's name, for WebCrypto's ``crypto.subtle``)
on their Web Crypto layers. Both need the extra ``pyfect-dev[eventlog]``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Never

from pyfect import schema as S
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.context import Tag
from pyfect.crypto import aead, digest, secure_random
from pyfect.crypto import web_crypto as web
from pyfect.crypto.crypto_error import CryptoError
from pyfect.effect import die, gen, provide_service
from pyfect.encoding.schema_binary import BytesCodec, to_codec
from pyfect.eventlog._batches import Batch, to_batches
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog._identity_derivation import cached_by_identity, derive_encryption_key
from pyfect.eventlog._transferable_bytes import TransferableBytes
from pyfect.eventlog.event_journal import Entry, EntryId, EntryIdSchema, RemoteEntry
from pyfect.layer import Layer, merge, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as provide_layer
from pyfect.redacted import make as redacted


class EncryptedBatch(S.Class, identifier="effect/eventlog/EventLogEncryption/EncryptedBatch"):
    """Encrypted entries: their ids in plaintext, the iv and the
    ciphertext."""

    entry_ids: tuple[EntryId, ...] = S.field(S.NonEmptyArray(EntryIdSchema), key="entryIds")
    iv: bytes = S.field(TransferableBytes)
    encrypted_batch: bytes = S.field(TransferableBytes, key="encryptedBatch")


class EncryptedRemoteBatch(
    S.Class, identifier="effect/eventlog/EventLogEncryption/EncryptedRemoteBatch"
):
    """An encrypted batch a remote stored, its first entry at ``sequence``."""

    sequence: int = S.field(S.Natural)
    entry_ids: tuple[EntryId, ...] = S.field(S.NonEmptyArray(EntryIdSchema), key="entryIds")
    iv: bytes = S.field(TransferableBytes)
    encrypted_batch: bytes = S.field(TransferableBytes, key="encryptedBatch")


def remote_batch(sequence: int, batch: EncryptedBatch) -> EncryptedRemoteBatch:
    return EncryptedRemoteBatch(
        sequence=sequence,
        entry_ids=batch.entry_ids,
        iv=batch.iv,
        encrypted_batch=batch.encrypted_batch,
    )


def _additional_data(store_id: str, entry_ids: Sequence[bytes]) -> bytes:
    # The store id is length-prefixed, followed by the 16-byte entry ids.
    store = text_encode(store_id)
    return len(store).to_bytes(4) + store + b"".join(entry_ids)


_BATCH_CODEC: BytesCodec[tuple[Entry, ...]] = to_codec(S.NonEmptyArray(Entry))
_encode_batch = S.encode_effect(_BATCH_CODEC)
_decode_batch = S.decode_effect(_BATCH_CODEC)


class EventLogEncryptionService(ABC):
    """What encryption does (Effect's ``EventLogEncryption`` service)."""

    @abstractmethod
    def encrypt(
        self, identity: IdentityService, store_id: str, entries: Sequence[Entry], /
    ) -> Effect[list[EncryptedBatch]]:
        """``entries`` in order, packed into batches and each batch sealed
        with ``identity``'s key, bound to ``store_id`` and its entry ids.
        Never fails; a crypto failure is a defect."""

    @abstractmethod
    def decrypt(
        self, identity: IdentityService, store_id: str, batches: Sequence[EncryptedRemoteBatch], /
    ) -> Effect[list[RemoteEntry]]:
        """The entries of ``batches``; a defect when a batch does not
        decrypt or its entries are not its entry ids."""

    @abstractmethod
    def sha256(self, data: bytes, /) -> Effect[bytes]:
        """The SHA-256 digest of ``data``. Never fails."""

    @property
    @abstractmethod
    def generate_identity(self) -> Effect[IdentityService]:
        """A new identity: a random UUID public key and 32 random bytes of
        root secret."""


class EventLogEncryption(Tag[EventLogEncryptionService], key="effect/eventlog/EventLogEncryption"):
    """How the event log encrypts entries for remotes."""


class _Encryption(EventLogEncryptionService):
    def __init__(
        self,
        aead_service: aead.AeadService,
        digest_service: digest.DigestService,
        random: secure_random.SecureRandomService,
    ) -> None:
        self._aead = aead_service
        self._digest = digest_service
        self._random = random
        self._encryption_key = cached_by_identity(
            lambda root_secret: (
                derive_encryption_key(root_secret)
                .map(lambda derived: derived.encryption_key)
                .pipe(provide_service(digest.Digest, digest_service))
            )
        )

    def encrypt(
        self, identity: IdentityService, store_id: str, entries: Sequence[Entry], /
    ) -> Effect[list[EncryptedBatch]]:
        def seal(
            key: aead.Key[aead.AesGcm], batch: Batch, data: bytes
        ) -> Effect[EncryptedBatch, CryptoError]:
            entry_ids = tuple(entry.id for entry in batch)
            return self._random.random_bytes(12).flat_map(
                lambda iv: self._aead.encrypt(
                    key, data, nonce=iv, aad=_additional_data(store_id, entry_ids)
                ).map(
                    lambda encrypted: EncryptedBatch(
                        entry_ids=entry_ids, iv=iv, encrypted_batch=encrypted
                    )
                )
            )

        @gen
        def run():
            key = yield from self._encryption_key(identity)
            batches = to_batches(entries)
            data = yield from for_each(batches, _encode_batch).or_die()
            return (
                yield from for_each(
                    range(len(batches)),
                    lambda i: seal(key, batches[i], data[i]),
                    concurrency="unbounded",
                ).or_die()
            )

        return run

    def decrypt(
        self, identity: IdentityService, store_id: str, batches: Sequence[EncryptedRemoteBatch], /
    ) -> Effect[list[RemoteEntry]]:
        @gen
        def run():
            key = yield from self._encryption_key(identity)
            decrypted = yield from for_each(
                batches,
                lambda batch: self._aead.decrypt(
                    key,
                    batch.encrypted_batch,
                    nonce=batch.iv,
                    aad=_additional_data(store_id, batch.entry_ids),
                ),
                concurrency="unbounded",
            ).or_die()
            result: list[RemoteEntry] = []
            for batch, data in zip(batches, decrypted, strict=True):
                entries = yield from _decode_batch(data).or_die()
                if [entry.id for entry in entries] != list(batch.entry_ids):
                    return (
                        yield from die(
                            ValueError("Encrypted batch entries do not match its entry ids")
                        )
                    )
                result.extend(
                    RemoteEntry(remote_sequence=batch.sequence + i, entry=entry)
                    for i, entry in enumerate(entries)
                )
            return result

        return run

    def sha256(self, data: bytes, /) -> Effect[bytes]:
        return self._digest.digest(digest.sha256, data)

    @property
    def generate_identity(self) -> Effect[IdentityService]:
        return self._random.uuid_v4().zip_with(
            self._random.random_bytes(32),
            lambda public_key, private_key: IdentityService(public_key, redacted(private_key)),
        )


@gen
def _make():
    aead_service = yield from aead.Aead()
    digest_service = yield from digest.Digest()
    random = yield from secure_random.SecureRandom()
    service: EventLogEncryptionService = _Encryption(aead_service, digest_service, random)
    return service


make: Effect[
    EventLogEncryptionService, Never, aead.Aead | digest.Digest | secure_random.SecureRandom
] = _make
"""An ``EventLogEncryptionService`` from the ``pyfect.crypto`` services. Each
identity's AES-256-GCM key is derived from its root secret with ``Digest``
and cached per identity; batches are encrypted with ``Aead`` under a random
12-byte nonce from ``SecureRandom``, which also generates identities. A
batch that fails authentication, or whose entries are not its entry ids, is
a defect."""

layer: Layer[EventLogEncryption, Never, aead.Aead | digest.Digest | secure_random.SecureRandom] = (
    layer_effect(EventLogEncryption, make)
)
"""``EventLogEncryption`` from the ``Aead``, ``Digest`` and ``SecureRandom``
services: choose the crypto layers yourself, such as ``pyfect.crypto.native``'s."""

_layer_web_crypto: Layer[aead.Aead | digest.Digest | secure_random.SecureRandom] = merge(
    aead.layer_web_crypto, digest.layer_web_crypto
).pipe(provide_merge(secure_random.layer_web_crypto))


def make_encryption_subtle(crypto: web.Crypto) -> Effect[EventLogEncryptionService]:
    """``make`` on the Web Crypto layers of ``Aead``, ``Digest`` and
    ``SecureRandom``, running on ``crypto``."""
    # ``local`` keeps enclosing Web Crypto layers, built on another
    # ``Crypto``, from being reused.
    return make.pipe(
        provide_layer(_layer_web_crypto.pipe(provide_layer(web.layer(crypto))), local=True)
    )


layer_subtle: Layer[EventLogEncryption] = layer.pipe(provide_layer(_layer_web_crypto))
"""``EventLogEncryption`` on the Web Crypto layers of ``Aead``, ``Digest`` and
``SecureRandom``, which run on the ``WebCrypto`` reference."""


__all__ = [
    "EncryptedBatch",
    "EncryptedRemoteBatch",
    "EventLogEncryption",
    "EventLogEncryptionService",
    "layer",
    "layer_subtle",
    "make",
    "make_encryption_subtle",
    "remote_batch",
]
