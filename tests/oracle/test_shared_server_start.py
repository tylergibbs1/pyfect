"""A shared test server whose start did not finish (it raised, or the per-test timeout
stopped it) fails every later test at once with that error. Each later test used to start
it again and wait out its own timeout: one stalled ``docker run`` cost 60 s per test."""

from pathlib import Path

import pytest

SERVERS = ["_clickhouse", "_libsql", "_mssql", "_mysql", "_postgres", "_redis"]

_TESTS = """
import pytest

from oracle import {module} as shared

starts = []


def hangs():
    starts.append(None)
    pytest.fail("test hung: still running after 60s")


shared._start = hangs


def test_first():
    shared.server()


def test_second():
    shared.server()


def test_started_once():
    assert len(starts) == 1
"""


@pytest.mark.parametrize("module", SERVERS)
def test_a_start_that_did_not_finish_fails_later_tests_with_its_error(
    module: str, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1]))
    pytester.makepyfile(test_uses=_TESTS.format(module=module))
    result = pytester.runpytest_subprocess("-p", "no:randomly", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, failed=2)
    result.stdout.fnmatch_lines(
        [
            "*_ test_first _*",
            "E *Failed: test hung: still running after 60s",
            "*_ test_second _*",
            "E *Failed: * did not start in an earlier test: test hung: still running after 60s",
        ]
    )


_NEVER_READY = """
import subprocess

from oracle import _docker
from oracle import {module} as shared

runs = []


def docker(*args, timeout=60):
    if args[0] == "run":
        runs.append(args)
    out = {{
        "run": "fake-container\\n",
        "port": "127.0.0.1:1\\n",
        "stats": "1.9GiB / 2GiB\\n",
        "logs": "the fake server's last words\\n",
    }}.get(args[0], "")
    if args[0] == "inspect":
        state = "status=exited oom_killed=true\\n"
        out = "{running}\\n" if args[2] == "{{{{.State.Running}}}}" else state
    return subprocess.CompletedProcess(["docker", *args], 1 if args[0] == "exec" else 0, out, "")


def refused(*args, **kwargs):
    raise ConnectionResetError(104, "Connection reset by peer")


_docker.docker = docker
_docker.require_docker = lambda: None
_docker.reap_stale = lambda label: []
_docker.pull = lambda image: None
shared._login = refused
shared._STARTUP_TIMEOUT = 0.6


def test_first():
    shared.server()


def test_second():
    shared.server()


def test_started_once():
    assert len(runs) == 1
"""


@pytest.mark.parametrize(("module", "name"), [("_mssql", "SQL Server"), ("_mysql", "MySQL")])
@pytest.mark.parametrize("running", ["true", "false"])
def test_a_container_that_never_serves_fails_once_with_its_state_and_logs(
    module: str, name: str, running: str, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
):
    """The start waits on its own deadline, not the test's alarm (0.3 s here, the start
    0.6 s): the failure names the container's state and logs, and later tests fail at once."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1]))
    pytester.makepyfile(test_uses=_NEVER_READY.format(module=module, running=running))
    result = pytester.runpytest_subprocess(
        "-p", "no:randomly", "-p", "no:cacheprovider", "-p", "_timeout", "-o", "test_timeout=0.3"
    )
    result.assert_outcomes(passed=1, failed=2)
    cause = "stopped (*" if running == "false" else "did not start in 0.6 s (*"
    result.stdout.fnmatch_lines(
        [
            "*_ test_first _*",
            f"E *ContainerFailed: *{name}*{cause}*status=exited oom_killed=true*1.9GiB / 2GiB*",
            "*the fake server's last words*",
            "*_ test_second _*",
            f"E *Failed: * did not start in an earlier test: *{name}*{cause}*",
        ]
    )
    result.stdout.no_fnmatch_line("*test hung*")
