"""Ports of Effect's ``effect/test/eventlog/EventLogEncryption.test.ts``.
Each test's docstring is the Effect test title. The recorded batch is
Effect's: written by the Web Crypto implementation before the crypto module
migration, with root secret bytes 0..31, store ``"default"``, and AES-GCM
under the v1-derived key."""

import pyfect as fx
from pyfect import testing
from pyfect.crypto import aead, digest, secure_random
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_encryption as Enc
from pyfect.eventlog.event_journal import Entry, EntryId


def _entry_id(first: int) -> EntryId:
    return EntryId(bytes(first + i for i in range(16)))


_identity = L.decode_identity_string(
    "eyJwdWJsaWNLZXkiOiJldmVudGxvZy1jb21wYXQiLCJwcml2YXRlS2V5IjoiQUFFQ0F3UUZCZ2NJQ1FvTERBME9EeEFSRWhNVUZSWVhHQmthR3h3ZEhoOD0ifQ"
)

_recorded_batch = Enc.EncryptedRemoteBatch(
    sequence=7,
    entry_ids=(_entry_id(0x10), _entry_id(0x20)),
    iv=bytes.fromhex("1b42ae41a7edba8ede50c991"),
    encrypted_batch=bytes.fromhex(
        "3fb6370cc472fb5b873f6eed54976f2ae7168808f387f5e948038943e9e01b9385f76daa821792ec93f9d7587f5b1d6d"
        "dbe84add43003856a9e6dec99f59955fef8f40f5e6dfafc7bfac6f71a6795b06229b9568fa321e65d9cbcd2617c796ba"
        "e79c347bbf8ce3552e4eabaed6491f123cd69b4e"
    ),
)


@testing.effect
def test_decrypts_batches_written_before_the_crypto_module_migration():
    """decrypts batches written before the crypto module migration"""

    def body():
        encryption = yield from Enc.EventLogEncryption()
        entries = yield from encryption.decrypt(_identity, "default", [_recorded_batch])
        assert [
            (r.remote_sequence, r.entry.id, r.entry.event, r.entry.primary_key, r.entry.payload)
            for r in entries
        ] == [
            (7, _entry_id(0x10), "UserCreated", "user-1", bytes([1, 2, 3])),
            (8, _entry_id(0x20), "UserRenamed", "user-1", bytes([4, 5])),
        ]

    yield from fx.gen(body).pipe(fx.provide(Enc.layer_subtle))


@testing.effect
def test_dies_when_a_recorded_batch_is_replayed_for_another_store():
    """dies when a recorded batch is replayed for another store"""

    def body():
        encryption = yield from Enc.EventLogEncryption()
        exit = yield from encryption.decrypt(_identity, "other", [_recorded_batch]).exit()
        assert isinstance(exit, fx.Failure)
        assert exit.cause.has_dies

    yield from fx.gen(body).pipe(fx.provide(Enc.layer_subtle))


@testing.effect
def test_encrypts_in_the_recorded_format_on_the_crypto_services_in_context():
    """encrypts in the recorded format on the crypto services in context"""

    def body():
        encryption = yield from Enc.EventLogEncryption()
        batches = yield from encryption.encrypt(
            _identity,
            "default",
            [
                Entry(
                    id=_entry_id(0x10),
                    event="UserCreated",
                    primary_key="user-1",
                    payload=bytes([1, 2, 3]),
                ),
                Entry(
                    id=_entry_id(0x20),
                    event="UserRenamed",
                    primary_key="user-1",
                    payload=bytes([4, 5]),
                ),
            ],
        )
        assert batches == [
            Enc.EncryptedBatch(
                entry_ids=_recorded_batch.entry_ids,
                iv=_recorded_batch.iv,
                encrypted_batch=_recorded_batch.encrypted_batch,
            )
        ]

    # Supplies the recorded nonce, so the output is deterministic.
    def random_bytes(_size: int) -> fx.Effect[bytes]:
        return fx.succeed(_recorded_batch.iv)

    recorded_nonce = fx.layer.mock(secure_random.SecureRandom, random_bytes=random_bytes)
    layer = Enc.layer.pipe(
        fx.layer.provide(fx.layer.merge(aead.layer_web_crypto, digest.layer_web_crypto))
    ).pipe(fx.layer.provide_merge(recorded_nonce))
    yield from fx.gen(body).pipe(fx.provide(layer))
