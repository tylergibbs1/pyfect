"""Ports of Effect's ``jose/Jwe.test.ts``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.jose import jwe, jwk
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal

from ._jose import (
    NODE,
    SECRET,
    SECRET_JWK,
    assert_reason,
    b64,
    json_b64,
    layer,
    reference_decrypt,
    text,
    unb64,
    utf8,
)


@testing.effect
def test_encrypts_and_decrypts_compact_dir_a256gcm_tokens_interoperably():
    """encrypts and decrypts compact dir/A256GCM tokens interoperably"""

    @fx.gen
    def program():
        key = yield from jwk.import_dir(redacted({**SECRET_JWK, "kid": "enc-1"}))

        header: dict[str, Any] = {"cty": "text/plain", "tenant": {"id": "one", "roles": ["reader"]}}
        ours = yield from jwe.encrypt(
            utf8("private message"), key, {**header, "alg": "RSA-OAEP", "enc": "A128GCM"}
        )
        their_header, plaintext = reference_decrypt(reveal(ours), SECRET)
        assert text(plaintext) == "private message"
        assert their_header == {"alg": "dir", "enc": "A256GCM", "kid": "enc-1", **header}

        again = yield from jwe.encrypt(utf8("private message"), key)
        assert reveal(again) != reveal(ours)

        token: str = NODE["jwe"]["fromJose"]
        decrypted = yield from jwe.decrypt(token, key)
        assert text(decrypted.plaintext) == "from jose"
        assert decrypted.protected_header == {"alg": "dir", "enc": "A256GCM", **header}
        assert decrypted.key is key

    return program.pipe(fx.provide(layer))


def _flip_first(segment: str) -> str:
    data = bytearray(unb64(segment))
    data[0] ^= 1
    return b64(bytes(data))


@testing.effect
def test_rejects_tampered_ciphertext_other_content_encryption_and_foreign_keys():
    """rejects tampered ciphertext, other content encryption, and foreign keys"""

    @fx.gen
    def program():
        key = yield from jwk.import_dir(redacted(SECRET_JWK))
        other = yield from jwk.import_dir(redacted({"kty": "oct", "k": b64(bytes([9] * 32))}))
        token = reveal((yield from jwe.encrypt(utf8("secret"), key)))
        header, _, iv, ciphertext, tag = token.split(".")

        assert_reason((yield from jwe.decrypt(token, other).flip()), "DecryptionFailed")

        flipped = _flip_first(tag)
        assert_reason(
            (yield from jwe.decrypt(f"{header}..{iv}.{ciphertext}.{flipped}", key).flip()),
            "DecryptionFailed",
        )

        # Authenticated header changes fail decryption, not parsing.
        kid = b64('{"alg":"dir","enc":"A256GCM","kid":"x"}')
        assert_reason(
            (yield from jwe.decrypt(f"{kid}..{iv}.{ciphertext}.{tag}", key).flip()),
            "DecryptionFailed",
        )

        a128: str = NODE["jwe"]["a128"]
        assert_reason((yield from jwe.decrypt(a128, key).flip()), "InvalidToken")

        # A non-empty encrypted key is not ``dir``.
        assert_reason(
            (yield from jwe.decrypt(f"{header}.AAAA.{iv}.{ciphertext}.{tag}", key).flip()),
            "InvalidToken",
        )
        assert_reason(
            (yield from jwe.decrypt(f"{header}.{iv}.{ciphertext}.{tag}", key).flip()),
            "InvalidToken",
        )

    return program.pipe(fx.provide(layer))


@dataclass(frozen=True)
class UnknownKey:
    pass


@testing.effect
def test_resolves_current_and_previous_keys_by_kid_and_preserves_lookup_failures():
    """resolves current and previous keys by kid and preserves lookup failures"""

    @fx.gen
    def program():
        previous = yield from jwk.import_dir(redacted({**SECRET_JWK, "kid": "previous"}))
        current = yield from jwk.import_dir(
            redacted({"kty": "oct", "k": b64(bytes([9] * 32)), "kid": "current"})
        )
        missing = UnknownKey()

        def resolve(header: jwe.ProtectedHeader) -> fx.Effect[jwk.DirKey, UnknownKey]:
            found = [key for key in (previous, current) if key.kid == header.get("kid")]
            return fx.succeed(found[0]) if found else fx.fail(missing)

        for key in (previous, current):
            token = yield from jwe.encrypt(utf8("private message"), key)
            decrypted = yield from jwe.decrypt(token, resolve)
            assert text(decrypted.plaintext) == "private message"
            assert decrypted.protected_header.get("kid") == key.kid
            assert decrypted.key is key

        unknown = yield from jwe.encrypt(utf8("private message"), current, {"kid": "unknown"})
        assert (yield from jwe.decrypt(unknown, resolve).flip()) is missing

    return program.pipe(fx.provide(layer))


@testing.effect
def test_rejects_malformed_tokens_before_resolving_a_key():
    """rejects malformed tokens before resolving a key"""

    @fx.gen
    def program():
        key = yield from jwk.import_dir(redacted(SECRET_JWK))
        token = reveal((yield from jwe.encrypt(utf8("private message"), key)))
        header, _, iv, ciphertext, tag = token.split(".")
        resolutions = 0

        def resolve(_header: jwe.ProtectedHeader) -> fx.Effect[jwk.DirKey]:
            nonlocal resolutions
            resolutions += 1
            return fx.succeed(key)

        extensions: list[dict[str, Any]] = [{"zip": "DEF"}, {"crit": ["tenant"], "tenant": "one"}]
        for extension in extensions:
            unsupported = json_b64({"alg": "dir", "enc": "A256GCM", **extension})
            assert_reason(
                (yield from jwe.decrypt(f"{unsupported}..{iv}.{ciphertext}.{tag}", resolve).flip()),
                "InvalidToken",
            )
            assert_reason(
                (yield from jwe.encrypt(utf8("payload"), key, extension).flip()), "InvalidArgument"
            )

        for invalid in (
            f"{header}.AAAA.{iv}.{ciphertext}.{tag}",
            f"{header}..{iv}.{ciphertext}.AA",
        ):
            assert_reason((yield from jwe.decrypt(invalid, resolve).flip()), "InvalidToken")
        assert resolutions == 0

    return program.pipe(fx.provide(layer))
