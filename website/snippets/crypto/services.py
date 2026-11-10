import pyfect as fx
from pyfect.crypto import aead, digest, native, signature
from pyfect.crypto.aead import Aead
from pyfect.crypto.digest import Digest
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.signature import Signature


@fx.fn
def main():
    random = yield from SecureRandom()
    print(len((yield from random.uuid_v7())))

    hashes = yield from Digest()
    print((yield from hashes.digest_hex(digest.sha256, b"abc"))[:16])

    # A fresh nonce for every message under one key.
    sealer = yield from Aead()
    key = yield from sealer.generate_key(aead.aes256_gcm)
    nonce = yield from random.random_bytes(aead.aes256_gcm.nonce_length)
    sealed = yield from sealer.encrypt(key, b"attack at dawn", nonce=nonce, aad=b"v1")
    print((yield from sealer.decrypt(key, sealed, nonce=nonce, aad=b"v1")))
    tampered = sealer.decrypt(key, sealed, nonce=nonce, aad=b"v2")
    print((yield from tampered.flip()).message)

    signer = yield from Signature()
    pair = yield from signer.generate_key_pair(signature.ed25519)
    signed = yield from signer.sign(pair.private_key, b"release 1.2")
    print((yield from signer.verify(pair.public_key, signed, b"release 1.2")))
    print(pair.private_key)


fx.run_main(main().pipe(fx.provide(native.layer)))
