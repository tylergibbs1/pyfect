"""JOSE (Effect's ``effect/jose``): JSON Web Keys, Key Sets, Signatures,
Encryption and Tokens on ``pyfect.crypto``.

- ``jwk``: generate, import and export keys; RFC 7638 thumbprints.
- ``jwks``: the ``Jwks`` service resolving a token's key, from a fixed or
  a remote key set.
- ``jws``: compact signatures (HS*, RS*, PS*, ES*, EdDSA).
- ``jwe``: compact encryption with a shared key (``dir`` / ``A256GCM``).
- ``jwt``: claims described by a schema, signed or encrypted, verified
  against a claims policy.

Every failure is a ``JoseError`` (``jose_error``).
"""

from pyfect.jose import jose_error, jwe, jwk, jwks, jws, jwt
from pyfect.jose.jose_error import JoseError

__all__ = ["JoseError", "jose_error", "jwe", "jwk", "jwks", "jws", "jwt"]
