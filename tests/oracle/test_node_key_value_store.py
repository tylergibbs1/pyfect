"""Ports of Effect's ``platform-node/test/KeyValueStore.test.ts``:
``layer_file_system`` on the live ``FileSystem`` and ``Path``.

Each test's docstring is the Effect test title. An error's ``method`` is
the Python method's name (``get_bytes`` for Effect's ``getUint8Array``).
"""

import pyfect as fx
from pyfect import file_system, path, testing
from pyfect.persistence import key_value_store as kvs

_PLATFORM = fx.layer.merge(file_system.layer, path.layer)


@testing.effect
def test_rejects_invalid_keys_without_modifying_the_file_system():
    """KeyValueStore / layerFileSystem / rejects invalid keys without modifying the file system"""

    def body():
        fs = yield from file_system.FileSystem()
        root = yield from fs.make_temp_directory_scoped()
        directory = f"{root}/store"
        sibling = f"{root}/sibling.txt"
        yield from fs.make_directory(directory)
        yield from fs.write_file_string(sibling, "sibling")

        def check():
            store = yield from kvs.KeyValueStore()
            for key in ("", ".", ".."):
                operations = [
                    ("get", store.get(key).as_void()),
                    ("get_bytes", store.get_bytes(key).as_void()),
                    ("set", store.set(key, "value").as_void()),
                    ("remove", store.remove(key).as_void()),
                    ("has", store.has(key).as_void()),
                ]
                for method, operation in operations:
                    error = yield from operation.flip()
                    assert isinstance(error, kvs.KeyValueStoreError)
                    assert error.method == method
                    assert error.key == key

        layer = kvs.layer_file_system(directory).pipe(fx.provide(_PLATFORM))
        yield from fx.gen(check).pipe(fx.provide(layer))

        assert (yield from fs.exists(directory))
        assert (yield from fs.read_directory(directory)) == []
        assert (yield from fs.read_file_string(sibling)) == "sibling"

    yield from fx.gen(body).pipe(fx.provide(file_system.layer))
