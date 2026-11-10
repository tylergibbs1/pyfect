import pyfect as fx
from pyfect import config
from pyfect import config_provider as cp
from pyfect import schema as S
from pyfect.crypto import key_format, mac, native, signature
from pyfect.crypto import schema as CS
from pyfect.crypto.mac import Mac
from pyfect.crypto.signature import Signature

# An HMAC key from base64 in the environment.
hmac_key = config.schema(CS.MacKeyFromBytes(mac.hmac_sha256), "WEBHOOK_KEY")
provider = cp.from_env({"WEBHOOK_KEY": "c2VjcmV0LWtleS1mb3Itd2ViaG9va3MtMDAwMDAwMDA="})

# A public key from PEM; FromFormat schemas decode only as effects.
PublicKeyPem = CS.SignaturePublicKeyFromFormat(key_format.pem(key_format.spki), signature.ed25519)


@fx.fn
def main():
    key = yield from hmac_key.parse(provider)
    tag = yield from (yield from Mac()).sign(key, b"payload")
    print(tag.hex()[:16])

    pair = yield from (yield from Signature()).generate_key_pair(signature.ed25519)
    pem = yield from key_format.encode(key_format.pem(key_format.spki), pair.public_key)
    print(pem.splitlines()[0])
    decoded = yield from S.decode_effect(PublicKeyPem)(pem)
    print(decoded.algorithm.name)

    # Private keys are written back only when asked to.
    error = yield from S.encode_effect(
        CS.SignaturePrivateKeyFromFormat(key_format.pkcs8, signature.ed25519)
    )(pair.private_key).flip()
    print(error)


fx.run_main(main().pipe(fx.provide(native.layer)))
