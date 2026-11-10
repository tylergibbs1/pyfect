"""Ports of Effect's ``crypto/WebCrypto.test.ts``.

``globalThis.crypto`` is ``pyfect.crypto._subtle.host`` (``os.urandom``,
``hashlib`` and the ``cryptography`` package); a ``Crypto`` whose
``subtle`` is ``None`` is an insecure browser context's.
"""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.crypto import digest, secure_random, signature, web_crypto
from pyfect.crypto._lib import aes_key_wrap
from pyfect.crypto._subtle import host
from pyfect.crypto.digest import Digest
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.signature import Signature
from pyfect.exit import Exit, is_failure

from ._crypto import assert_reason, crypto_with, encode, fake_subtle, raises


def assert_subtle_unavailable(exit: Exit[Any, Any]) -> None:
    assert is_failure(exit), exit
    assert exit.cause.has_dies, exit
    assert "crypto.subtle is unavailable" in str(exit.cause.squash())


@testing.effect
def test_identifies_the_algorithm_and_declining_layer_in_native_unsupported_errors():
    """identifies the algorithm and declining layer in native Unsupported errors"""

    @fx.gen
    def program():
        key = yield from signature.private_key(signature.ed25519, bytes([7] * 32))
        service = yield from Signature()
        error = yield from service.sign(key, encode("message")).flip()
        assert_reason(error, "Unsupported", "sign")
        assert "ed25519" in error.reason.message
        assert "Signature.layerWebCrypto" in error.reason.message

    return (
        program.pipe(fx.provide(signature.layer_web_crypto))
        .pipe(fx.provide_service(SecureRandom, secure_random.make(lambda size: bytes([7] * size))))
        .pipe(fx.provide(fake_subtle(import_key=raises("NotSupportedError", "not supported"))))
    )


@testing.effect
def test_defaults_to_global_this_crypto():
    """defaults to globalThis.crypto"""
    assert (yield from web_crypto.WebCrypto()) is host


@testing.effect
def test_swaps_the_crypto_object_the_digest_service_runs_on():
    """swaps the Crypto object the Digest service runs on"""

    class _Subtle:
        def digest(self, *_args: object) -> bytes:
            return bytes([1, 2, 3])

    @fx.gen
    def program():
        service = yield from Digest()
        assert (yield from service.digest(digest.sha256, encode("abc"))) == bytes([1, 2, 3])

    return program.pipe(fx.provide(digest.layer_web_crypto)).pipe(
        fx.provide(web_crypto.layer(crypto_with(_Subtle())))
    )


@testing.effect
def test_dies_at_the_first_call_that_needs_crypto_subtle_not_when_a_layer_is_built():
    """dies at the first call that needs crypto.subtle, not when a layer is built"""

    @fx.gen
    def program():
        service = yield from Digest()
        # MD5 runs in the process, so it keeps working without subtle.
        md5_hex = yield from service.digest_hex(digest.md5, encode("abc"))
        assert md5_hex == "900150983cd24fb0d6963f7d28e17f72"
        assert_subtle_unavailable((yield from service.digest(digest.sha256, encode("abc")).exit()))
        assert_subtle_unavailable(
            (yield from service.digest_hex(digest.sha256, encode("abc")).exit())
        )

    # A Crypto without subtle, as in an insecure browser context.
    return program.pipe(fx.provide(digest.layer_web_crypto)).pipe(
        fx.provide(web_crypto.layer(crypto_with(None)))
    )


def test_the_host_unwraps_only_a_json_object_as_a_jwk():
    """Web Crypto's ``unwrapKey`` with ``"jwk"`` reads the plaintext as a JWK
    object; any other JSON is a ``DataError``, as in Node."""
    subtle = host.subtle
    assert subtle is not None
    kek_bytes = bytes(16)
    kek = subtle.import_key("raw", kek_bytes, "AES-KW", False, ["unwrapKey"])
    for text in [b"[1, 2, 3, 4, 5, 6]", b'"a JSON string!"']:
        wrapped = aes_key_wrap(kek_bytes, text.ljust(24))
        with pytest.raises(web_crypto.DOMException) as raised:
            subtle.unwrap_key("jwk", wrapped, kek, "AES-KW", "AES-GCM", True, ["encrypt"])
        assert raised.value.name == "DataError"
