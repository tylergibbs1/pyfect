from typing import TypedDict

import pyfect as fx
from pyfect import redacted
from pyfect import schema as S
from pyfect.crypto import native
from pyfect.jose import JoseError, jwk, jwt


class Claims(TypedDict):
    sub: str
    role: str


ClaimsSchema = S.Struct(Claims)


@fx.fn
def main():
    secret = yield from jwk.generate_secret("HS256", kid="2026-11")
    key = yield from jwk.import_hmac(secret, "HS256")
    token = yield from jwt.sign(ClaimsSchema, {"sub": "ada", "role": "admin"}, key)
    verified = yield from jwt.verify(ClaimsSchema, token, key, subject="ada")
    print(verified.claims, verified.protected_header.get("kid"))

    head, _, signed = redacted.value(token).rpartition(".")
    forged = f"{head}.{'A' * len(signed)}"
    error = yield from jwt.verify(ClaimsSchema, forged, key).flip()
    print(error.reason.tag if isinstance(error, JoseError) else error)


fx.run_main(main().pipe(fx.provide(native.layer)))
