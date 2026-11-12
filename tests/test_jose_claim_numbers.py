"""A registered time claim is a JavaScript number, as in Effect's ``Jwt.verify``.

``JSON.parse`` reads an integer too large for a double as ``Infinity``, which ``exp`` /
``nbf`` / ``iat`` reject; Python reads it exactly, so a token whose ``exp`` was a 400-digit
integer used to verify as never expiring.
"""

import pytest
from oracle._jose import SECRET_JWK, layer
from oracle.test_jose_jwt import claim_failure

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.jose import jwk, jws, jwt

_HUGE = "1" + "0" * 400


@pytest.mark.parametrize(
    ("claim", "value"),
    [("exp", _HUGE), ("nbf", "-" + _HUGE), ("iat", _HUGE)],
)
@testing.effect
def test_a_time_claim_beyond_a_double_is_invalid(claim: str, value: str):
    @fx.gen
    def program():
        key = yield from jwk.import_hmac(fx.redacted.make(SECRET_JWK), "HS256")
        token = yield from jws.sign(f'{{"sub":"a","{claim}":{value}}}'.encode(), key)
        failure = yield from jwt.verify(S.Unknown, token, key).flip()
        assert claim_failure(failure) == (claim, "invalid")

    return program.pipe(fx.provide(layer))
