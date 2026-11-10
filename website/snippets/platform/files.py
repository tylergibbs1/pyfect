import os

import pyfect as fx
from pyfect import platform
from pyfect.file_system import FileSystem
from pyfect.path import Path


@fx.fn
def program():
    fs = yield from FileSystem()
    path = yield from Path()
    # Removed, with everything in it, when the scope closes.
    root = yield from fs.make_temp_directory_scoped(prefix="notes-")
    notes = path.join(root, "notes.txt")

    yield from fs.write_file_string(notes, "milk\neggs\nbread\n")
    print(repr((yield from fs.read_file_string(notes))))

    # A large file is better read as a stream of byte chunks.
    lines = yield from fs.stream(notes, chunk_size=4).decode_text().split_lines().run_collect()
    print(lines)
    print("exists:", (yield from fs.exists(notes)))

    # Paths under a root matching a glob, sorted by name, depth first.
    yield from fs.make_directory(path.join(root, "drafts"))
    yield from fs.write_file_string(path.join(root, "drafts", "todo.txt"), "")
    print((yield from fs.glob("**/*.txt", root=root)))
    # An excluded directory is not read at all.
    print((yield from fs.glob("**/*.txt", root=root, exclude=("drafts",))))
    return root


root = fx.run_main(fx.scoped(program()).pipe(fx.provide(platform.layer)))
assert not os.path.exists(root)
