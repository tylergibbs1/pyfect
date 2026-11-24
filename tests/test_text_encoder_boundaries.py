"""Text becomes bytes as Effect's ``TextEncoder`` makes them: a lone surrogate is U+FFFD.

A ``str`` can hold a lone surrogate (a JSON ``"\\ud800"`` decodes to one). Effect writes it as
EF BF BD wherever it encodes text; ``"surrogatepass"`` writes the surrogate's own three bytes
(ED A0 80), so a password hash or a percent-encoded URL part made in one runtime would not match
the other's. These run each such boundary on a lone surrogate.
"""

from __future__ import annotations

import base64
import hashlib

import pyfect as fx
from pyfect.crypto import digest, kdf, password, secure_random
from pyfect.crypto.password import Password
from pyfect.crypto.secure_random import SecureRandom
from pyfect.http import url

_SALT = bytes(range(16))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode().rstrip("=")


def _effect_phc(text_encoder_bytes: bytes) -> str:
    """The PHC string Effect's ``Password`` writes: PBKDF2-SHA256 over the TextEncoder bytes."""
    derived = hashlib.pbkdf2_hmac("sha256", text_encoder_bytes, _SALT, 2, 32)
    return f"$pbkdf2-sha256$i=2,l=32${_b64(_SALT)}${_b64(derived)}"


def test_a_password_with_a_lone_surrogate_hashes_and_verifies_as_effects_does() -> None:
    effect_phc = _effect_phc("pässword\ufffd".encode())

    @fx.gen
    def program():
        passwords = yield from Password()
        stored = yield from passwords.hash("pässword\ud800")
        verifies = yield from passwords.verify("pässword\ud800", effect_phc)
        return stored, verifies

    algorithm = kdf.pbkdf2(hash=digest.sha256, iterations=2)
    random = secure_random.make(lambda size: bytes(range(size)))
    stored, verifies = fx.run_blocking(
        program.pipe(fx.provide(password.layer(algorithm=algorithm)))
        .pipe(fx.provide(kdf.layer_web_crypto))
        .pipe(fx.provide_service(SecureRandom, random))
        .or_die()
    )
    assert stored == effect_phc
    assert verifies is True


def test_a_url_username_or_password_with_a_lone_surrogate_percent_encodes_u_fffd() -> None:
    base = url.parse("http://host/")
    assert url.set_username(base, "a\ud800").username == "a%EF%BF%BD"
    assert url.set_password(base, "b\udc00").password == "b%EF%BF%BD"
