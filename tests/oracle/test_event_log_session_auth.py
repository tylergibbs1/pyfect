"""Ports of Effect's ``effect/test/eventlog/EventLogSessionAuth.test.ts``
and ``EventLogIdentityDerivation.test.ts``. Each test's docstring is the
Effect test title."""

import pyfect as fx
from pyfect.eventlog import _crypto
from pyfect.eventlog import event_log_session_auth as A
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog._identity_derivation import (
    ENCRYPTION_DERIVATION_LABEL_V1,
    SIGNING_DERIVATION_LABEL_V1,
    make_get_identity_root_secret_material,
)
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal


def _key_pair() -> tuple[bytes, bytes]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    private = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return public, private


def _payload(
    signing_public_key: bytes, challenge: bytes = bytes(range(1, 9))
) -> A.SessionAuthPayload:
    return A.SessionAuthPayload(
        remote_id="remote-123",
        challenge=challenge,
        public_key="client-public-key",
        signing_public_key=signing_public_key,
    )


def test_encodes_and_decodes_deterministically() -> None:
    """encodes and decodes canonical auth payload deterministically"""
    payload = _payload(bytes(range(A.ED25519_PUBLIC_KEY_LENGTH)))
    first = fx.run_sync(A.encode_session_auth_payload(payload).or_die())
    second = fx.run_sync(A.encode_session_auth_payload(payload).or_die())
    assert first == second
    decoded = fx.run_sync(A.decode_session_auth_payload(first).or_die())
    assert decoded.remote_id == payload.remote_id
    assert decoded.public_key == payload.public_key
    assert decoded.challenge == payload.challenge
    assert decoded.signing_public_key == payload.signing_public_key


def test_signs_and_verifies() -> None:
    """signs and verifies canonical auth payload with Ed25519"""
    public, private = _key_pair()
    payload = _payload(public)
    signature = fx.run_sync(A.sign_session_auth_payload(payload, private).or_die())
    assert len(signature) == A.ED25519_SIGNATURE_LENGTH
    assert fx.run_sync(A.verify_session_auth_payload(payload, signature).or_die()) is True


def test_mismatched_payload() -> None:
    """returns false for mismatched payload/signature"""
    public, private = _key_pair()
    payload = _payload(public)
    signature = fx.run_sync(A.sign_session_auth_payload(payload, private).or_die())
    challenge = bytes([payload.challenge[0] ^ 0xFF]) + payload.challenge[1:]
    verified = fx.run_sync(
        A.verify_session_auth_payload(_payload(public, challenge), signature).or_die()
    )
    assert verified is False


def test_rejects_malformed_signature_length() -> None:
    """rejects malformed signature length"""
    public, _ = _key_pair()
    error = fx.run_sync(
        A.verify_session_auth_payload(_payload(public), bytes(A.ED25519_SIGNATURE_LENGTH - 1))
        .flip()
        .or_die()
    )
    assert error.reason == "InvalidSignatureLength"


def test_rejects_malformed_signing_public_key_length() -> None:
    """rejects malformed signing public key length"""
    payload = A.SessionAuthPayload(
        remote_id="remote-123",
        challenge=bytes(32),
        public_key="client-public-key",
        signing_public_key=bytes(A.ED25519_PUBLIC_KEY_LENGTH - 1),
    )
    error = fx.run_sync(A.encode_session_auth_payload(payload).flip().or_die())
    assert error.reason == "InvalidSigningPublicKeyLength"


def test_rejects_invalid_canonical_payload_bytes() -> None:
    """rejects invalid canonical payload bytes"""
    public, _ = _key_pair()
    encoded = fx.run_sync(A.encode_session_auth_payload(_payload(public)).or_die())
    error = fx.run_sync(
        A.verify_session_auth_payload_bytes(encoded[:-1], public, bytes(A.ED25519_SIGNATURE_LENGTH))
        .flip()
        .or_die()
    )
    assert error.reason == "InvalidPayload"


def _identity(public_key: str, root_secret: bytes) -> IdentityService:
    return IdentityService(public_key, redacted(root_secret))


_ROOT_SECRET = bytes((i * 17) % 256 for i in range(32))


def test_same_root_secret_same_material() -> None:
    """derives the same material for identities with the same root secret"""
    derive = make_get_identity_root_secret_material()
    first = fx.run_sync(derive(_identity("user-a", _ROOT_SECRET)))
    second = fx.run_sync(derive(_identity("user-b", _ROOT_SECRET)))
    assert "/v1/" in ENCRYPTION_DERIVATION_LABEL_V1
    assert "/v1/" in SIGNING_DERIVATION_LABEL_V1
    assert first.encryption_key_material == second.encryption_key_material
    assert first.signing_public_key == second.signing_public_key
    assert reveal(first.signing_private_key) == reveal(second.signing_private_key)


def test_domain_separated_labels() -> None:
    """uses versioned, domain-separated labels for encryption and signing"""
    derive = make_get_identity_root_secret_material()
    derived = fx.run_sync(derive(_identity("user-a", _ROOT_SECRET)))
    seed = reveal(derived.signing_private_key)[-32:]
    assert derived.encryption_key_material != seed
    assert ENCRYPTION_DERIVATION_LABEL_V1 != SIGNING_DERIVATION_LABEL_V1
    assert _crypto.ed25519_public_key(seed) == derived.signing_public_key


def test_memoizes_per_identity_instance() -> None:
    """memoizes derived material for the same identity instance"""
    derive = make_get_identity_root_secret_material()
    identity = _identity("user-a", _ROOT_SECRET)
    assert fx.run_sync(derive(identity)) is fx.run_sync(derive(identity))
