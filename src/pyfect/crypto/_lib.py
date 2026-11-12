"""The ``crypto`` extra's libraries, ``cryptography`` and PyNaCl. ``pyfect.crypto``
uses them only through this module, so a missing extra always fails with the
command that installs it (``tests/test_install.py`` checks)."""

from pyfect._extras import missing_extra

try:
    from cryptography.exceptions import (
        InternalError,
        InvalidSignature,
        InvalidTag,
        UnsupportedAlgorithm,
    )
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import (
        ec,
        ed25519,
        padding,
        rsa,
        utils,
        x25519,
    )
    from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes, PublicKeyTypes
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

_UNREADABLE = (ValueError, TypeError, UnsupportedAlgorithm, InternalError)
"""What ``cryptography``'s key loaders raise for bytes they cannot read: an
SPKI naming an algorithm it does not know is ``UnsupportedAlgorithm``, and
OpenSSL's failure to set up a raw key of the wrong size (a PKCS#8 Ed448 key
of 32 bytes) is ``InternalError``."""


def load_der_public_key(data: bytes) -> PublicKeyTypes | None:
    """An SPKI key, ``None`` when ``data`` is not one ``cryptography`` reads.
    Keys are loaded only through here (``tests/test_crypto_key_loading_guard.py``)."""
    try:
        return serialization.load_der_public_key(data)
    except _UNREADABLE:
        return None


def load_der_private_key(data: bytes) -> PrivateKeyTypes | None:
    """An unencrypted PKCS#8 (or traditional) key, ``None`` when ``data`` is
    not one ``cryptography`` reads."""
    try:
        return serialization.load_der_private_key(data, None)
    except _UNREADABLE:
        return None


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
    "load_der_private_key",
    "load_der_public_key",
    "modes",
    "nacl_bindings",
    "padding",
    "rsa",
    "serialization",
    "utils",
    "x25519",
]
