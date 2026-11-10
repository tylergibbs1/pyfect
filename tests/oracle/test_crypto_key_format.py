"""Ports of Effect's ``crypto/KeyFormat.test.ts``.

Keys are generated and encoded by the ``cryptography`` package (``node:crypto``
in Effect's test), independently of the module under test. Its
``TraditionalOpenSSL`` private format is PKCS#1 for RSA and SEC1 for EC.
"""

from __future__ import annotations

from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect._binary_codecs import base64_url_encode
from pyfect.crypto import aead, digest, key_agreement, key_format, key_wrap, mac, signature
from pyfect.crypto._subtle import host
from pyfect.crypto.web_crypto import CryptoKeyPair, JsonWebKey, Params

from ._crypto import assert_reason, from_hex, unreachable


def _primitives() -> Any:
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa, x25519

    return ec, ed25519, rsa, x25519


_ec, _ed25519, _rsa, _x25519 = _primitives()
P256 = _ec.generate_private_key(_ec.SECP256R1())
P384 = _ec.generate_private_key(_ec.SECP384R1())
ED25519 = _ed25519.Ed25519PrivateKey.generate()
X25519 = _x25519.X25519PrivateKey.generate()
RSA = _rsa.generate_private_key(public_exponent=65537, key_size=2048)


def der(key: Any, kind: str) -> bytes:
    from cryptography.hazmat.primitives import serialization as s

    if kind == "spki":
        return key.public_key().public_bytes(s.Encoding.DER, s.PublicFormat.SubjectPublicKeyInfo)
    private_format = (
        s.PrivateFormat.PKCS8 if kind == "pkcs8" else s.PrivateFormat.TraditionalOpenSSL
    )
    return key.private_bytes(s.Encoding.DER, private_format, s.NoEncryption())


def pem(key: Any, kind: str) -> str:
    from cryptography.hazmat.primitives import serialization as s

    if kind == "spki":
        data = key.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo)
    else:
        private_format = (
            s.PrivateFormat.PKCS8 if kind == "pkcs8" else s.PrivateFormat.TraditionalOpenSSL
        )
        data = key.private_bytes(s.Encoding.PEM, private_format, s.NoEncryption())
    return data.decode()


def _b64(n: int, size: int | None = None) -> str:
    length = size if size is not None else max(1, (n.bit_length() + 7) // 8)
    return base64_url_encode(n.to_bytes(length))


def jwk(key: Any, *, public: bool = False) -> JsonWebKey:
    """``KeyObject.export({ format: "jwk" })``."""
    from cryptography.hazmat.primitives import serialization as s

    if isinstance(key, _ec.EllipticCurvePrivateKey):
        size = (key.curve.key_size + 7) // 8
        numbers = key.private_numbers()
        crv = {"secp256r1": "P-256", "secp384r1": "P-384", "secp521r1": "P-521"}[key.curve.name]
        out: JsonWebKey = {
            "kty": "EC",
            "crv": crv,
            "x": _b64(numbers.public_numbers.x, size),
            "y": _b64(numbers.public_numbers.y, size),
        }
        if not public:
            out["d"] = _b64(numbers.private_value, size)
        return out
    if isinstance(key, _ed25519.Ed25519PrivateKey | _x25519.X25519PrivateKey):
        crv = "Ed25519" if isinstance(key, _ed25519.Ed25519PrivateKey) else "X25519"
        raw = key.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)
        out = {"kty": "OKP", "crv": crv, "x": base64_url_encode(raw)}
        if not public:
            out["d"] = base64_url_encode(
                key.private_bytes(s.Encoding.Raw, s.PrivateFormat.Raw, s.NoEncryption())
            )
        return out
    numbers = key.private_numbers()
    out = {"kty": "RSA", "n": _b64(numbers.public_numbers.n), "e": _b64(numbers.public_numbers.e)}
    if not public:
        out.update(
            d=_b64(numbers.d),
            p=_b64(numbers.p),
            q=_b64(numbers.q),
            dp=_b64(numbers.dmp1),
            dq=_b64(numbers.dmq1),
            qi=_b64(numbers.iqmp),
        )
    return out


def node_jwk(pkcs8: bytes) -> JsonWebKey:
    """The private key behind PKCS#8 bytes, read back by ``cryptography``."""
    from cryptography.hazmat.primitives.serialization import load_der_private_key

    return jwk(load_der_private_key(pkcs8, None))


