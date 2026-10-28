import sys

import pyfect as fx
from pyfect import platform, process
from pyfect.process import ChildProcessSpawner

COUNT = "import time\nfor i in range(3):\n    print('tick', i, flush=True)\n    time.sleep(0.01)"


@fx.fn
def program():
    spawner = yield from ChildProcessSpawner()

    # Run a command and collect everything it printed.
    greeting = yield from spawner.string(process.make(sys.executable, ["-c", "print('hi')"]))
    print(repr(greeting))

    # Read each line as the child writes it.
    ticks = process.make(sys.executable, ["-c", COUNT])
    yield from spawner.stream_lines(ticks).run_for_each(lambda line: fx.console.log("got", line))

    # Or hold the handle: its stdout and stderr are byte streams.
    handle = yield from process.make(sys.executable, ["-c", "import sys; sys.exit(3)"])
    print("exit code:", (yield from handle.exit_code))


fx.run_main(fx.scoped(program()).pipe(fx.provide(platform.layer)))
