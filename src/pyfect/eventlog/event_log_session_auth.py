"""How a client proves it holds an identity (Effect's
``eventlog/EventLogSessionAuth``): it signs, with the Ed25519 key derived
from the identity's root secret, a canonical payload binding the server's
remote id and one-time challenge to its public keys.

The payload is five length-prefixed fields (a 4-byte big-endian length,
then the bytes): the context ``"eventlog-auth-v1"``, the remote id (its
hex text when given as bytes), the challenge, the public key and the
32-byte signing public key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.crypto import key_format, secure_random
from pyfect.crypto import signature as sig
from pyfect.crypto import web_crypto as web
from pyfect.crypto.crypto_error import CryptoError
from pyfect.effect import fail, gen, succeed, suspend, sync, void
from pyfect.errors import TaggedError
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.layer import Layer
from pyfect.layer import provide as provide_layer

AUTH_PAYLOAD_CONTEXT = "eventlog-auth-v1"
ED25519_PUBLIC_KEY_LENGTH = 32
ED25519_SIGNATURE_LENGTH = 64
SESSION_AUTH_CHALLENGE_LENGTH = 32
SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_MILLIS = 30_000
_LENGTH_PREFIX_BYTES = 4

type SessionAuthErrorReason = Literal[
    "InvalidPayload",
    "InvalidContext",
    "InvalidAlgorithm",
    "InvalidSigningPublicKeyLength",
    "InvalidSignatureLength",
    "InvalidSigningPrivateKey",
    "CryptoUnavailable",
    "CryptoFailure",
]


@dataclass(eq=False)
class EventLogSessionAuthError(TaggedError):
    """Session auth failed for ``reason``."""

    reason: SessionAuthErrorReason
    message: str
    cause: object = None


@dataclass(frozen=True, slots=True)
class SessionAuthPayload:
    """What a session auth signature covers."""

    remote_id: str | bytes
    challenge: bytes
    public_key: str
    signing_public_key: bytes


def _check_signing_public_key(key: bytes) -> EventLogSessionAuthError | None:
    if len(key) == ED25519_PUBLIC_KEY_LENGTH:
        return None
    return EventLogSessionAuthError(
        "InvalidSigningPublicKeyLength",
        f"Expected signingPublicKey length to be {ED25519_PUBLIC_KEY_LENGTH} bytes, "
        f"received {len(key)}",
    )


def _encode(payload: SessionAuthPayload) -> bytes:
    remote_id = payload.remote_id if isinstance(payload.remote_id, str) else payload.remote_id.hex()
    fields = [
        text_encode(AUTH_PAYLOAD_CONTEXT),
        text_encode(remote_id),
        payload.challenge,
        text_encode(payload.public_key),
        payload.signing_public_key,
    ]
    return b"".join(len(field).to_bytes(_LENGTH_PREFIX_BYTES) + field for field in fields)


def encode_session_auth_payload(
    payload: SessionAuthPayload,
) -> Effect[bytes, EventLogSessionAuthError]:
    """The canonical bytes of ``payload``."""
    error = _check_signing_public_key(payload.signing_public_key)
    return fail(error) if error is not None else sync(lambda: _encode(payload))


def _invalid(message: str) -> EventLogSessionAuthError:
    return EventLogSessionAuthError("InvalidPayload", message)


def _decode(payload: bytes) -> SessionAuthPayload:
    offset = 0

    def field() -> bytes:
        nonlocal offset
        if offset + _LENGTH_PREFIX_BYTES > len(payload):
            raise _invalid("Session auth payload is truncated before field length")
        length = int.from_bytes(payload[offset : offset + _LENGTH_PREFIX_BYTES])
        offset += _LENGTH_PREFIX_BYTES
        if offset + length > len(payload):
            raise _invalid("Session auth payload is truncated inside a field")
        value = payload[offset : offset + length]
        offset += length
        return value

    def text() -> str:
        try:
            return field().decode()
        except UnicodeDecodeError as cause:
            error = _invalid("Session auth payload contains invalid UTF-8 bytes")
            error.cause = cause
            raise error from cause

    context = text()
    if context != AUTH_PAYLOAD_CONTEXT:
        raise EventLogSessionAuthError(
            "InvalidContext", f"Invalid session auth payload context: {context}"
        )
    remote_id = text()
    challenge = field()
    public_key = text()
    signing_public_key = field()
    error = _check_signing_public_key(signing_public_key)
    if error is not None:
        raise error
    if offset != len(payload):
        raise _invalid("Session auth payload contains trailing bytes")
    return SessionAuthPayload(remote_id, challenge, public_key, signing_public_key)


def _attempt[A](f: Callable[[], A]) -> Effect[A, EventLogSessionAuthError]:
    def run() -> Effect[A, EventLogSessionAuthError]:
        try:
            return succeed(f())
        except EventLogSessionAuthError as error:
            return fail(error)

    return suspend(run)


def decode_session_auth_payload(
    payload: bytes,
) -> Effect[SessionAuthPayload, EventLogSessionAuthError]:
    """The payload of canonical bytes; an ``InvalidPayload`` /
    ``InvalidContext`` error when they are not one."""
    return _attempt(lambda: _decode(payload))


def _require_web_crypto() -> Effect[None, EventLogSessionAuthError]:
    # The Web Crypto layers read the ``WebCrypto`` reference, so a runtime
    # without ``subtle`` fails here rather than with a defect inside a layer.
    def check(crypto: web.Crypto) -> Effect[None, EventLogSessionAuthError]:
        if crypto.subtle is None:
            return fail(
                EventLogSessionAuthError("CryptoUnavailable", "crypto.subtle is not available")
            )
        return void

    return web.WebCrypto().flat_map(check)


_layer_signature: Layer[sig.Signature] = sig.layer_web_crypto.pipe(
    provide_layer(secure_random.layer_web_crypto)
)


def _crypto_failure(message: str) -> Callable[[CryptoError], EventLogSessionAuthError]:
    return lambda cause: EventLogSessionAuthError("CryptoFailure", message, cause)


def sign_session_auth_payload_bytes(
    payload: bytes, signing_private_key: bytes
) -> Effect[bytes, EventLogSessionAuthError]:
    """Sign canonical bytes with a PKCS#8 Ed25519 private key, on
    ``sig.layer_web_crypto`` with the ``WebCrypto`` reference."""

    @gen
    def run():
        yield from decode_session_auth_payload(payload)
        yield from _require_web_crypto()
        private_key = yield from key_format.decode_private(
            key_format.pkcs8, sig.ed25519, signing_private_key
        ).map_error(
            lambda cause: EventLogSessionAuthError(
                "InvalidSigningPrivateKey",
                "Failed to import Ed25519 signing private key (expected PKCS#8 bytes)",
                cause,
            )
        )
        return (
            yield from sig.Signature()
            .flat_map(lambda service: service.sign(private_key, payload))
            .pipe(provide_layer(_layer_signature))
            .map_error(_crypto_failure("Failed to sign canonical session auth payload"))
        )

    return run


def verify_session_auth_payload_bytes(
    payload: bytes, signing_public_key: bytes, signature: bytes
) -> Effect[bool, EventLogSessionAuthError]:
    """Whether ``signature`` signs the canonical bytes for the key; the
    lengths are checked before verifying on ``sig.layer_web_crypto``
    with the ``WebCrypto`` reference."""

    @gen
    def run():
        yield from decode_session_auth_payload(payload)
        error = _check_signing_public_key(signing_public_key)
        if error is not None:
            return (yield from fail(error))
        if len(signature) != ED25519_SIGNATURE_LENGTH:
            return (
                yield from fail(
                    EventLogSessionAuthError(
                        "InvalidSignatureLength",
                        f"Expected signature length to be {ED25519_SIGNATURE_LENGTH} bytes, "
                        f"received {len(signature)}",
                    )
                )
            )
        yield from _require_web_crypto()
        public_key = yield from sig.public_key(sig.ed25519, signing_public_key).map_error(
            lambda cause: EventLogSessionAuthError(
                "InvalidSigningPublicKeyLength",
                "Failed to import Ed25519 signing public key",
                cause,
            )
        )
        return (
            yield from sig.Signature()
            .flat_map(lambda service: service.verify(public_key, signature, payload))
            .pipe(provide_layer(_layer_signature))
            .map_error(_crypto_failure("Failed to verify canonical session auth payload signature"))
        )

    return run


def sign_session_auth_payload(
    payload: SessionAuthPayload, signing_private_key: bytes
) -> Effect[bytes, EventLogSessionAuthError]:
    return encode_session_auth_payload(payload).flat_map(
        lambda data: sign_session_auth_payload_bytes(data, signing_private_key)
    )


def verify_session_auth_payload(
    payload: SessionAuthPayload, signature: bytes
) -> Effect[bool, EventLogSessionAuthError]:
    return encode_session_auth_payload(payload).flat_map(
        lambda data: verify_session_auth_payload_bytes(data, payload.signing_public_key, signature)
    )


make_session_auth_challenge: Effect[bytes, EventLogSessionAuthError] = (
    secure_random.SecureRandom()
    .flat_map(lambda random: random.random_bytes(SESSION_AUTH_CHALLENGE_LENGTH))
    .pipe(provide_layer(secure_random.layer_web_crypto))
)
"""A fresh random challenge from ``SecureRandom`` on the ``WebCrypto``
reference."""


_identity_material = make_get_identity_root_secret_material()


def derive_signing_public_key(identity: IdentityService) -> Effect[bytes]:
    """The Ed25519 signing public key ``identity`` presents in session auth
    (Effect's ``deriveSigningPublicKey``), derived on the ``WebCrypto``
    reference. Record it when provisioning an identity, so
    ``authorize_identity`` can reject any other key presented for its public
    key."""
    return _identity_material(identity).map(lambda material: material.signing_public_key)


def verify_session_authenticate_request(
    payload: SessionAuthPayload, signature: bytes, algorithm: str
) -> Effect[bool, EventLogSessionAuthError]:
    """Verify an ``Authenticate`` request; only ``"Ed25519"`` is known."""
    if algorithm != "Ed25519":
        return fail(
            EventLogSessionAuthError(
                "InvalidAlgorithm", f"Unsupported session auth algorithm: {algorithm}"
            )
        )
    return verify_session_auth_payload(payload, signature)


__all__ = [
    "AUTH_PAYLOAD_CONTEXT",
    "ED25519_PUBLIC_KEY_LENGTH",
    "ED25519_SIGNATURE_LENGTH",
    "SESSION_AUTH_CHALLENGE_LENGTH",
    "SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_MILLIS",
    "EventLogSessionAuthError",
    "SessionAuthErrorReason",
    "SessionAuthPayload",
    "decode_session_auth_payload",
    "derive_signing_public_key",
    "encode_session_auth_payload",
    "make_session_auth_challenge",
    "sign_session_auth_payload",
    "sign_session_auth_payload_bytes",
    "verify_session_auth_payload",
    "verify_session_auth_payload_bytes",
    "verify_session_authenticate_request",
]
