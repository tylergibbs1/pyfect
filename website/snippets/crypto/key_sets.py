from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.crypto import native
from pyfect.jose import JoseError, jwk, jwks, jwt
from pyfect.jose.jose_error import KeyNotFound
from pyfect.jose.jwks import Jwks, JwksService, Selection


class Claims(TypedDict):
    sub: str


ClaimsSchema = S.Struct(Claims)

# The app's key store: the served public keys, and the kids revoked since.
served: list[jwk.PublicJwk] = []
revoked: set[str] = set()


@fx.fn
def new_key(kid: str):
    pair = yield from jwk.generate_key_pair("EdDSA", kid=kid)
    served.append(pair.public_key)
    return (yield from jwk.import_private(pair.private_key, "EdDSA"))


@fx.fn
def verify(token: fx.Redacted[str]):
    # A key set read for each request sees the keys as they are now.
    key_set = yield from jwks.make_local({"keys": list(served)})

    # A custom resolver refuses a revoked kid before the key set looks.
    def resolve(selection: Selection) -> fx.Effect[jwk.PublicKey, JoseError]:
        if selection.kid in revoked:
            return fx.fail(JoseError(KeyNotFound()))
        return key_set.resolve(selection)

    verifying = jwt.verify_with_key_set(ClaimsSchema, token, algorithms=["EdDSA"])
    verified = yield from verifying.pipe(fx.provide_service(Jwks, JwksService(resolve=resolve)))
    return verified.claims["sub"]


@fx.fn
def main():
    old = yield from new_key("2026-10")
    token = yield from jwt.sign(ClaimsSchema, {"sub": "ada"}, old)
    print((yield from verify(token)))

    rotated = yield from new_key("2026-11")
    print((yield from verify((yield from jwt.sign(ClaimsSchema, {"sub": "bob"}, rotated)))))

    revoked.add("2026-10")
    error = yield from verify(token).flip()
    print(error.reason.tag if isinstance(error, JoseError) else error)


fx.run_main(main().pipe(fx.provide(native.layer)))
