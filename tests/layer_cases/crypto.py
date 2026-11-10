"""Layer cases of ``pyfect.crypto`` and ``pyfect.jose``: each run goes
through the service once (a digest, a tag, a sealed message, a signature,
a key set lookup)."""

from __future__ import annotations

import json
from typing import Any

from oracle._jose import ES256_PUBLIC_JWK

import pyfect as fx
from layer_cases._case import Case
from pyfect import layer as L
from pyfect.crypto import (
    aead,
    cipher,
    digest,
    kdf,
    key_agreement,
    key_wrap,
    mac,
    native,
    secure_random,
    signature,
    web_crypto,
)
from pyfect.crypto._subtle import host
from pyfect.http import response as http_response
from pyfect.http.client import layer_test
from pyfect.jose import jwks

type AnyEffect = fx.Effect[Any, Any, Any]

_KEY_SET: jwks.KeySet = {"keys": [{**ES256_PUBLIC_JWK, "kid": "ec"}]}


def _draw() -> AnyEffect:
    return secure_random.SecureRandom().flat_map(lambda s: s.random_bytes(4)).map(lambda _: None)


def _digest() -> AnyEffect:
    return digest.Digest().flat_map(lambda d: d.digest(digest.sha256, b"abc")).map(lambda _: None)


@fx.gen
def _mac():
    service = yield from mac.Mac()
    key = yield from service.generate_key(mac.hmac_sha256)
    tag = yield from service.sign(key, b"data")
    assert (yield from service.verify(key, tag, b"data"))


@fx.gen
def _aead():
    service = yield from aead.Aead()
    for algorithm in (aead.aes256_gcm, aead.chacha20_poly1305):
        key = yield from service.generate_key(algorithm)
        nonce = bytes(algorithm.nonce_length)
        sealed = yield from service.encrypt(key, b"data", nonce=nonce)
        assert (yield from service.decrypt(key, sealed, nonce=nonce)) == b"data"


@fx.gen
def _cipher():
    service = yield from cipher.Cipher()
    key = yield from service.generate_key(cipher.aes256_cbc)
    sealed = yield from service.encrypt(key, b"data", iv=bytes(16))
    assert (yield from service.decrypt(key, sealed, iv=bytes(16))) == b"data"


def _kdf() -> AnyEffect:
    return (
        kdf.Kdf()
        .flat_map(lambda k: k.derive(kdf.hkdf_sha256, b"secret", salt=b"salt", length=32))
        .map(lambda _: None)
    )


@fx.gen
def _signature():
    service = yield from signature.Signature()
    pair = yield from service.generate_key_pair(signature.ed25519)
    signed = yield from service.sign(pair.private_key, b"data")
    assert (yield from service.verify(pair.public_key, signed, b"data"))


@fx.gen
def _key_agreement():
    service = yield from key_agreement.KeyAgreement()
    first = yield from service.generate_key_pair(key_agreement.x25519)
    second = yield from service.generate_key_pair(key_agreement.x25519)
    shared = yield from service.derive_shared_secret(first.private_key, second.public_key)
    assert shared == (yield from service.derive_shared_secret(second.private_key, first.public_key))


@fx.gen
def _key_wrap():
    service = yield from key_wrap.KeyWrap()
    kek = yield from service.generate_key(key_wrap.aes128_kw)
    target = yield from aead.key(aead.aes128_gcm, bytes(16))
    wrapped = yield from service.wrap(kek, target)
    yield from service.unwrap(kek, aead.aes128_gcm, wrapped)


@fx.gen
def _every_family():
    yield from _draw()
    yield from _digest()
    yield from _mac
    yield from _aead
    yield from _cipher
    yield from _kdf()
    yield from _signature
    yield from _key_agreement
    yield from _key_wrap


@fx.gen
def _resolve():
    resolver = yield from jwks.Jwks()
    yield from resolver.resolve(jwks.Selection("ES256", kid="ec"))


