import pyfect as fx
from pyfect.crypto import aead, kdf, key_agreement, native
from pyfect.crypto.aead import Aead
from pyfect.crypto.kdf import Kdf
from pyfect.crypto.key_agreement import KeyAgreement
from pyfect.crypto.secure_random import SecureRandom

INFO = b"example sealed box v1"


@fx.fn
def main():
    random = yield from SecureRandom()
    agreement = yield from KeyAgreement()
    derive = yield from Kdf()
    sealer = yield from Aead()

    recipient = yield from agreement.generate_key_pair(key_agreement.x25519)

    # The sender agrees on a secret with a fresh pair, then stretches it with HKDF:
    # a raw X25519 secret is never a key by itself.
    ephemeral = yield from agreement.generate_key_pair(key_agreement.x25519)
    shared = yield from agreement.derive_shared_secret(ephemeral.private_key, recipient.public_key)
    salt = yield from key_agreement.to_bytes(ephemeral.public_key)
    okm = yield from derive.derive(kdf.hkdf_sha256, shared, salt=salt, info=INFO, length=32)
    key = yield from aead.key(aead.xchacha20_poly1305, okm)
    nonce = yield from random.random_bytes(aead.xchacha20_poly1305.nonce_length)
    box = yield from sealer.encrypt(key, b"for your eyes only", nonce=nonce)

    # The recipient derives the same key from the sender's public key.
    sender_public = yield from key_agreement.public_key(key_agreement.x25519, salt)
    secret = yield from agreement.derive_shared_secret(recipient.private_key, sender_public)
    okm = yield from derive.derive(kdf.hkdf_sha256, secret, salt=salt, info=INFO, length=32)
    opened = yield from aead.key(aead.xchacha20_poly1305, okm)
    print((yield from sealer.decrypt(opened, box, nonce=nonce)))


fx.run_main(main().pipe(fx.provide(native.layer)))
