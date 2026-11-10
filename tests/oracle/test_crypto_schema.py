"""Ports of Effect's ``crypto/Schema.test.ts`` (Effect's ``Schema`` crypto
keys, ``pyfect.crypto.schema`` here).

The Ed25519 and EC keys are encoded by the ``cryptography`` package
(``node:crypto`` in Effect's test), independently of the module under test.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

import pyfect as fx
from pyfect import config, testing
from pyfect import config_provider as cp
from pyfect import schema as S
from pyfect._binary_codecs import base64_encode, base64_url_encode
from pyfect.crypto import aead, crypto_error, digest, key_format, mac, signature
from pyfect.crypto import schema as CS
from pyfect.exit import Exit, Failure
from pyfect.schema import representation as R
from pyfect.schema.issue import Forbidden, InvalidValue, Issue


def _keys() -> tuple[Any, Any, Any]:
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

    return (
        ed25519.Ed25519PrivateKey.generate(),
        ec.generate_private_key(ec.SECP256R1()),
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
    )


ED25519, P256, RSA = _keys()


def _spki(key: Any) -> bytes:
    from cryptography.hazmat.primitives import serialization as s

    return key.public_key().public_bytes(s.Encoding.DER, s.PublicFormat.SubjectPublicKeyInfo)


def _spki_pem(key: Any) -> str:
    from cryptography.hazmat.primitives import serialization as s

    return (
        key.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo).decode()
    )


def _pkcs8(key: Any) -> bytes:
    from cryptography.hazmat.primitives import serialization as s

    return key.private_bytes(s.Encoding.DER, s.PrivateFormat.PKCS8, s.NoEncryption())


def leaves(issue: Issue) -> list[Issue]:
    inner = getattr(issue, "issues", None)
    if inner is not None:
        return [leaf for i in inner for leaf in leaves(i)]
    one = getattr(issue, "issue", None)
    if one is not None:
        return leaves(one)
    return [issue]


def failure(exit: Exit[Any, S.SchemaError]) -> Issue:
    match exit.cause.find_error() if isinstance(exit, Failure) else None:
        case fx.Ok(error):
            found = leaves(error.issue)
            assert len(found) == 1
            return found[0]
        case other:
            raise AssertionError(other)


p256_sha512 = dataclasses.replace(signature.ecdsa_p256, hash=digest.sha512)


@testing.effect
def test_declared_schemas_reject_a_key_with_a_different_operation_defining_hash():
    """declared schemas reject a key with a different operation-defining hash"""
    key = yield from key_format.decode_public(key_format.spki, p256_sha512, _spki(P256))
    assert not S.is_(CS.SignaturePublicKey(signature.ecdsa_p256))(key)


@testing.effect
def test_generated_code_for_a_custom_hash_schema_accepts_the_same_keys():
    """generated code for a custom-hash schema accepts the same keys"""
    key = yield from key_format.decode_public(key_format.spki, p256_sha512, _spki(P256))
    schema = CS.SignaturePublicKey(p256_sha512)
    assert S.is_(schema)(key)

    output = R.to_code_document(R.to_representations((schema,)))
    assert R.ImportArtifact("from pyfect.crypto import digest") in output.artifacts
    namespace: dict[str, object] = {"__name__": "generated"}
    exec(R.to_code_module(output), namespace)
    generated: Any = namespace["Schema0"]
    assert S.is_(generated)(key)


@testing.effect
def test_declared_rsa_schemas_ignore_generation_only_modulus_length():
    """declared RSA schemas ignore generation-only modulus length"""
    key = yield from key_format.decode_public(
        key_format.spki, signature.rsa_pss(hash=digest.sha256, modulus_length=2048), _spki(RSA)
    )
    assert S.is_(CS.SignaturePublicKey(signature.rsa_pss_sha256))(key)


@testing.effect
def test_from_bytes_decodes_synchronously_and_maps_a_crypto_error_to_invalid_value():
    """FromBytes decodes synchronously and maps a CryptoError to InvalidValue"""
    data = bytes([7] * 32)
    key = S.decode_sync(CS.AeadKeyFromBytes(aead.aes256_gcm))(data)
    assert S.is_(CS.AeadKey(aead.aes256_gcm))(key)
    assert (yield from aead.to_bytes(key)) == data

    issue = failure(S.decode_unknown_exit(CS.AeadKeyFromBytes(aead.aes256_gcm))(bytes(16)))
    assert isinstance(issue, InvalidValue)
    assert issue.annotations is not None
    cause = issue.annotations["cause"]
    assert isinstance(cause, crypto_error.CryptoError)
    assert issue.annotations["message"] == cause.message

    # Public keys read and write; secret keys only read.
    public_bytes = bytes([9] * 32)
    public_schema = CS.SignaturePublicKeyFromBytes(signature.ed25519)
    public_key = S.decode_sync(public_schema)(public_bytes)
    assert (yield from S.encode_effect(public_schema)(public_key)) == public_bytes
    exit = yield from S.encode_effect(CS.AeadKeyFromBytes(aead.aes256_gcm))(key).exit()
    assert isinstance(failure(exit), Forbidden)


@testing.effect
def test_from_bytes_reads_base64_under_config_schema():
    """FromBytes reads base64 under Config.schema"""
    data = bytes([3] * 32)
    provider = cp.from_env({"MAC_KEY": base64_encode(data)})
    key = yield from config.schema(CS.MacKeyFromBytes(mac.hmac_sha256), "MAC_KEY").parse(provider)
    assert key.algorithm is mac.hmac_sha256
    assert (yield from mac.to_bytes(key)) == data


@testing.effect
def test_from_format_decodes_asynchronously_and_only_encodes_private_keys_when_allowed():
    """FromFormat decodes asynchronously and only encodes private keys when allowed"""
    spki_pem = _spki_pem(ED25519)
    pkcs8_der = _pkcs8(ED25519)
    public_schema = CS.SignaturePublicKeyFromFormat(
        key_format.pem(key_format.spki), signature.ed25519
    )
    with pytest.raises(RuntimeError, match="Sync adapter"):
        S.decode_sync(public_schema)(spki_pem)
    public_key = yield from S.decode_effect(public_schema)(spki_pem)
    assert public_key.algorithm is signature.ed25519
    assert (yield from S.encode_effect(public_schema)(public_key)) == spki_pem

    private_key = yield from S.decode_effect(
        CS.SignaturePrivateKeyFromFormat(key_format.pkcs8, signature.ed25519)
    )(pkcs8_der)
    forbidden = yield from S.encode_effect(
        CS.SignaturePrivateKeyFromFormat(key_format.pkcs8, signature.ed25519)
    )(private_key).exit()
    assert isinstance(failure(forbidden), Forbidden)
    allowed = CS.SignaturePrivateKeyFromFormat(
        key_format.pkcs8, signature.ed25519, allow_encode=True
    )
    assert (yield from S.encode_effect(allowed)(private_key)) == pkcs8_der

    k = base64_url_encode(bytes([5] * 32))
    secret_schema = CS.AeadKeyFromFormat(key_format.jwk, aead.aes256_gcm, allow_encode=True)
    # Secret keys skip subtle, but format schemas stay asynchronous only.
    with pytest.raises(RuntimeError, match="Sync adapter"):
        S.decode_sync(secret_schema)({"kty": "oct", "k": k})
    secret_key = yield from S.decode_effect(secret_schema)({"kty": "oct", "k": k})
    assert (yield from S.encode_effect(secret_schema)(secret_key)) == {"kty": "oct", "k": k}

    invalid = yield from S.decode_effect(public_schema)("not a key").exit()
    issue = failure(invalid)
    assert isinstance(issue, InvalidValue)
    assert issue.annotations is not None
    assert crypto_error.is_crypto_error(issue.annotations["cause"])


@testing.effect
def test_declared_schemas_check_the_algorithm_redact_and_compare_by_reference():
    """declared schemas check the algorithm, redact, and compare by reference"""
    schema = CS.AeadKey(aead.aes256_gcm)
    key = yield from aead.key(aead.aes256_gcm, bytes([1] * 32))
    same = yield from aead.key(aead.aes256_gcm, bytes([1] * 32))
    other = yield from aead.key(aead.aes256_gcm, bytes([2] * 32))

    assert S.decode_unknown_sync(schema)(key) is key
    assert not S.is_(schema)((yield from aead.key(aead.aes128_gcm, bytes(16))))
    assert not S.is_(schema)((yield from mac.key(mac.hmac_sha256, bytes([1] * 32))))
    assert not S.is_(schema)(bytes(32))

    format = S.to_formatter(schema)
    assert format(key) == format(other)
    assert "0101" not in format(key)

    equivalence = S.to_equivalence(schema)
    assert equivalence(key, key)
    assert not equivalence(key, same)

    with pytest.raises(ValueError):
        S.to_strategy(schema)

    public_key = yield from signature.public_key(signature.ed25519, bytes([9] * 32))
    json = S.encode_unknown_exit(S.to_codec_json(CS.SignaturePublicKey(signature.ed25519)))(
        public_key
    )
    issue = failure(json)
    assert isinstance(issue, Forbidden)
    assert issue.annotations is not None
    assert "SignaturePublicKeyFromFormat" in str(issue.annotations["message"])
