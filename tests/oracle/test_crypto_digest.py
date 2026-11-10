"""Ports of Effect's ``crypto/Digest.test.ts``."""

from __future__ import annotations

import hashlib
import os

import pyfect as fx
from pyfect import testing
from pyfect.crypto import digest
from pyfect.crypto.digest import Digest

from ._crypto import encode

VECTORS: list[tuple[digest.Algorithm, str, str]] = [
    # RFC 1321, appendix A.5
    (digest.md5, "", "d41d8cd98f00b204e9800998ecf8427e"),
    (digest.md5, "a", "0cc175b9c0f1b6a831c399e269772661"),
    (digest.md5, "abc", "900150983cd24fb0d6963f7d28e17f72"),
    (digest.md5, "message digest", "f96b697d7cb7938d525a2f31aaf161d0"),
    (digest.md5, "abcdefghijklmnopqrstuvwxyz", "c3fcd3d76192e4007dfb496cca67e13b"),
    (
        digest.md5,
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "d174ab98d277d9f5a5611c2c9f419d9f",
    ),
    (
        digest.md5,
        "12345678901234567890123456789012345678901234567890123456789012345678901234567890",
        "57edf4a22be3c955ac49da2e2107b67a",
    ),
    # FIPS 180-2, appendix examples
    (digest.sha1, "abc", "a9993e364706816aba3e25717850c26c9cd0d89d"),
    (digest.sha256, "abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    (
        digest.sha384,
        "abc",
        "cb00753f45a35e8bb5a03d699ac65007272c32ab0eded1631a8b605a43ff5bed"
        "8086072ba1e7cc2358baeca134c825a7",
    ),
    (
        digest.sha512,
        "abc",
        "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
        "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
    ),
]


@testing.effect
def test_matches_the_published_vectors_through_the_service():
    """matches the published vectors through the service"""

    @fx.gen
    def program():
        service = yield from Digest()
        for algorithm, text, hex_text in VECTORS:
            data = encode(text)
            assert (yield from service.digest_hex(algorithm, data)) == hex_text
            assert (yield from service.digest(algorithm, data)).hex() == hex_text

    return program.pipe(fx.provide(digest.layer_web_crypto))


@testing.effect
def test_computes_md5_like_node_crypto_on_random_inputs():
    """computes MD5 like node:crypto on random inputs"""

    @fx.gen
    def program():
        service = yield from Digest()
        # Covers every padding case around the 64-byte block boundary.
        for length in range(201):
            data = os.urandom(length)
            expected = hashlib.md5(data, usedforsecurity=False).hexdigest()
            assert (yield from service.digest_hex(digest.md5, data)) == expected, length

    return program.pipe(fx.provide(digest.layer_web_crypto))