def jwk_d(key: Any) -> bytes:
    from pyfect._binary_codecs import base64_url_decode

    decoded = base64_url_decode(jwk(key).get("d", ""))
    assert isinstance(decoded, fx.result.Ok)
    return decoded.value


rsa_pss_2048 = signature.rsa_pss(hash=digest.sha256, modulus_length=2048)
rsa_oaep_2048 = key_wrap.rsa_oaep(hash=digest.sha256, modulus_length=2048)


@testing.effect
def test_rejects_rsa_pkcs8_decoded_as_ecdsa_with_invalid_key():
    """rejects RSA PKCS#8 decoded as ECDSA with InvalidKey"""
    error = yield from key_format.decode_private(
        key_format.pkcs8, signature.ecdsa_p256, der(RSA, "pkcs8")
    ).flip()
    assert_reason(error, "InvalidKey", "decodePrivate")


@testing.effect
def test_rejects_a_point_less_p_384_pkcs8_decoded_as_p_256_with_invalid_key():
    """rejects a point-less P-384 PKCS#8 decoded as P-256 with InvalidKey"""
    pkcs8 = from_hex("304e020100301006072a8648ce3d020106052b81040022043730350201010430") + jwk_d(
        P384
    )
    error = yield from key_format.decode_private(
        key_format.pkcs8, signature.ecdsa_p256, pkcs8
    ).flip()
    assert_reason(error, "InvalidKey", "decodePrivate")


@testing.effect
def test_reports_the_imported_rsa_pkcs8_modulus_rather_than_the_generation_default():
    """reports the imported RSA PKCS#8 modulus rather than the generation default"""
    key = yield from key_format.decode_private(
        key_format.pkcs8, signature.rsa_pss_sha256, der(RSA, "pkcs8")
    )
    assert key.algorithm.modulus_length == 2048


@testing.effect
def test_decodes_and_encodes_spki_and_pkcs8_for_every_asymmetric_family():
    """decodes and encodes SPKI and PKCS#8 for every asymmetric family"""
    cases: list[tuple[key_format.AsymmetricAlgorithm, Any]] = [
        (signature.ecdsa_p256, P256),
        (key_agreement.ecdh_p384, P384),
        (signature.ed25519, ED25519),
        (key_agreement.x25519, X25519),
        (rsa_pss_2048, RSA),
        (rsa_oaep_2048, RSA),
    ]
    for algorithm, pair in cases:
        public_key = yield from key_format.decode_public(
            key_format.spki, algorithm, der(pair, "spki")
        )
        assert public_key.algorithm is algorithm
        assert (yield from key_format.encode(key_format.spki, public_key)) == der(pair, "spki")

        private_key = yield from key_format.decode_private(
            key_format.pkcs8, algorithm, der(pair, "pkcs8")
        )
        assert private_key.algorithm is algorithm
        encoded = yield from key_format.encode(key_format.pkcs8, private_key)
        assert node_jwk(encoded) == jwk(pair)

    # Decoded keys hold the stored forms: an EC private key's PKCS#8 and an
    # Ed25519 seed.
    ec_private = yield from key_format.decode_private(
        key_format.pkcs8, signature.ecdsa_p256, der(P256, "pkcs8")
    )
    assert (yield from signature.to_bytes(ec_private)) == (
        yield from key_format.encode(key_format.pkcs8, ec_private)
    )
    ed_private = yield from key_format.decode_private(
        key_format.pkcs8, signature.ed25519, der(ED25519, "pkcs8")
    )
    assert (yield from signature.to_bytes(ed_private)) == jwk_d(ED25519)


