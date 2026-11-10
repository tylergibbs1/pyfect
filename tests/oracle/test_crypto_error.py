"""Ports of Effect's ``crypto/CryptoError.test.ts``."""

from __future__ import annotations

from pyfect.crypto.crypto_error import (
    AnyReason,
    CryptoError,
    DecryptionFailed,
    InvalidArgument,
    InvalidKey,
    NotExtractable,
    Unsupported,
    is_crypto_error,
    is_crypto_error_reason,
)


def test_prefixes_the_reason_message_with_the_module_and_method_and_copies_the_cause():
    """prefixes the reason message with the module and method and copies the reason's cause"""
    cause = ValueError("DataError from fixture")
    error = CryptoError(
        module="Mac",
        method="key",
        reason=InvalidKey(description="HMAC keys must not be empty", cause=cause),
    )
    assert error.module == "Mac"
    assert error.method == "key"
    assert error.message == "Mac.key: HMAC keys must not be empty"
    assert error.cause is cause
    assert error.__cause__ is cause


def test_carries_no_detail_for_a_failed_decryption():
    """carries no detail for a failed decryption"""
    reason = DecryptionFailed()
    error = CryptoError(module="Aead", method="decrypt", reason=reason)
    assert error.message == f"Aead.decrypt: {reason.message}"
    assert error.cause is None
    assert not hasattr(reason, "cause")


def test_recognizes_the_error_and_each_of_its_reasons():
    """recognizes the error and each of its reasons"""
    reasons: list[AnyReason] = [
        InvalidArgument(description="nonce must be 12 bytes"),
        InvalidKey(description="key must be 32 bytes"),
        DecryptionFailed(),
        Unsupported(description="Kdf.layerWebCrypto does not provide argon2id"),
        NotExtractable(description="the CryptoKey is not extractable"),
    ]
    for reason in reasons:
        error = CryptoError(module="Aead", method="encrypt", reason=reason)
        assert is_crypto_error(error)
        assert not is_crypto_error_reason(error)
        assert is_crypto_error_reason(reason)
        assert not is_crypto_error(reason)
    assert not is_crypto_error(ValueError("Aead.encrypt: failed"))
    assert not is_crypto_error_reason(ValueError("failed"))
