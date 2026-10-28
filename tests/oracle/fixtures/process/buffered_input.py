"""Effect's ``buffered-input.ts`` fixture, in Python: a megabyte written to
a child that never reads it, on standard input or descriptor 3, with the
wait for its exit timed out. The host must finish and stay alive.

    buffered_input.py stdin|fd3
"""

import sys
import time

import pyfect as fx
from pyfect import process, stream
from pyfect.file_system import layer as file_system_layer
from pyfect.layer import merge, provide
from pyfect.path import layer as path_layer
from pyfect.process import InputFd

data = stream.make(bytes(1024 * 1024))
command = (
    process.make(sys.executable, ["-c", "import time; time.sleep(5)"], stdin=data)
    if sys.argv[1] == "stdin"
    else process.make(
        sys.executable,
        ["-c", "import time; time.sleep(5)"],
        stdin="ignore",
        additional_fds={3: InputFd(data)},
    )
)


@fx.fn
def program():
    handle = yield from command
    return (yield from handle.exit_code.timeout(0.1))


services = process.layer.pipe(provide(merge(file_system_layer, path_layer)))
result = fx.run_sync_exit(fx.scoped(program()).pipe(fx.provide(services)))
print("program finished:", type(result).__name__, flush=True)
time.sleep(0.5)
print("still alive after 500ms", flush=True)