@testing.effect
def test_rejects_malformed_der_and_keys_for_another_algorithm():
    """rejects malformed DER and keys for another algorithm"""
    cases: list[tuple[signature.Algorithm, bytes]] = [
        (signature.ecdsa_p256, bytes(32)),
        (signature.ecdsa_p256, der(P384, "spki")),
        (signature.ed25519, der(X25519, "spki")),
    ]
    for algorithm, data in cases:
        error = yield from key_format.decode_public(key_format.spki, algorithm, data).flip()
        assert_reason(error, "InvalidKey", "decodePublic")
    error = yield from key_format.decode_private(
        key_format.pkcs8, signature.ecdsa_p256, der(P256, "spki")
    ).flip()
    assert_reason(error, "InvalidKey", "decodePrivate")

    subtle = host.subtle
    assert subtle is not None
    crypto_key = subtle.generate_key(
        Params(name="ECDSA", named_curve="P-256"), False, ["sign", "verify"]
    )
    assert isinstance(crypto_key, CryptoKeyPair)
    non_extractable = yield from signature.private_key_from_crypto_key(
        signature.ecdsa_p256, crypto_key.private_key
    )
    error = yield from key_format.encode(key_format.pkcs8, non_extractable).flip()
    assert_reason(error, "NotExtractable", "encode")

    # Formats carry their role, direction and data type.
    def type_errors() -> None:
        key_format.decode_public(key_format.pkcs8, signature.ecdsa_p256, b"")  # pyright: ignore[reportCallIssue, reportArgumentType]
        key_format.encode(key_format.pkcs1, non_extractable)  # pyright: ignore[reportCallIssue, reportArgumentType]
        key_format.decode_public(key_format.pem(key_format.spki), signature.ecdsa_p256, b"")  # pyright: ignore[reportCallIssue, reportArgumentType]

    del type_errors


@testing.effect
def test_imports_pkcs1_and_sec1_private_keys_checking_the_sec1_curve():
    """imports PKCS#1 and SEC1 private keys, checking the SEC1 curve"""
    from_pkcs1 = yield from key_format.decode_private(
        key_format.pkcs1, rsa_pss_2048, der(RSA, "pkcs1")
    )
    assert node_jwk((yield from key_format.encode(key_format.pkcs8, from_pkcs1))) == jwk(RSA)

    # cryptography writes SEC1 with the [0] curve parameters and [1] point.
    algorithms: list[signature.Ecdsa[Any] | key_agreement.Ecdh[Any]] = [
        signature.ecdsa_p256,
        key_agreement.ecdh_p256,
    ]
    for algorithm in algorithms:
        from_sec1 = yield from key_format.decode_private(
            key_format.sec1, algorithm, der(P256, "sec1")
        )
        assert node_jwk((yield from key_format.encode(key_format.pkcs8, from_sec1))) == jwk(P256)
    error = yield from key_format.decode_private(
        key_format.sec1, signature.ecdsa_p384, der(P256, "sec1")
    ).flip()
    assert_reason(error, "InvalidKey", "decodePrivate")

    # Safari cannot import an EC private key without its public point, so it
    # is refused everywhere.
    d = jwk_d(P256)
    curve = from_hex("06082a8648ce3d030107")
    sec1 = from_hex("3031020101") + bytes([0x04, 0x20]) + d + bytes([0xA0, 0x0A]) + curve
    pkcs8 = (
        from_hex("3041020100301306072a8648ce3d0201")
        + curve
        + from_hex("0427302502010104")
        + bytes([0x20])
        + d
    )
    error = yield from key_format.decode_private(key_format.sec1, signature.ecdsa_p256, sec1).flip()
    assert_reason(error, "Unsupported", "decodePrivate")
    error = yield from key_format.decode_private(
        key_format.pkcs8, signature.ecdsa_p256, pkcs8
    ).flip()
    assert_reason(error, "Unsupported", "decodePrivate")


@testing.effect
def test_reads_and_writes_strict_pem():
    """reads and writes strict PEM"""
    spki_pem = pem(RSA, "spki")
    public_key = yield from key_format.decode_public(
        key_format.pem(key_format.spki), rsa_pss_2048, spki_pem
    )
    # One block with 64-column lines, as OpenSSL writes it.
    encoded = yield from key_format.encode(key_format.pem(key_format.spki), public_key)
    assert encoded.strip() == spki_pem.strip()

    cases = [
        (key_format.pem(key_format.pkcs8), pem(RSA, "pkcs8")),
        (key_format.pem(key_format.pkcs1), pem(RSA, "pkcs1")),
    ]
    for format, data in cases:
        private_key = yield from key_format.decode_private(format, rsa_pss_2048, data)
        assert node_jwk((yield from key_format.encode(key_format.pkcs8, private_key))) == jwk(RSA)
    from_sec1 = yield from key_format.decode_private(
        key_format.pem(key_format.sec1), signature.ecdsa_p256, pem(P256, "sec1")
    )
    assert node_jwk((yield from key_format.encode(key_format.pkcs8, from_sec1))) == jwk(P256)

    # The label must match, and there must be exactly one block.
    for data in [pem(RSA, "pkcs8"), spki_pem + spki_pem, "not a key"]:
        error = yield from key_format.decode_public(
            key_format.pem(key_format.spki), rsa_pss_2048, data
        ).flip()
        assert_reason(error, "InvalidKey", "decodePublic")


