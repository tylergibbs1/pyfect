"""Execution ids and idempotency keys: the first 16 bytes of a SHA-256
digest, in hex (Effect's ``internal/crypto.ts``)."""

from __future__ import annotations

import hashlib

from pyfect._core import Effect
from pyfect.effect import sync, yield_now


def make_hash_digest(original: str) -> Effect[str]:
    """The digest of ``original``'s UTF-8 bytes. Like Effect's, which
    awaits ``crypto.subtle.digest``, it lets other fibers run first."""

    def digest() -> str:
        return hashlib.sha256(original.encode()).digest()[:16].hex()

    return yield_now().and_then(sync(digest))


__all__ = ["make_hash_digest"]
