import pyfect as fx
from pyfect.crypto import aead, kdf, key_wrap, native
from pyfect.crypto.aead import Aead
from pyfect.crypto.kdf import Kdf
from pyfect.crypto.key_wrap import KeyWrap
from pyfect.crypto.secure_random import SecureRandom


@fx.fn
def main():
    random = yield from SecureRandom()
    sealer = yield from Aead()
    wrapper = yield from KeyWrap()
    derive = yield from Kdf()

    # One data key per message; only its wrapped form is stored.
    data_key = yield from sealer.generate_key(aead.xchacha20_poly1305)
    nonce = yield from random.random_bytes(aead.xchacha20_poly1305.nonce_length)
    sealed = yield from sealer.encrypt(data_key, b"the launch code", nonce=nonce, aad=b"msg-1")

    # The key-encryption key comes from a passphrase, through Argon2id.
    salt = yield from random.random_bytes(16)
    stretched = yield from derive.derive(kdf.argon2id(), b"correct horse", salt=salt, length=32)
    kek = yield from key_wrap.key(key_wrap.aes256_kw, stretched)
    wrapped = yield from wrapper.wrap(kek, data_key)
    print(len(wrapped))

    # A new passphrase only rewraps the data key; the sealed message stays as it is.
    restored = yield from wrapper.unwrap(kek, aead.xchacha20_poly1305, wrapped)
    print((yield from sealer.decrypt(restored, sealed, nonce=nonce, aad=b"msg-1")))

    wrong = yield from derive.derive(kdf.argon2id(), b"wrong horse", salt=salt, length=32)
    wrong_kek = yield from key_wrap.key(key_wrap.aes256_kw, wrong)
    refused = wrapper.unwrap(wrong_kek, aead.xchacha20_poly1305, wrapped)
    print((yield from refused.flip()).reason.tag)


fx.run_main(main().pipe(fx.provide(native.layer)))
