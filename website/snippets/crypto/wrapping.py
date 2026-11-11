import json

import pyfect as fx
from pyfect.crypto import aead, key_format, key_wrap, native
from pyfect.crypto.key_format import JsonWebKey
from pyfect.crypto.key_wrap import KeyWrap


@fx.fn
def main():
    wrapper = yield from KeyWrap()

    # The recipient keeps the private key and publishes the public one as a JWK.
    pair = yield from wrapper.generate_key_pair(key_wrap.rsa_oaep_sha256)
    published = json.dumps((yield from key_format.encode(key_format.jwk, pair.public_key)))

    # The sender reads the JWK it was sent as a key of the algorithm it names.
    received: dict[str, str] = json.loads(published)
    jwk = JsonWebKey(kty="RSA", n=received["n"], e=received["e"])
    public_key = yield from key_format.decode_public(key_format.jwk, key_wrap.rsa_oaep_sha256, jwk)
    data_key = yield from (yield from aead.Aead()).generate_key(aead.aes256_gcm)
    wrapped = yield from wrapper.wrap(public_key, data_key)
    print(len(wrapped))  # the modulus length: 3072 bits

    restored = yield from wrapper.unwrap(pair.private_key, aead.aes256_gcm, wrapped)
    print(restored.algorithm.name)

    # The same RSA key with the other hash wraps differently, and does not unwrap.
    sha1_key = yield from key_format.decode_public(key_format.jwk, key_wrap.rsa_oaep_sha1, jwk)
    other = yield from wrapper.wrap(sha1_key, data_key)
    error = yield from wrapper.unwrap(pair.private_key, aead.aes256_gcm, other).flip()
    print(error.reason.tag)


fx.run_main(main().pipe(fx.provide(native.layer)))
