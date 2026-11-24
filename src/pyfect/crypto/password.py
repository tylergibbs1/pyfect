"""Password storage as PHC strings (Effect's ``effect/crypto/Password``)::

    passwords = yield from Password()
    stored = yield from passwords.hash("hunter2")
    valid = yield from passwords.verify("hunter2", stored)

The ``Password`` service hashes with one configured algorithm, Argon2id or
PBKDF2 from ``kdf``, into a string such as
``$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>`` that records the algorithm,
its costs and the salt. ``verify`` reads them back, so hashes made under an
older policy keep verifying, and ``needs_rehash`` says when to replace them.
``decode`` and ``encode`` convert between PHC strings and ``PasswordHash``
values without a service.

Passwords are UTF-8 encoded without Unicode normalization, as other PHC
implementations do. ``verify`` runs whatever costs the stored hash states, so
``decode`` a hash from an untrusted source and check its algorithm first.
Argon2id needs a ``Kdf`` layer that provides it, such as ``native.layer_kdf``.
"""

from __future__ import annotations

import binascii
import re
from dataclasses import dataclass
from typing import Never, Protocol

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.context import Tag
from pyfect.crypto import _web
from pyfect.crypto.crypto_error import CryptoError, InvalidArgument
from pyfect.crypto.digest import Algorithm as DigestAlgorithm
from pyfect.crypto.digest import name_suffix, sha1, sha256, sha384, sha512
from pyfect.crypto.kdf import Argon2id, Kdf, KdfService, Pbkdf2, argon2id, pbkdf2
from pyfect.crypto.mac import timing_safe_equal
from pyfect.crypto.secure_random import SecureRandom, SecureRandomService
from pyfect.effect import gen, succeed, suspend
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

type Algorithm = Argon2id | Pbkdf2
"""A password hashing algorithm: Argon2id or PBKDF2."""


@dataclass(frozen=True, slots=True)
class PasswordHash:
    """A password hash with the algorithm and salt that produced it."""

    algorithm: Algorithm
    salt: bytes
    hash: bytes


_DIGESTS: dict[str, DigestAlgorithm] = {
    "sha1": sha1,
    "sha256": sha256,
    "sha384": sha384,
    "sha512": sha512,
}
# At most 16 digits, so ``int`` never sees a string past its digit limit.
_NUMBER = "(0|[1-9][0-9]{0,15})"
_B64 = "([A-Za-z0-9+/]+)"
_ARGON2ID = re.compile(rf"\$argon2id\$v=19\$m={_NUMBER},t={_NUMBER},p={_NUMBER}\${_B64}\${_B64}")
_PBKDF2 = re.compile(
    rf"\$pbkdf2-({'|'.join(_DIGESTS)})\$i={_NUMBER}(?:,l={_NUMBER})?\${_B64}\${_B64}"
)
_MAX_SAFE_INTEGER = 2**53 - 1


def _invalid(description: str) -> Effect[Never, CryptoError]:
    return _web.fail("Password", "decode", InvalidArgument(description=description))


def _b64_encode(data: bytes) -> str:
    return binascii.b2a_base64(data, newline=False).decode("ascii").rstrip("=")


def _b64_decode(text: str) -> bytes | None:
    """PHC B64 is standard Base64 without padding; re-encoding rejects
    non-canonical trailing bits."""
    try:
        data = binascii.a2b_base64(text + "=" * (-len(text) % 4), strict_mode=True)
    except binascii.Error:
        return None
    return data if _b64_encode(data) == text else None


def _decode(phc: str) -> Effect[PasswordHash, CryptoError]:
    argon2 = _ARGON2ID.fullmatch(phc)
    match = argon2 or _PBKDF2.fullmatch(phc)
    if match is None:
        return _invalid("expected an argon2id (v=19) or pbkdf2 PHC string")
    groups = match.groups()
    salt = _b64_decode(groups[-2])
    hash = _b64_decode(groups[-1])
    if salt is None or hash is None:
        return _invalid("salt and hash must be unpadded Base64")
    costs = [None if n is None else int(n) for n in (groups[:3] if argon2 else groups[1:3])]
    if any(n is not None and n > _MAX_SAFE_INTEGER for n in costs):
        return _invalid("costs must be safe integers")
    if argon2 is not None:
        memory, passes, parallelism = (n or 0 for n in costs)
        algorithm = argon2id(memory=memory, passes=passes, parallelism=parallelism)
        return succeed(PasswordHash(algorithm, salt, hash))
    iterations, length = costs
    if length is not None and length != len(hash):
        return _invalid("l must equal the hash length")
    algorithm = pbkdf2(hash=_DIGESTS[groups[0]], iterations=iterations or 0)
    return succeed(PasswordHash(algorithm, salt, hash))


