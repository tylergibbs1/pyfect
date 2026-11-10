"""Message digests as a service (Effect's ``effect/crypto/Digest``)::

    digest = yield from Digest()
    hex_text = yield from digest.digest_hex(sha256, data)

The algorithms are values: ``md5``, ``sha1``, ``sha256``, ``sha384``,
``sha512``. ``layer_web_crypto`` runs the SHA family on the ``WebCrypto``
reference's ``subtle`` and MD5 in the process (``hashlib``), so MD5 works
without ``subtle``. MD5 and SHA-1 are for existing protocols only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.crypto import _web
from pyfect.crypto._key import Binary
from pyfect.crypto.web_crypto import Crypto, WebCrypto
from pyfect.effect import die, suspend, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect

type Name = Literal["MD5", "SHA-1", "SHA-256", "SHA-384", "SHA-512"]


@dataclass(frozen=True, kw_only=True)
class Algorithm:
    """A digest: its Web Crypto ``name``, ``output_length`` in bytes, and an
    in-process ``implementation`` for one Web Crypto lacks."""

    name: Name
    output_length: int
    implementation: Callable[[bytes], bytes] | None = field(default=None, compare=False)


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data, usedforsecurity=False).digest()


md5 = Algorithm(name="MD5", output_length=16, implementation=_md5)
sha1 = Algorithm(name="SHA-1", output_length=20)
sha256 = Algorithm(name="SHA-256", output_length=32)
sha384 = Algorithm(name="SHA-384", output_length=48)
sha512 = Algorithm(name="SHA-512", output_length=64)


def name_suffix(hash: Algorithm) -> str:
    """``"Sha256"`` for SHA-256, as the algorithm names use it."""
    return hash.name[0] + hash.name[1:].lower().replace("-", "")


@dataclass(frozen=True, slots=True, kw_only=True)
class DigestService:
    digest: Callable[[Algorithm, Binary], Effect[bytes]]
    digest_hex: Callable[[Algorithm, Binary], Effect[str]]


class Digest(Tag[DigestService], key="effect/crypto/Digest"):
    """Message digests."""


def web_crypto_digest(crypto: Crypto | None, algorithm: Algorithm, data: Binary) -> Effect[bytes]:
    """``algorithm``'s digest of ``data``: its ``implementation``, or
    ``crypto.subtle`` (dying when there is none)."""
    implementation = algorithm.implementation
    if implementation is not None:
        return sync(lambda: implementation(bytes(data)))

    def go() -> Effect[bytes]:
        subtle = None if crypto is None else crypto.subtle
        if subtle is None:
            return die(_web.subtle_unavailable())
        return sync(lambda: bytes(subtle.digest(algorithm.name, bytes(data))))

    return suspend(go)


def _service(crypto: Crypto) -> DigestService:
    return DigestService(
        digest=lambda algorithm, data: web_crypto_digest(crypto, algorithm, data),
        digest_hex=lambda algorithm, data: web_crypto_digest(crypto, algorithm, data).map(
            bytes.hex
        ),
    )


layer_web_crypto: Layer[Digest] = layer_effect(Digest, WebCrypto().map(_service))
"""Digests on the ``WebCrypto`` reference, MD5 in the process."""

__all__ = [
    "Algorithm",
    "Digest",
    "DigestService",
    "Name",
    "layer_web_crypto",
    "md5",
    "name_suffix",
    "sha1",
    "sha256",
    "sha384",
    "sha512",
    "web_crypto_digest",
]
