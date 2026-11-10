"""The ``crypto`` extra's libraries, ``cryptography`` and PyNaCl. ``pyfect.crypto``
uses them only through this module, so a missing extra always fails with the
command that installs it (``tests/test_install.py`` checks)."""

from pyfect._extras import missing_extra

try:
    from cryptography.exceptions import InvalidSignature, InvalidTag, UnsupportedAlgorithm
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import (
        ec,
        ed25519,
        padding,
        rsa,
        utils,
        x25519,
    )
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.keywrap import (
        InvalidUnwrap,
        aes_key_unwrap,
        aes_key_wrap,
    )
    from cryptography.hazmat.primitives.padding import PKCS7
    from nacl import bindings as nacl_bindings
    from nacl.exceptions import CryptoError as NaclCryptoError
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.crypto keys", "crypto", error) from error

__all__ = [
    "AESGCM",
    "HKDF",
    "PBKDF2HMAC",
    "PKCS7",
    "Argon2id",
    "ChaCha20Poly1305",
    "Cipher",
    "InvalidSignature",
    "InvalidTag",
    "InvalidUnwrap",
    "NaclCryptoError",
    "UnsupportedAlgorithm",
    "aes_key_unwrap",
    "aes_key_wrap",
    "algorithms",
    "ec",
    "ed25519",
    "hashes",
    "modes",
    "nacl_bindings",
    "padding",
    "rsa",
    "serialization",
    "utils",
    "x25519",
]
