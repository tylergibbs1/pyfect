import tempfile

import pyfect as fx
from pyfect import layer, platform
from pyfect import schema as S
from pyfect.persistence import KeyValueStore, key_value_store


class Settings(S.Class, identifier="Settings"):
    theme: str
    font_size: int


@fx.fn
def program():
    kv = yield from KeyValueStore()
    yield from kv.set("greeting", "hello")
    print((yield from kv.get("greeting")))
    print((yield from kv.get("missing")))

    # A prefix keeps one part of a program's keys apart from the rest.
    users = kv.prefix("user:")
    yield from users.set("1", "Ada")
    print((yield from kv.has("user:1")))

    # A schema store holds typed values, written as JSON text.
    settings = kv.to_schema_store(Settings)
    yield from settings.set("ada", Settings(theme="dark", font_size=14))
    yield from settings.modify("ada", lambda s: Settings(theme=s.theme, font_size=16))
    print((yield from settings.get("ada")))


# A file per key, in a directory; key_value_store.layer_memory is the same in a dict.
with tempfile.TemporaryDirectory() as directory:
    Store = key_value_store.layer_file_system(directory).pipe(layer.provide(platform.layer))
    fx.run_main(program().pipe(fx.provide(Store)))
