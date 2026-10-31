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

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.effect import fail, succeed, suspend, sync
from pyfect.errors import TaggedError

AUTH_PAYLOAD_CONTEXT = "eventlog-auth-v1"
ED25519_PUBLIC_KEY_LENGTH = 32
ED25519_SIGNATURE_LENGTH = 64
SESSION_AUTH_CHALLENGE_LENGTH = 32
SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_SECONDS = 30.0
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

    def __str__(self) -> str:
        return self.message


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


def sign_session_auth_payload_bytes(
    payload: bytes, signing_private_key: bytes
) -> Effect[bytes, EventLogSessionAuthError]:
    """Sign canonical bytes with a PKCS#8 Ed25519 private key."""

    def sign() -> bytes:
        from pyfect.eventlog import _crypto

        _decode(payload)
        try:
            return _crypto.ed25519_sign(signing_private_key, payload)
        except ValueError as cause:
            raise EventLogSessionAuthError(
                "InvalidSigningPrivateKey",
                "Failed to import Ed25519 signing private key (expected PKCS#8 bytes)",
                cause,
            ) from cause

    return _attempt(sign)


def verify_session_auth_payload_bytes(
    payload: bytes, signing_public_key: bytes, signature: bytes
) -> Effect[bool, EventLogSessionAuthError]:
    """Whether ``signature`` signs the canonical bytes for the key."""

    def verify() -> bool:
        from pyfect.eventlog import _crypto

        _decode(payload)
        error = _check_signing_public_key(signing_public_key)
        if error is not None:
            raise error
        if len(signature) != ED25519_SIGNATURE_LENGTH:
            raise EventLogSessionAuthError(
                "InvalidSignatureLength",
                f"Expected signature length to be {ED25519_SIGNATURE_LENGTH} bytes, "
                f"received {len(signature)}",
            )
        return _crypto.ed25519_verify(signing_public_key, signature, payload)

    return _attempt(verify)


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


make_session_auth_challenge: Effect[bytes, EventLogSessionAuthError] = sync(
    lambda: os.urandom(SESSION_AUTH_CHALLENGE_LENGTH)
)
"""A fresh random challenge."""


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
    "SESSION_AUTH_CHALLENGE_TIME_TO_LIVE_SECONDS",
    "EventLogSessionAuthError",
    "SessionAuthErrorReason",
    "SessionAuthPayload",
    "decode_session_auth_payload",
    "encode_session_auth_payload",
    "make_session_auth_challenge",
    "sign_session_auth_payload",
    "sign_session_auth_payload_bytes",
    "verify_session_auth_payload",
    "verify_session_auth_payload_bytes",
    "verify_session_authenticate_request",
]