@testing.effect
def test_reads_and_writes_jwk_with_only_kty_crv_and_the_key_material():
    """reads and writes JWK with only kty, crv and the key material"""
    cases: list[tuple[signature.Algorithm, Any]] = [
        (signature.ecdsa_p256, P256),
        (signature.ed25519, ED25519),
    ]
    for algorithm, pair in cases:
        public_jwk = jwk(pair, public=True)
        private_jwk = jwk(pair)
        # JOSE members other than kty, crv and alg are ignored on import.
        decorated = cast(
            "JsonWebKey",
            {**public_jwk, "use": "sig", "kid": "1", "key_ops": ["verify"], "ext": True},
        )
        public_key = yield from key_format.decode_public(key_format.jwk, algorithm, decorated)
        assert (yield from key_format.encode(key_format.jwk, public_key)) == public_jwk
        private_key = yield from key_format.decode_private(key_format.jwk, algorithm, private_jwk)
        assert (yield from key_format.encode(key_format.jwk, private_key)) == private_jwk

        # d decides the role.
        error = yield from key_format.decode_public(key_format.jwk, algorithm, private_jwk).flip()
        assert_reason(error, "InvalidKey", "decodePublic")
        error = yield from key_format.decode_private(key_format.jwk, algorithm, public_jwk).flip()
        assert_reason(error, "InvalidKey", "decodePrivate")

    # alg, crv and kty are checked when present.
    p256_jwk = jwk(P256, public=True)
    with_alg: JsonWebKey = {**p256_jwk, "alg": "ES256"}
    decoded = yield from key_format.decode_public(key_format.jwk, signature.ecdsa_p256, with_alg)
    assert decoded.algorithm is signature.ecdsa_p256
    mismatches: list[JsonWebKey] = [{"alg": "ES384"}, {"crv": "P-384"}, {"kty": "OKP"}]
    for mismatch in mismatches:
        error = yield from key_format.decode_public(
            key_format.jwk, signature.ecdsa_p256, {**p256_jwk, **mismatch}
        ).flip()
        assert_reason(error, "InvalidKey", "decodePublic")

    secret: JsonWebKey = {"kty": "oct", "k": base64_url_encode(bytes([7] * 32))}
    mac_key = yield from key_format.decode_secret(
        key_format.jwk, mac.hmac_sha256, {**secret, "alg": "HS256"}
    )
    assert (yield from mac.to_bytes(mac_key)) == bytes([7] * 32)
    assert (yield from key_format.encode(key_format.jwk, mac_key)) == secret
    error = yield from key_format.decode_secret(
        key_format.jwk, mac.hmac_sha256, {**secret, "alg": "HS512"}
    ).flip()
    assert_reason(error, "InvalidKey", "decodeSecret")
    kek = yield from key_format.decode_secret(key_format.jwk, key_wrap.aes256_kw, secret)
    assert (yield from key_wrap.to_bytes(kek)) == bytes([7] * 32)


@testing.effect
def test_handles_chacha_jwk_without_subtle():
    """handles ChaCha JWK without subtle"""
    secret: JsonWebKey = {"kty": "oct", "k": base64_url_encode(bytes([7] * 32))}

    @fx.gen
    def program():
        for algorithm in [aead.chacha20_poly1305, aead.xchacha20_poly1305]:
            key = yield from key_format.decode_secret(key_format.jwk, algorithm, secret)
            assert key.algorithm is algorithm
            assert (yield from aead.to_bytes(key)) == bytes([7] * 32)
            assert (yield from key_format.encode(key_format.jwk, key)) == secret
        bad: list[JsonWebKey] = [
            {**secret, "kty": "RSA"},
            {"kty": "oct", "k": base64_url_encode(bytes(16))},
        ]
        for data in bad:
            error = yield from key_format.decode_secret(
                key_format.jwk, aead.chacha20_poly1305, data
            ).flip()
            assert_reason(error, "InvalidKey", "decodeSecret")

    return program.pipe(fx.provide(unreachable))
