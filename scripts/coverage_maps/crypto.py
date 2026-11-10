"""Effect's ``effect/crypto`` and ``effect/jose`` modules, and
platform-node's ``NodeCrypto`` (``pyfect.crypto.native``)."""

from api_coverage import Cluster, Module


def _crypto(name: str, module: str, renamed: dict[str, str] | None = None) -> Module:
    return Module(name, f"effect/src/crypto/{name}.ts", (f"pyfect.crypto.{module}",), renamed or {})


def _jose(name: str, module: str) -> Module:
    return Module(name, f"effect/src/jose/{name}.ts", (f"pyfect.jose.{module}",))


CLUSTER = Cluster(
    "crypto",
    "Cryptography and JOSE",
    (
        _crypto("Aead", "aead"),
        _crypto("Cipher", "cipher"),
        _crypto("CryptoError", "crypto_error"),
        _crypto("Digest", "digest"),
        _crypto("Kdf", "kdf"),
        _crypto("KeyAgreement", "key_agreement"),
        _crypto("KeyFormat", "key_format"),
        # The family dispatch is two functions: a key from bytes and back.
        _crypto("KeyWrap", "key_wrap", {"secretFamily": "pyfect.crypto.key_wrap.secret_key"}),
        _crypto("Mac", "mac"),
        _crypto("SecureRandom", "secure_random"),
        _crypto("Signature", "signature"),
        _crypto("WebCrypto", "web_crypto"),
        _jose("JoseError", "jose_error"),
        _jose("Jwe", "jwe"),
        _jose("Jwk", "jwk"),
        _jose("Jwks", "jwks"),
        _jose("Jws", "jws"),
        _jose("Jwt", "jwt"),
        Module(
            "NodeCrypto",
            "platform/node-shared/src/NodeCrypto.ts",
            ("pyfect.crypto.native",),
        ),
    ),
)