def decode(phc: str) -> Effect[PasswordHash, CryptoError]:
    """Parses a PHC string.

    Accepts ``$argon2id$v=19$m=<memory>,t=<passes>,p=<parallelism>$<salt>$<hash>``
    and ``$pbkdf2-<sha1|sha256|sha384|sha512>$i=<iterations>[,l=<length>]$<salt>$<hash>``,
    where ``l``, when present, must equal the hash length. Salt and hash are
    Base64 without padding, and numbers are safe integers in decimal without
    leading zeros. Anything else, including other Argon2 versions and variants,
    bcrypt and scrypt, fails with an ``InvalidArgument`` reason. Costs are
    range-checked when deriving, not here."""
    return suspend(lambda: _decode(phc))


def _params(algorithm: Algorithm) -> str:
    """The identifier and costs, which are what ``needs_rehash`` compares."""
    if isinstance(algorithm, Argon2id):
        return f"argon2id$v=19$m={algorithm.memory},t={algorithm.passes},p={algorithm.parallelism}"
    return f"pbkdf2-{name_suffix(algorithm.hash).lower()}$i={algorithm.iterations}"


def encode(hash: PasswordHash) -> str:
    """Formats ``hash`` as a PHC string. PBKDF2 hashes always include ``l``."""
    length = f",l={len(hash.hash)}" if isinstance(hash.algorithm, Pbkdf2) else ""
    return f"${_params(hash.algorithm)}{length}${_b64_encode(hash.salt)}${_b64_encode(hash.hash)}"


class PasswordService(Protocol):
    def hash(self, password: str | Redacted[str]) -> Effect[str, CryptoError]:
        """Hashes ``password`` with the configured algorithm, a 16-byte random
        salt and a 32-byte output, returning the PHC string."""
        ...

    def verify(self, password: str | Redacted[str], hash: str) -> Effect[bool, CryptoError]:
        """Checks ``password`` against a stored PHC string, with the algorithm
        and salt it records. A wrong password is ``False``; a malformed stored
        hash fails with an ``InvalidArgument`` reason."""
        ...

    def needs_rehash(self, hash: str) -> Effect[bool, CryptoError]:
        """Whether a stored PHC string differs from what ``hash`` would make
        now: another algorithm or cost, or a salt or output length other than
        16 and 32 bytes. Rehash the password after a successful ``verify``
        when it does."""
        ...


class Password(Tag[PasswordService], key="effect/crypto/Password"):
    """Hashes and verifies passwords as PHC strings."""


_SALT_LENGTH = 16
_HASH_LENGTH = 32


def _to_bytes(password: str | Redacted[str]) -> bytes:
    text = redacted_value(password) if isinstance(password, Redacted) else password
    return text_encode(text)


class _Service:
    __slots__ = ("_algorithm", "_kdf", "_random")

    def __init__(self, algorithm: Algorithm, kdf: KdfService, random: SecureRandomService):
        self._algorithm = algorithm
        self._kdf = kdf
        self._random = random

    def hash(self, password: str | Redacted[str]) -> Effect[str, CryptoError]:
        @gen
        def program():
            salt = yield from self._random.random_bytes(_SALT_LENGTH)
            derived = yield from self._kdf.derive(
                self._algorithm, _to_bytes(password), salt=salt, length=_HASH_LENGTH
            )
            return encode(PasswordHash(self._algorithm, salt, derived))

        return program

    def verify(self, password: str | Redacted[str], hash: str) -> Effect[bool, CryptoError]:
        @gen
        def program():
            stored = yield from decode(hash)
            derived = yield from self._kdf.derive(
                stored.algorithm, _to_bytes(password), salt=stored.salt, length=len(stored.hash)
            )
            return timing_safe_equal(derived, stored.hash)

        return program

    def needs_rehash(self, hash: str) -> Effect[bool, CryptoError]:
        def differs(stored: PasswordHash) -> bool:
            return (
                _params(stored.algorithm) != _params(self._algorithm)
                or len(stored.salt) != _SALT_LENGTH
                or len(stored.hash) != _HASH_LENGTH
            )

        return decode(hash).map(differs)


def layer(*, algorithm: Algorithm) -> Layer[Password, Never, Kdf | SecureRandom]:
    """Provides ``Password``, hashing new passwords with ``algorithm``.

    There is no default algorithm. ``kdf.argon2id()`` and ``kdf.pbkdf2_sha256``
    carry recommended costs; Argon2id fails with an ``Unsupported`` reason from
    ``Kdf`` when the ``Kdf`` layer does not provide it."""

    @gen
    def build():
        kdf = yield from Kdf()
        random = yield from SecureRandom()
        return _Service(algorithm, kdf, random)

    return layer_effect(Password, build)


__all__ = [
    "Algorithm",
    "CryptoError",
    "Password",
    "PasswordHash",
    "PasswordService",
    "decode",
    "encode",
    "layer",
]
