"""On Windows a batch file (``.bat``, ``.cmd``) runs through ``cmd.exe``, which parses its
arguments again, so an argument could run another command. As Node (and so Effect) does
since CVE-2024-27980, the spawner refuses one unless the command uses ``shell``: the spawn
dies with ``OSError(EINVAL)``, Node's synchronous ``spawn EINVAL``.

The decision is a pure function, tested here on every OS; the spawner is tested end to end
on Windows, and on POSIX a script named ``.cmd`` still runs.
"""

import errno
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import _batch_files, file_system, path, process
from pyfect._batch_files import refuses_batch_file
from pyfect.exit import Failure, Success
from pyfect.layer import Layer, merge, provide_merge
from pyfect.process import ChildProcessSpawner
from pyfect.workers import ProcessWorker

_WINDOWS_ONLY = "on Windows only: cmd.exe runs batch files"
"""A skip ``tests/_skips.py`` allows: ci.yml's windows job runs these."""

type Platform = ChildProcessSpawner | file_system.FileSystem | path.Path

services: Layer[Platform] = process.layer.pipe(provide_merge(merge(file_system.layer, path.layer)))


@pytest.mark.parametrize(
    "program",
    [
        "run.bat",
        "run.cmd",
        "RUN.CMD",
        "run.Bat",
        r"C:\tools\run.cmd",
        "./run.bat",
        "run.cmd.",
        "run.cmd . .",
        "run.bat::$DATA",
    ],
)
def test_a_batch_file_without_shell_is_refused_on_windows(program: str) -> None:
    assert refuses_batch_file(program, shell=False, platform="win32")


@pytest.mark.parametrize(
    "program", ["run", "run.exe", "run.com", "run.cmdx", "run.bat.exe", "cmd", "batch", "x.bat\\y"]
)
def test_other_programs_are_spawned_on_windows(program: str) -> None:
    assert not refuses_batch_file(program, shell=False, platform="win32")


@pytest.mark.parametrize("shell", [True, "cmd.exe"])
def test_a_batch_file_is_spawned_with_shell(shell: bool | str) -> None:
    assert not refuses_batch_file("run.cmd", shell=shell, platform="win32")


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_only_windows_refuses_batch_files(platform: str) -> None:
    assert not refuses_batch_file("run.cmd", shell=False, platform=platform)


def _run(eff: fx.Effect[str, Any, Any]) -> fx.Exit[str, Any]:
    scoped: fx.Effect[str, Any, Any] = fx.scoped(eff)
    return fx.run_blocking_exit(scoped.pipe(fx.provide(services)))


def _string(command: process.Command) -> fx.Effect[str, Any, Any]:
    return ChildProcessSpawner().flat_map(lambda spawner: spawner.string(command))


def _refused(exit: fx.Exit[str, Any]) -> bool:
    if not isinstance(exit, Failure):
        return False
    defect = exit.cause.squash()
    return isinstance(defect, OSError) and defect.errno == errno.EINVAL


def test_the_spawner_dies_with_einval_where_the_host_is_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every OS checks the wiring; the windows job runs the real thing below."""
    monkeypatch.setattr(_batch_files, "current_platform", lambda: "win32")
    assert _refused(_run(_string(process.make("run.CMD", ["a&b"]))))
    with pytest.raises(OSError) as raised:
        ProcessWorker([], executable="python.bat").start()
    assert raised.value.errno == errno.EINVAL


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable script")
def test_a_script_named_cmd_runs_on_posix(tmp_path: Path) -> None:
    script = tmp_path / "run.cmd"
    script.write_text('#!/bin/sh\nprintf "%s" "$1"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    exit = _run(_string(process.make(str(script), ["a&b"])))
    assert isinstance(exit, Success), exit
    assert exit.value == "a&b"


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_ONLY)
@pytest.mark.parametrize("name", ["run.cmd", "RUN.BAT"])
def test_the_spawner_refuses_a_batch_file_on_windows(tmp_path: Path, name: str) -> None:
    script = tmp_path / name
    script.write_text("@echo %~1\r\n")
    for command in [
        process.make(str(script), ["a"]),
        process.make(name, ["a"], env={"PATH": str(tmp_path)}, extend_env=True),
    ]:
        exit = _run(_string(command))
        assert _refused(exit), exit


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_ONLY)
def test_the_spawner_runs_a_batch_file_with_shell_on_windows(tmp_path: Path) -> None:
    script = tmp_path / "run.cmd"
    script.write_text("@echo hello\r\n")
    exit = _run(_string(process.make(f'"{script}"', shell=True)))
    assert isinstance(exit, Success), exit
    assert exit.value.strip() == "hello"


@pytest.mark.skipif(sys.platform != "win32", reason=_WINDOWS_ONLY)
def test_a_process_worker_refuses_a_batch_file_on_windows(tmp_path: Path) -> None:
    script = tmp_path / "python.cmd"
    script.write_text("@echo off\r\n")
    with pytest.raises(OSError) as raised:
        ProcessWorker([], executable=str(script)).start()
    assert raised.value.errno == errno.EINVAL
