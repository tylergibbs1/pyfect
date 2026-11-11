import base64
import json
from typing import TypedDict

import pyfect as fx
from pyfect import redacted
from pyfect import schema as S
from pyfect.crypto import native
from pyfect.jose import JoseError, jwk, jwt


class Session(TypedDict):
    sub: str
    scope: str


SessionSchema = S.Struct(Session)


def segment(data: dict[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


@fx.fn
def main():
    # A dir key is 32 random bytes, shared by whoever seals and opens the tokens.
    secret = yield from jwk.generate_secret("dir", kid="sessions-1")
    key = yield from jwk.import_dir(secret)

    token = yield from jwt.encrypt(SessionSchema, {"sub": "ada", "scope": "read"}, key)
    # Five segments; with dir there is no encrypted key, so the second is empty.
    parts = redacted.value(token).split(".")
    print(len(parts), parts[1] == "")
    opened = yield from jwt.decrypt(SessionSchema, token, key)
    print(opened.claims, opened.protected_header)

    # Only dir with A256GCM is supported: any other alg or enc is refused.
    other = ".".join([segment({"alg": "dir", "enc": "A128GCM"}), *parts[1:]])
    error = yield from jwt.decrypt(SessionSchema, other, key).flip()
    print(error.reason.tag if isinstance(error, JoseError) else error)


fx.run_main(main().pipe(fx.provide(native.layer)))
