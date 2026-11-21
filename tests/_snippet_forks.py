"""Runs `python -P <args>` as a fork of one interpreter that has already imported what the
programs share.

A snippet's run was mostly importing pyfect: 0.2 s of its 0.35 s of CPU on a laptop, and CI's
runners (two cores, two threads each) are about twice as slow. `Forks` starts this file once
(`python -P _snippet_forks.py module...`); it imports the modules it is given, freezes them
out of the garbage collector, and forks a child per run. The child takes the run's
environment, files for its output and empty input, and runs the program as `python -P` would:
a script with `runpy` as `__main__`, `-c` code with `exec`. It exits as an interpreter does,
so `atexit` handlers (`_count_sleeps.py`'s report) run and an uncaught error exits 1 with its
traceback. pyfect resets its threads after a fork (`scheduler.py`, `_blocking_pool.py`), and
`random` reseeds.

`gc.freeze()` matters as much as the imports: without it each child's collections walked, and
so copied, every object the server had imported, and preloading more modules made the runs
slower (225 snippets took 62 s of CPU with every shared module preloaded, 40 s with pyfect
alone, 15 s with every shared module frozen, against 76 s started fresh).

A run under pytest needs pyfect imported after pytest is configured (`_count_sleeps.py`), so
those still start an interpreter of their own.
"""

import contextlib
import gc
import importlib
import importlib.util
import json
import os
import runpy
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Sequence
from concurrent.futures import Future
from pathlib import Path
from types import FrameType, ModuleType
from typing import IO, NoReturn, TypedDict

TIMEOUT = 60
"""Seconds a run may take: then its child prints every thread's stack and exits 1."""


class _Request(TypedDict):
    id: int
    argv: list[str]
    env: dict[str, str]
    out: str
    err: str


class _Run(BaseException):
    """Raised in a forked child, out of the server's loop, to run `argv` at the top level."""

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv


def _start_child(request: _Request) -> NoReturn:
    signal.set_wakeup_fd(-1)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    for fd, path in ((1, request["out"]), (2, request["err"])):
        target = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.dup2(target, fd)
        os.close(target)
    os.close(devnull)
    os.environ.clear()
    os.environ.update(request["env"])
    _hang_killer().dump_stacks_then_kill(TIMEOUT, refresh=False)
    raise _Run(request["argv"])


def _wake(signum: int, frame: FrameType | None) -> None:
    """SIGCHLD's handler: the wakeup fd, not this, tells the loop a child exited."""


def _hang_killer() -> ModuleType:
    """``tests/_thread_cpu_timer.py``, loaded by its path: a run's ``sys.path`` must be what
    ``python -P`` gives it, without this directory. Without ``refresh`` its dump has the
    run's threads as they are at its start (its main thread): a daemon thread of ours would
    be among the threads a program counts or prints."""
    path = Path(__file__).with_name("_thread_cpu_timer.py")
    spec = importlib.util.spec_from_file_location("_thread_cpu_timer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _preload(modules: list[str]) -> None:
    for module in modules:
        # Not installed: a run that imports it fails as it would without the server.
        with contextlib.suppress(ModuleNotFoundError):
            importlib.import_module(module)
    gc.freeze()  # see the module's docstring


def _drain(fd: int) -> None:
    with contextlib.suppress(BlockingIOError):
        while os.read(fd, 512):
            pass


def _serve(preload: list[str]) -> None:
    """Imports `preload`, then forks a child per request line on stdin; writes `id exit-code`
    to stdout when it ends."""
    _preload(preload)
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_r, False)
    os.set_blocking(wake_w, False)
    signal.set_wakeup_fd(wake_w)
    signal.signal(signal.SIGCHLD, _wake)
    selector = selectors.DefaultSelector()
    selector.register(0, selectors.EVENT_READ)
    selector.register(wake_r, selectors.EVENT_READ)
    running: dict[int, int] = {}
    pending = b""
    open_input = True
    while open_input or running:
        for key, _ in selector.select():
            if key.fd == wake_r:
                _drain(wake_r)
                continue
            chunk = os.read(0, 1 << 16)
            if not chunk:
                open_input = False
                selector.unregister(0)
                continue
            *lines, pending = (pending + chunk).split(b"\n")
            for line in lines:
                request: _Request = json.loads(line)
                pid = os.fork()
                if pid == 0:
                    selector.close()
                    os.close(wake_r)
                    os.close(wake_w)
                    _start_child(request)
                running[pid] = request["id"]
        while running:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            code = os.waitstatus_to_exitcode(status)
            os.write(1, f"{running.pop(pid)} {code}\n".encode())


def _run_as_python(argv: list[str]) -> None:
    """What `python -P <argv>` does with a script or `-c` code."""
    if argv[0] == "-c":
        sys.argv = ["-c", *argv[2:]]
        main = ModuleType("__main__")
        sys.modules["__main__"] = main
        exec(compile(argv[1], "<string>", "exec"), main.__dict__)
    else:
        sys.argv = argv
        runpy.run_path(argv[0], run_name="__main__")


class Forks:
    """Runs programs as `python -P <args>` would, each in a fork of a server that imported
    `preload` (modules the programs share). `run` may be called from any thread; close it when
    done."""

    def __init__(self, cwd: Path, preload: Sequence[str]) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="snippet-forks-")
        self._server = subprocess.Popen(
            [sys.executable, "-P", __file__, *preload],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=cwd,
            env=dict(os.environ),
        )
        self._lock = threading.Lock()
        self._next = 0
        self._waiting: dict[int, Future[int]] = {}
        self._reader = threading.Thread(target=self._read, name="snippet-forks", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        stdout = self._server.stdout
        assert stdout is not None
        for line in stdout:
            number, code = line.split()
            with self._lock:
                future = self._waiting.pop(int(number))
            future.set_result(int(code))
        with self._lock:
            waiting, self._waiting = self._waiting, {}
        for future in waiting.values():
            future.set_exception(RuntimeError("the snippet fork server exited"))

    def run(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        future: Future[int] = Future()
        with self._lock:
            number = self._next
            self._next += 1
            self._waiting[number] = future
            out, err = (Path(self._dir.name) / f"{number}.{s}" for s in ("out", "err"))
            request: _Request = {
                "id": number,
                "argv": list(args),
                "env": os.environ | (env or {}),
                "out": str(out),
                "err": str(err),
            }
            stdin = self._server.stdin
            assert stdin is not None
            stdin.write(json.dumps(request).encode() + b"\n")
            stdin.flush()
        code = future.result(timeout=TIMEOUT + 30)
        done = subprocess.CompletedProcess(
            [sys.executable, "-P", *args], code, _read_text(out), _read_text(err)
        )
        out.unlink()
        err.unlink()
        return done

    def close(self) -> None:
        stdin: IO[bytes] | None = self._server.stdin
        assert stdin is not None
        stdin.close()
        self._server.wait(timeout=TIMEOUT)
        self._reader.join()
        stdout = self._server.stdout
        assert stdout is not None
        stdout.close()
        self._dir.cleanup()


def _read_text(path: Path) -> str:
    """As `subprocess.run(..., text=True)` decodes a child's output."""
    with open(path, encoding=None, errors="strict", newline=None) as file:
        return file.read()


if __name__ == "__main__":
    argv: list[str] | None = None
    try:
        _serve(sys.argv[1:])
    except _Run as run:
        argv = run.argv
    # Outside the handler, so the program's own errors are not chained to `_Run`.
    if argv is not None:
        _run_as_python(argv)
