"""Ports of Effect's ``crypto/Password.test.ts``."""

from __future__ import annotations

import pyfect as fx
from pyfect import testing
from pyfect.crypto import digest, kdf, password, secure_random
from pyfect.crypto.password import Password
from pyfect.crypto.secure_random import SecureRandom

from ._crypto import assert_reason

ARGON2 = "$argon2id$v=19$m=65536,t=2,p=1$c29tZXNhbHQ$CTFhFdXPJO1aFaMaO6Mm5c8y7cJHAph8ArZWb2GRPPc"


@testing.effect
def test_stores_pbkdf2_parameters_with_the_hash_and_detects_when_they_need_updating():
    """stores PBKDF2 parameters with the hash and detects when they need updating"""
    algorithm = kdf.pbkdf2(hash=digest.sha256, iterations=2)
    random = secure_random.make(lambda size: bytes(range(size)))

    @fx.gen
    def program():
        passwords = yield from Password()
        stored = yield from passwords.hash("password")
        # node:crypto pbkdf2Sync("password", salt, 2, 32, "sha256"), salt bytes 0..15.
        assert stored == (
            "$pbkdf2-sha256$i=2,l=32$AAECAwQFBgcICQoLDA0ODw$oP/TQpLk59UZ7g8lEk4MW5SB2IvkD0Zi62y0ueQ/n0E"
        )
        assert (yield from passwords.verify("password", stored)) is True
        assert (yield from passwords.verify("wrong", stored)) is False
        assert (yield from passwords.needs_rehash(stored)) is False
        assert (yield from passwords.needs_rehash(stored.replace("i=2", "i=3"))) is True

    return (
        program.pipe(fx.provide(password.layer(algorithm=algorithm)))
        .pipe(fx.provide(kdf.layer_web_crypto))
        .pipe(fx.provide_service(SecureRandom, random))
    )


@testing.effect
def test_round_trips_canonical_argon2id_and_rejects_malformed_strings():
    """round-trips canonical Argon2id and rejects malformed strings"""

    @fx.gen
    def program():
        assert password.encode((yield from password.decode(ARGON2))) == ARGON2
        for malformed in [
            ARGON2 + "=",
            ARGON2.replace("t=2", "t=02"),
            ARGON2.replace("t=2", "t=9007199254740993"),
            ARGON2.replace("v=19", "v=16"),
            ARGON2.replace("argon2id", "argon2i"),
            ARGON2[: ARGON2.rfind("$")],
        ]:
            error = yield from password.decode(malformed).flip()
            assert error.module == "Password"
            assert_reason(error, "InvalidArgument")

    return program
