"""Helpers for the ``pyfect.jose`` ports (Effect's ``test/jose/utils.ts``).

``fixtures/jose_node.json`` holds keys and tokens made by Node's ``jose``
6.2.14 (the reference Effect's interop tests use), so the ports check
pyfect against it without running Node."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pyfect._binary_codecs import base64_url_decode, base64_url_encode
from pyfect.crypto import aead, digest, mac, secure_random, signature
from pyfect.jose.jose_error import JoseError
from pyfect.jose.jwk import PrivateJwk, PublicJwk, SecretJwk
from pyfect.layer import merge, provide_merge
from pyfect.result import Ok
from pyfect.schema import SchemaError

layer = merge(
    aead.layer_web_crypto,
    digest.layer_web_crypto,
    mac.layer_web_crypto,
    signature.layer_web_crypto,
).pipe(provide_merge(secure_random.layer_web_crypto))

NODE: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "jose_node.json").read_text()
)


def utf8(text: str) -> bytes:
    return text.encode()


def text(data: bytes) -> str:
    return data.decode()


def b64(data: bytes | str) -> str:
    return base64_url_encode(data.encode() if isinstance(data, str) else data)


def unb64(encoded: str) -> bytes:
    decoded = base64_url_decode(encoded)
    assert isinstance(decoded, Ok)
    return decoded.value


def json_b64(value: object) -> str:
    return b64(json.dumps(value, separators=(",", ":")))


def assert_reason(error: JoseError | SchemaError | object, reason: str) -> JoseError:
    assert isinstance(error, JoseError), error
    assert error.reason.tag == reason, error
    return error


# RFC 7515, Appendix A. Every example signs the same payload.
RFC7515_PAYLOAD = (
    "eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFtcGxlLmNvbS9pc19yb290Ijp0cnVlfQ"
)
# A.1
HS256_JWK: SecretJwk = {
    "kty": "oct",
    "k": "AyM1SysPpbyDfgZld3umj1qzKObwVMkoqQ-EstJQLr_T-1qS0gZH75aKtMN3Yj0iPS4hcgUuTwjAzZr1Z9CAow",
}
HS256_TOKEN = (
    "eyJ0eXAiOiJKV1QiLA0KICJhbGciOiJIUzI1NiJ9"
    f".{RFC7515_PAYLOAD}"
    ".dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
)
# A.2
RS256_JWK: PrivateJwk = {
    "kty": "RSA",
    "n": "ofgWCuLjybRlzo0tZWJjNiuSfb4p4fAkd_wWJcyQoTbji9k0l8W26mPddxHmfHQp-Vaw-4qPCJrcS2mJPMEzP1Pt0Bm4d4QlL-yRT-SFd2lZS-pCgNMsD1W_YpRPEwOWvG6b32690r2jZ47soMZo9wGzjb_7OMg0LOL-bSf63kpaSHSXndS5z5rexMdbBYUsLA9e-KXBdQOS-UTo7WTBEMa2R2CapHg665xsmtdVMTBQY4uDZlxvb3qCo5ZwKh9kG4LT6_I5IhlJH7aGhyxXFvUK-DWNmoudF8NAco9_h9iaGNj8q2ethFkMLs91kzk2PAcDTW9gb54h4FRWyuXpoQ",  # noqa: E501
    "e": "AQAB",
    "d": "Eq5xpGnNCivDflJsRQBXHx1hdR1k6Ulwe2JZD50LpXyWPEAeP88vLNO97IjlA7_GQ5sLKMgvfTeXZx9SE-7YwVol2NXOoAJe46sui395IW_GO-pWJ1O0BkTGoVEn2bKVRUCgu-GjBVaYLU6f3l9kJfFNS3E0QbVdxzubSu3Mkqzjkn439X0M_V51gfpRLI9JYanrC4D4qAdGcopV_0ZHHzQlBjudU2QvXt4ehNYTCBr6XCLQUShb1juUO1ZdiYoFaFQT5Tw8bGUl_x_jTj3ccPDVZFD9pIuhLhBOneufuBiB4cS98l2SR_RQyGWSeWjnczT0QU91p1DhOVRuOopznQ",  # noqa: E501
    "p": "4BzEEOtIpmVdVEZNCqS7baC4crd0pqnRH_5IB3jw3bcxGn6QLvnEtfdUdiYrqBdss1l58BQ3KhooKeQTa9AB0Hw_Py5PJdTJNPY8cQn7ouZ2KKDcmnPGBY5t7yLc1QlQ5xHdwW1VhvKn-nXqhJTBgIPgtldC-KDV5z-y2XDwGUc",  # noqa: E501
    "q": "uQPEfgmVtjL0Uyyx88GZFF1fOunH3-7cepKmtH4pxhtCoHqpWmT8YAmZxaewHgHAjLYsp1ZSe7zFYHj7C6ul7TjeLQeZD_YwD66t62wDmpe_HlB-TnBA-njbglfIsRLtXlnDzQkv5dTltRJ11BKBBypeeF6689rjcJIDEz9RWdc",  # noqa: E501
    "dp": "BwKfV3Akq5_MFZDFZCnW-wzl-CCo83WoZvnLQwCTeDv8uzluRSnm71I3QCLdhrqE2e9YkxvuxdBfpT_PI7Yz-FOKnu1R6HsJeDCjn12Sk3vmAktV2zb34MCdy7cpdTh_YVr7tss2u6vneTwrA86rZtu5Mbr1C1XsmvkxHQAdYo0",  # noqa: E501
    "dq": "h_96-mK1R_7glhsum81dZxjTnYynPbZpHziZjeeHcXYsXaaMwkOlODsWa7I9xXDoRwbKgB719rrmI2oKr6N3Do9U0ajaHF-NKJnwgjMd2w9cjz3_-kyNlxAr2v4IKhGNpmM5iIgOS1VZnOZ68m6_pbLBSp3nssTdlqvd0tIiTHU",  # noqa: E501
    "qi": "IYd7DHOhrWvxkwPQsRM2tOgrjbcrfvtQJipd-DlcxyVuuM9sQLdgjVk2oy26F0EmpScGLq2MowX7fhd_QJQ3ydy5cY7YIBi87w93IKLEdfnbJtoOPLUW0ITrJReOgo1cq9SbsxYawBgfp_gh6A5603k2-ZQwVK0JKSHuLFkuQ3U",  # noqa: E501
}
RS256_TOKEN = (
    "eyJhbGciOiJSUzI1NiJ9"
    f".{RFC7515_PAYLOAD}"
    ".cC4hiUPoj9Eetdgtv3hF80EGrhuB__dzERat0XF9g2VtQgr9PJbu3XOiZj5RZmh7AAuHIm4Bh-0Qc_lF5YKt_O8W2Fp5jujGbds9uJdbF9CUAr7t1dnZcAcQjbKBYNX4BAynRFdiuB--f_nZLgrnbyTyWzO75vRK5h6xBArLIARNPvkSjtQBMHlb1L07Qe7K0GarZRmB_eSN9383LcOLn6_dO--xi12jzDwusC-eOkHWEsqtFZESc6BfI7noOPqvhJ1phCnvWh6IeYI2w9QOYEUipUTI8np6LbgGY9Fs98rqVt5AXLIhWkWywlVmtVrBp0igcN_IoypGlUPQGe77Rw"
)
# A.3
ES256_JWK: PrivateJwk = {
    "kty": "EC",
    "crv": "P-256",
    "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
    "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0",
    "d": "jpsQnnGQmL-YBIffH1136cspYG6-0iY7X1fCE9-E9LI",
}
ES256_TOKEN = (
    "eyJhbGciOiJFUzI1NiJ9"
    f".{RFC7515_PAYLOAD}"
    ".DtEhU3ljbEg8L38VWAfUAqOyKAM6-Xx-F4GawxaepmXFCgfTjDxw5djxLa8ISlSApmWQxfKTUJqPP3-Kg6NU1Q"
)


def without(jwk: Any, *names: str) -> dict[str, Any]:
    return {name: value for name, value in jwk.items() if name not in names}


RS256_PUBLIC_JWK = cast("PublicJwk", without(RS256_JWK, "d", "p", "q", "dp", "dq", "qi"))
ES256_PUBLIC_JWK = cast("PublicJwk", without(ES256_JWK, "d"))

# 32 bytes, the only length ``dir`` / A256GCM accepts.
SECRET = bytes([7] * 32)
SECRET_JWK: SecretJwk = {"kty": "oct", "k": b64(SECRET)}


def _int(member: str) -> int:
    return int.from_bytes(unb64(member), "big")


_HASHES: dict[str, type[hashes.HashAlgorithm]] = {
    "256": hashes.SHA256,
    "384": hashes.SHA384,
    "512": hashes.SHA512,
}
_CURVES: dict[str, ec.EllipticCurve] = {
    "P-256": ec.SECP256R1(),
    "P-384": ec.SECP384R1(),
    "P-521": ec.SECP521R1(),
}


def reference_verify(token: str, public_jwk: Any) -> dict[str, Any]:
    """Check a compact JWS with ``cryptography``, independently of
    ``pyfect.crypto``; the protected header when it is valid."""
    header, payload, sig = token.split(".")
    protected = json.loads(unb64(header))
    alg: str = protected["alg"]
    data, signature_bytes = f"{header}.{payload}".encode(), unb64(sig)
    try:
        if alg == "EdDSA":
            ed25519.Ed25519PublicKey.from_public_bytes(unb64(public_jwk["x"])).verify(
                signature_bytes, data
            )
        elif alg.startswith("ES"):
            curve = _CURVES[public_jwk["crv"]]
            size = len(signature_bytes) // 2
            r = int.from_bytes(signature_bytes[:size], "big")
            s = int.from_bytes(signature_bytes[size:], "big")
            point = ec.EllipticCurvePublicNumbers(
                _int(public_jwk["x"]), _int(public_jwk["y"]), curve
            ).public_key()
            point.verify(encode_dss_signature(r, s), data, ec.ECDSA(_HASHES[alg[2:]]()))
        else:
            key = rsa.RSAPublicNumbers(_int(public_jwk["e"]), _int(public_jwk["n"])).public_key()
            hash = _HASHES[alg[2:]]()
            pad: padding.AsymmetricPadding = (
                padding.PSS(mgf=padding.MGF1(hash), salt_length=hash.digest_size)
                if alg.startswith("PS")
                else padding.PKCS1v15()
            )
            key.verify(signature_bytes, data, pad, hash)
    except InvalidSignature as error:
        raise AssertionError(f"{alg} signature rejected") from error
    return protected


def reference_decrypt(token: str, secret: bytes) -> tuple[dict[str, Any], bytes]:
    """Decrypt a compact ``dir`` / A256GCM JWE with ``cryptography``,
    independently of ``pyfect.crypto``."""
    header, encrypted_key, iv, ciphertext, tag = token.split(".")
    assert encrypted_key == ""
    plaintext = AESGCM(secret).decrypt(unb64(iv), unb64(ciphertext) + unb64(tag), header.encode())
    return json.loads(unb64(header)), plaintext
