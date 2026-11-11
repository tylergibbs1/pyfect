from dataclasses import replace
from typing import TypedDict

import pyfect as fx
from pyfect import clock
from pyfect import schema as S
from pyfect.crypto import native
from pyfect.jose import JoseError, jwk, jwt


class Claims(TypedDict):
    sub: str
    iat: int
    exp: int


ClaimsSchema = S.Struct(Claims)


@fx.fn
def issue(key: jwk.PrivateKey, subject: str, lifetime_seconds: int):
    # `iat` and `exp` are NumericDates, whole seconds, which the claims carry themselves.
    now = int((yield from clock.current_time_millis()) // 1000)
    claims: Claims = {"sub": subject, "iat": now, "exp": now + lifetime_seconds}
    return (yield from jwt.sign(ClaimsSchema, claims, key))


@fx.fn
def main():
    pair = yield from jwk.generate_key_pair("EdDSA")
    # The RFC 7638 thumbprint as `kid`: the imported keys are dataclasses, so
    # `replace` sets it, and `export_public` writes it into the served JWK.
    kid = yield from jwk.thumbprint(pair.public_key)
    signing = replace((yield from jwk.import_private(pair.private_key, "EdDSA")), kid=kid)
    verifying = replace((yield from jwk.import_public(pair.public_key, "EdDSA")), kid=kid)
    print((yield from jwk.export_public(verifying)).get("kid") == kid)

    token = yield from issue(signing, "ada", 3600)
    verified = yield from jwt.verify(
        ClaimsSchema, token, verifying, subject="ada", required_claims=["iat", "exp"]
    )
    print(verified.claims["sub"], verified.protected_header.get("kid") == kid)

    expired = yield from issue(signing, "ada", -60)
    error = yield from jwt.verify(ClaimsSchema, expired, verifying).flip()
    print(error.reason.message if isinstance(error, JoseError) else error)


fx.run_main(main().pipe(fx.provide(native.layer)))
