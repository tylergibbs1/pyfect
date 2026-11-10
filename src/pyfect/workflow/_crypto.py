"""Execution ids and idempotency keys: the first 16 bytes of a SHA-256
digest, in hex, on the ``WebCrypto`` reference (Effect's ``internal/crypto.ts``).
They are persisted, so they must stay byte-for-byte stable."""

from __future__ import annotations

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.crypto.digest import sha256, web_crypto_digest
from pyfect.crypto.web_crypto import WebCrypto
from pyfect.effect import yield_now


def make_hash_digest(original: str) -> Effect[str]:
    """The digest of ``original``'s UTF-8 bytes. Like Effect's, which
    awaits ``subtle.digest``, it lets other fibers run first."""
    return (
        yield_now()
        .and_then(
            WebCrypto().flat_map(
                lambda crypto: web_crypto_digest(crypto, sha256, text_encode(original))
            )
        )
        .map(lambda digest: digest.hex()[:32])
    )


__all__ = ["make_hash_digest"]