def _key_set_server() -> L.Layer[Any]:
    return layer_test(lambda request: fx.succeed(http_response.make(request, json.dumps(_KEY_SET))))


def _random() -> L.Layer[Any]:
    return secure_random.layer_web_crypto


CASES: dict[str, Case] = {
    "pyfect.crypto.secure_random.layer_web_crypto": Case(
        layer=lambda: secure_random.layer_web_crypto, use=_draw
    ),
    "pyfect.crypto.web_crypto.layer": Case(
        layer=lambda: web_crypto.layer(host),
        needs=lambda: digest.layer_web_crypto,
        use=_digest,
    ),
    "pyfect.crypto.digest.layer_web_crypto": Case(
        layer=lambda: digest.layer_web_crypto, use=_digest
    ),
    "pyfect.crypto.mac.layer_web_crypto": Case(
        layer=lambda: mac.layer_web_crypto, needs=_random, use=lambda: _mac
    ),
    "pyfect.crypto.mac.layer_web_crypto_with": Case(
        layer=mac.layer_web_crypto_with, needs=_random, use=lambda: _mac
    ),
    "pyfect.crypto.aead.layer_web_crypto": Case(
        layer=lambda: aead.layer_web_crypto, needs=_random, use=lambda: _aead
    ),
    "pyfect.crypto.aead.layer_web_crypto_with": Case(
        layer=aead.layer_web_crypto_with, needs=_random, use=lambda: _aead
    ),
    "pyfect.crypto.cipher.layer_web_crypto": Case(
        layer=lambda: cipher.layer_web_crypto, needs=_random, use=lambda: _cipher
    ),
    "pyfect.crypto.kdf.layer_web_crypto": Case(layer=lambda: kdf.layer_web_crypto, use=_kdf),
    "pyfect.crypto.signature.layer_web_crypto": Case(
        layer=lambda: signature.layer_web_crypto, needs=_random, use=lambda: _signature
    ),
    "pyfect.crypto.key_agreement.layer_web_crypto": Case(
        layer=lambda: key_agreement.layer_web_crypto, needs=_random, use=lambda: _key_agreement
    ),
    "pyfect.crypto.key_wrap.layer_web_crypto": Case(
        layer=lambda: key_wrap.layer_web_crypto, needs=_random, use=lambda: _key_wrap
    ),
    "pyfect.crypto.native.layer": Case(layer=lambda: native.layer, use=lambda: _every_family),
    "pyfect.crypto.native.layer_aead": Case(layer=lambda: native.layer_aead, use=lambda: _aead),
    "pyfect.crypto.native.layer_cipher": Case(
        layer=lambda: native.layer_cipher, use=lambda: _cipher
    ),
    "pyfect.crypto.native.layer_digest": Case(layer=lambda: native.layer_digest, use=_digest),
    "pyfect.crypto.native.layer_kdf": Case(layer=lambda: native.layer_kdf, use=_kdf),
    "pyfect.crypto.native.layer_key_agreement": Case(
        layer=lambda: native.layer_key_agreement, use=lambda: _key_agreement
    ),
    "pyfect.crypto.native.layer_key_wrap": Case(
        layer=lambda: native.layer_key_wrap, use=lambda: _key_wrap
    ),
    "pyfect.crypto.native.layer_mac": Case(layer=lambda: native.layer_mac, use=lambda: _mac),
    "pyfect.crypto.native.layer_signature": Case(
        layer=lambda: native.layer_signature, use=lambda: _signature
    ),
    "pyfect.jose.jwks.layer_local": Case(
        layer=lambda: jwks.layer_local(_KEY_SET), use=lambda: _resolve
    ),
    "pyfect.jose.jwks.layer_remote": Case(
        layer=lambda: jwks.layer_remote("https://issuer.example/keys"),
        needs=_key_set_server,
        use=lambda: _resolve,
    ),
}

SKIPPED: dict[str, str] = {}
