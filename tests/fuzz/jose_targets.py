"""JOSE tokens and keys, and the crypto key formats: malformed input fails
with ``JoseError`` / ``CryptoError`` (or ``SchemaError`` for claims), never a
defect."""

from __future__ import annotations

import functools
from typing import Any, get_args

import pyfect as fx
from pyfect import _json_text, effect
from pyfect import schema as S
from pyfect.crypto import aead, digest, key_agreement, key_format, mac, secure_random, signature
from pyfect.crypto.crypto_error import CryptoError
from pyfect.jose import jwe, jwk, jwks, jws, jwt
from pyfect.jose.jose_error import JoseError
from pyfect.jose.jwk import AsymmetricAlgorithm, DirKey, HmacKey, PublicKey
from pyfect.layer import merge, provide_merge
from pyfect.redacted import make as redacted
from pyfect.schema import SchemaError

from ._harness import raises_only, settle, target, text

_CRYPTO = merge(
    aead.layer_web_crypto,
    digest.layer_web_crypto,
    mac.layer_web_crypto,
    signature.layer_web_crypto,
).pipe(provide_merge(secure_random.layer_web_crypto))

# RFC 7515 A.1 and RFC 8037 A.2.
_HS256: Any = {
    "kty": "oct",
    "k": "AyM1SysPpbyDfgZld3umj1qzKObwVMkoqQ-EstJQLr_T-1qS0gZH75aKtMN3Yj0iPS4hcgUuTwjAzZr1Z9CAow",
}
_ED25519: Any = {"kty": "OKP", "crv": "Ed25519", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"}
_DIR: Any = {"kty": "oct", "k": "GawgguFyGrWKav7AX4VKUg_7kH5x1uQDYmsvmmu1A9s"}


def _run(eff: fx.Effect[Any, Any, Any]) -> Any:
    return fx.run_blocking(eff.pipe(fx.provide(_CRYPTO)).or_die())


@functools.cache
def _keys() -> tuple[HmacKey, PublicKey, DirKey]:
    return (
        _run(jwk.import_hmac(redacted(_HS256), "HS256")),
        _run(jwk.import_public(_ED25519, "EdDSA")),
        _run(jwk.import_dir(redacted(_DIR))),
    )


def _settle(eff: fx.Effect[Any, Any, Any]) -> None:
    settle(eff.pipe(fx.provide(_CRYPTO)), JoseError, SchemaError)


@target("jose_token")
def jose_token(data: bytes) -> None:
    """A compact token parsed, verified (HMAC and EdDSA, as a JWS and a JWT),
    read unverified and decrypted (``dir``)."""
    token = text(data)
    hmac, ed25519, direct = _keys()
    _settle(jws.parse(token))
    _settle(jws.verify(token, hmac))
    _settle(jws.verify(token, ed25519))
    _settle(jwt.verify(jwt.RegisteredClaimsSchema, token, hmac))
    _settle(jwt.decode_unverified(token))
    _settle(jwe.decrypt(token, direct))
    _settle(jwt.decrypt(jwt.RegisteredClaimsSchema, token, direct))


_ALGORITHMS: tuple[AsymmetricAlgorithm, ...] = get_args(AsymmetricAlgorithm.__value__)


@target("jose_jwk")
def jose_jwk(data: bytes) -> None:
    """A JSON document imported as a public, private, HMAC and ``dir`` JWK
    and as a key set; the first byte picks the algorithm."""
    if not data:
        return
    parsed: object = raises_only(lambda: _json_text.parse(data[1:]), ValueError)
    if not isinstance(parsed, dict):  # the imports take a JWK, a dict (TypedDict)
        return
    value: Any = parsed
    algorithm = _ALGORITHMS[data[0] % len(_ALGORITHMS)]
    _settle(jwk.import_public(value, algorithm))
    _settle(jwk.import_private(redacted(value), algorithm))
    _settle(jwk.import_hmac(redacted(value), "HS256"))
    _settle(jwk.import_dir(redacted(value)))
    key_set = S.decode_unknown_option(jwks.KeySetSchema)(value)
    if key_set is not None:
        resolve = jwks.make_local(key_set.value).flat_map(
            lambda found: found.resolve(jwks.Selection(algorithm=algorithm))
        )
        _settle(resolve)


_KEY_ALGORITHMS: tuple[Any, ...] = (
    signature.ecdsa_p256,
    signature.ed25519,
    key_agreement.x25519,
    key_agreement.ecdh_p384,
    signature.rsa_pss(hash=digest.sha256, modulus_length=2048),
)


@target("crypto_key_format")
def crypto_key_format(data: bytes) -> None:
    """The first byte picks the algorithm and the format: SPKI, PKCS#8,
    PKCS#1, SEC1 (DER and PEM) or a JWK."""
    if not data:
        return
    algorithm = _KEY_ALGORITHMS[data[0] % len(_KEY_ALGORITHMS)]
    body = data[1:]
    decode_public: Any = key_format.decode_public
    decode_private: Any = key_format.decode_private
    eff: fx.Effect[Any, CryptoError]
    match (data[0] // len(_KEY_ALGORITHMS)) % 6:
        case 0:
            eff = decode_public(key_format.spki, algorithm, body)
        case 1:
            eff = decode_private(key_format.pkcs8, algorithm, body)
        case 2:
            eff = decode_private(key_format.pkcs1, algorithm, body)
        case 3:
            eff = decode_private(key_format.sec1, algorithm, body)
        case 4:
            pem = key_format.pem(key_format.spki)
            eff = decode_public(pem, algorithm, text(body))
        case _:
            value: Any = raises_only(lambda: _json_text.parse(body), ValueError)
            if not isinstance(value, dict):
                return
            eff = effect.suspend(
                lambda: decode_private(key_format.jwk, algorithm, value).catch_all(
                    lambda _error: decode_public(key_format.jwk, algorithm, value)  # pyright: ignore[reportUnknownLambdaType]
                )
            )
    settle(eff, CryptoError)
